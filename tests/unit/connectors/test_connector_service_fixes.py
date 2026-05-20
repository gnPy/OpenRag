"""Unit tests for ConnectorService and LangflowConnectorService fixes."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.base import ConnectorDocument, DocumentACL

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _make_document(doc_id: str = "doc-123", filename: str = "test.docx"):
    return ConnectorDocument(
        id=doc_id,
        filename=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"dummy content",
        source_url="https://example.com/test.docx",
        acl=DocumentACL(owner="alice"),
        modified_time=datetime(2026, 5, 7),
        created_time=datetime(2026, 5, 1),
    )


@pytest.mark.asyncio
async def test_connector_service_process_connector_document_fixes():
    """Verify that process_connector_document forwards ingest_settings and deletes existing chunks first."""
    from connectors.service import ConnectorService

    service = ConnectorService.__new__(ConnectorService)
    service.session_manager = MagicMock()
    service.index_name = "test-index"
    service.document_service = MagicMock()
    service.models_service = MagicMock()
    service.docling_service = MagicMock()

    opensearch_client = AsyncMock()
    service.session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    document = _make_document()
    ingest_settings = {
        "chunkSize": 500,
        "chunkOverlap": 50,
        "embeddingModel": "custom-embedding",
    }

    # Mock the metadata update
    service._update_connector_metadata = AsyncMock()

    mock_processor = MagicMock()
    mock_processor.process_document_standard = AsyncMock(return_value={"status": "indexed"})

    with (
        patch("utils.file_utils.auto_cleanup_tempfile") as mock_temp,
        patch("connectors.service.open", create=True) as mock_open,
        patch("models.processors.TaskProcessor", return_value=mock_processor),
    ):
        mock_temp.return_value.__enter__.return_value = "/tmp/test.docx"

        result = await service.process_connector_document(
            document=document,
            owner_user_id="alice",
            connector_type="sharepoint",
            jwt_token="token-abc",
            ingest_settings=ingest_settings,
        )

    # Verify pre-delete call
    opensearch_client.delete_by_query.assert_called_once()
    delete_query = opensearch_client.delete_by_query.call_args.kwargs["body"]
    assert delete_query["query"]["term"]["document_id"] == "doc-123"
    opensearch_client.indices.refresh.assert_called_once()

    # Verify process_document_standard propagation
    mock_processor.process_document_standard.assert_called_once()
    kwargs = mock_processor.process_document_standard.call_args.kwargs
    assert kwargs["chunk_size"] == 500
    assert kwargs["chunk_overlap"] == 50
    assert kwargs["embedding_model"] == "custom-embedding"


@pytest.mark.asyncio
async def test_langflow_connector_service_sync_connector_files_fixes():
    """Verify that LangflowConnectorService.sync_connector_files passes max_files and supports filename_filter."""
    from connectors.langflow_connector_service import LangflowConnectorService

    service = LangflowConnectorService.__new__(LangflowConnectorService)
    service.task_service = MagicMock()
    service.session_manager = MagicMock()
    service.session_manager.get_user = MagicMock(return_value=None)
    service.docling_service = MagicMock()

    mock_connector = MagicMock()
    mock_connector.is_authenticated = True
    mock_connector.list_files = AsyncMock(
        return_value={
            "files": [
                {"id": "f1", "name": "keep.docx", "mimeType": "application/pdf"},
                {"id": "f2", "name": "skip.docx", "mimeType": "application/pdf"},
            ],
            "nextPageToken": None,
        }
    )
    service.get_connector = AsyncMock(return_value=mock_connector)

    filename_filter = {"keep.docx"}

    # Mock TaskService custom task creation
    service.task_service.create_custom_task = AsyncMock(return_value="task-123")

    task_id = await service.sync_connector_files(
        connection_id="conn-1",
        user_id="alice",
        max_files=10,
        jwt_token="token-abc",
        filename_filter=filename_filter,
    )

    assert task_id == "task-123"
    # Verify max_files is passed to list_files (not limit)
    mock_connector.list_files.assert_called_once_with(None, max_files=10)

    # Verify LangflowConnectorFileProcessor instantiation gets only filtered files
    processor_class_path = "connectors.langflow_connector_service.LangflowConnectorFileProcessor"
    with patch(processor_class_path) as mock_processor_cls:
        await service.sync_connector_files(
            connection_id="conn-1",
            user_id="alice",
            max_files=10,
            jwt_token="token-abc",
            filename_filter=filename_filter,
        )
        # First argument is self, second is connection_id, third is files_to_process
        files_passed = mock_processor_cls.call_args[0][2]
        assert len(files_passed) == 1
        assert files_passed[0]["id"] == "f1"


@pytest.mark.asyncio
async def test_langflow_connector_service_sync_specific_files_folder_validation():
    """Verify ValueError is raised on folder-only selection and folders are excluded from files fallback."""
    from connectors.langflow_connector_service import LangflowConnectorService

    service = LangflowConnectorService.__new__(LangflowConnectorService)
    service.task_service = MagicMock()
    service.session_manager = MagicMock()
    service.session_manager.get_user = MagicMock(return_value=None)
    service.docling_service = MagicMock()

    mock_connector = MagicMock()
    mock_connector.is_authenticated = True

    # Set up mock config for folder expansion
    mock_cfg = MagicMock()
    mock_connector.cfg = mock_cfg

    # Case A: list_files returns nothing, file_infos contains only folders
    # Should raise ValueError
    mock_connector.list_files = AsyncMock(return_value={"files": []})
    service.get_connector = AsyncMock(return_value=mock_connector)

    file_infos_folders_only = [{"id": "folder-1", "name": "My Folder", "isFolder": True}]

    with pytest.raises(ValueError, match="No files to sync after expanding folders"):
        await service.sync_specific_files(
            connection_id="conn-1",
            user_id="alice",
            file_ids=["folder-1"],
            file_infos=file_infos_folders_only,
        )

    # Case B: expansion fails (raises general exception), fallback filters folder items
    mock_connector.list_files = AsyncMock(side_effect=RuntimeError("API error"))
    service.task_service.create_custom_task = AsyncMock(return_value="task-abc")

    file_infos_mixed = [
        {"id": "folder-1", "name": "My Folder", "isFolder": True},
        {"id": "file-1", "name": "My File.docx", "isFolder": False},
    ]

    # Patch the processor class to inspect passed IDs
    processor_class_path = "connectors.langflow_connector_service.LangflowConnectorFileProcessor"
    with patch(processor_class_path) as mock_processor_cls:
        await service.sync_specific_files(
            connection_id="conn-1",
            user_id="alice",
            file_ids=["folder-1", "file-1"],
            file_infos=file_infos_mixed,
        )
        # inspect files passed: the list of expanded_file_ids is the third argument
        files_passed = mock_processor_cls.call_args[0][2]
        # Should exclude "folder-1" and only contain "file-1"
        assert files_passed == ["file-1"]

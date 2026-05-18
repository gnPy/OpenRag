from types import SimpleNamespace

import pytest

from models.processors import TaskProcessor


@pytest.mark.asyncio
async def test_standard_processor_uses_admin_client_for_embedding_mapping(
    tmp_path,
    monkeypatch,
):
    user_client = SimpleNamespace(
        exists_calls=[],
        index_calls=[],
    )
    admin_client = object()
    mapping_clients = []

    async def exists(*, index, id):
        user_client.exists_calls.append({"index": index, "id": id})
        return False

    async def index(**kwargs):
        user_client.index_calls.append(kwargs)

    user_client.exists = exists
    user_client.index = index

    class SessionManager:
        def get_user_opensearch_client(self, user_id, jwt_token):
            assert user_id == "user-1"
            assert jwt_token == "Bearer user-token"
            return user_client

    class ModelsService:
        async def get_litellm_model_name(self, embedding_model):
            return embedding_model

    class EmbeddingClient:
        class Embeddings:
            async def create(self, model, input):
                return SimpleNamespace(
                    data=[
                        SimpleNamespace(embedding=[0.1, 0.2, 0.3])
                        for _ in input
                    ]
                )

        embeddings = Embeddings()

    async def ensure_embedding_field_exists(client, model_name, index_name, dimensions):
        mapping_clients.append(client)
        assert model_name == "text-embedding-3-small"
        assert index_name == "documents"
        assert dimensions == 3
        return "chunk_embedding_text_embedding_3_small"

    monkeypatch.setattr(
        "config.settings.clients",
        SimpleNamespace(
            opensearch=admin_client,
            patched_embedding_client=EmbeddingClient(),
        ),
    )
    monkeypatch.setattr("config.settings.get_index_name", lambda: "documents")
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(knowledge=SimpleNamespace(embedding_model="")),
    )
    monkeypatch.setattr(
        "utils.embedding_fields.ensure_embedding_field_exists",
        ensure_embedding_field_exists,
    )

    file_path = tmp_path / "doc.md"
    file_path.write_text("# Test\n\nhello world", encoding="utf-8")
    document_service = SimpleNamespace(session_manager=SessionManager())
    processor = TaskProcessor(
        document_service=document_service,
        models_service=ModelsService(),
        docling_service=None,
    )

    result = await processor.process_document_standard(
        file_path=str(file_path),
        file_hash="file-1",
        owner_user_id="user-1",
        original_filename="doc.md",
        jwt_token="Bearer user-token",
        embedding_model="text-embedding-3-small",
    )

    assert result == {"status": "indexed", "id": "file-1"}
    assert mapping_clients == [admin_client]
    assert user_client.exists_calls == [{"index": "documents", "id": "file-1"}]
    assert user_client.index_calls

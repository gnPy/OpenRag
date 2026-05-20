from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.langflow_ingest import LangflowIngestBatch, LangflowIngestChunk, ingest_langflow_chunks
from services.document_index_writer import DocumentIndexContext
from services.langflow_file_service import LangflowFileService
from services.langflow_ingest_token_service import LangflowIngestTokenService


@pytest.mark.asyncio
async def test_langflow_ingest_callback_indexes_authoritative_token_context():
    token_service = LangflowIngestTokenService(secret="test-secret" * 4, ttl_seconds=60)
    context = DocumentIndexContext(
        document_id="doc-1",
        filename="source.pdf",
        mimetype="application/pdf",
        embedding_model="text-embedding-3-small",
        owner="user-1",
        allowed_users=["user@example.com"],
        allowed_principals=["u:ms:tenant:user"],
        ingest_run_id="run-1",
    )
    token = token_service.create_token(context)

    class Writer:
        def __init__(self):
            self.calls = []

        async def index_chunks(self, context, chunks, *, final=False):
            self.calls.append((context, chunks, final))
            return {"indexed_chunks": len(chunks), "document_id": context.document_id}

    writer = Writer()
    body = LangflowIngestBatch(
        ingest_run_id="run-1",
        batch_id=1,
        final=True,
        chunks=[
            LangflowIngestChunk(
                id="doc-1_0",
                text="hello",
                vector=[0.1, 0.2],
                page=3,
                metadata={"owner": "forged-owner", "filename": "forged.pdf"},
            )
        ],
    )

    result = await ingest_langflow_chunks(
        body,
        authorization=f"Bearer {token}",
        x_openrag_ingest_token=None,
        token_service=token_service,
        writer=writer,
    )

    indexed_context, chunks, final = writer.calls[0]
    assert result["status"] == "ok"
    assert indexed_context.owner == "user-1"
    assert indexed_context.allowed_users == ["user@example.com"]
    assert indexed_context.allowed_principals == ["u:ms:tenant:user"]
    assert chunks[0].chunk_id == "doc-1_0"
    assert chunks[0].metadata["owner"] == "forged-owner"
    assert final is True

    with pytest.raises(HTTPException):
        await ingest_langflow_chunks(
            body,
            authorization=f"Bearer {token}",
            x_openrag_ingest_token=None,
            token_service=token_service,
            writer=writer,
        )


@pytest.mark.asyncio
async def test_langflow_file_service_sends_backend_callback_tweaks(monkeypatch):
    token_service = LangflowIngestTokenService(secret="test-secret" * 4, ttl_seconds=60)
    captured = {}

    class Response:
        status_code = 200
        reason_phrase = "OK"
        headers = {"content-type": "application/json"}
        text = '{"status":"ok"}'

        def json(self):
            return {"status": "ok"}

    async def langflow_request(method, endpoint, **kwargs):
        captured.update({"method": method, "endpoint": endpoint, **kwargs})
        return Response()

    async def add_provider_credentials_to_headers(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "services.langflow_file_service.clients",
        SimpleNamespace(langflow_request=langflow_request),
    )
    monkeypatch.setattr(
        "utils.langflow_headers.add_provider_credentials_to_headers",
        add_provider_credentials_to_headers,
    )
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(embedding_model="text-embedding-3-small")
        ),
    )

    service = LangflowFileService(ingest_token_service=token_service)
    result = await service.run_ingestion_flow(
        file_paths=["/tmp/source.pdf"],
        file_tuples=[("source.pdf", b"content", "application/pdf")],
        jwt_token="user-token",
        owner="user-1",
        owner_name="User One",
        owner_email="user@example.com",
        connector_type="local",
    )

    assert result == {"status": "ok"}
    payload = captured["json"]
    callback_tweaks = payload["tweaks"][LangflowFileService.INGEST_OPENSEARCH_COMPONENT_ID]
    assert callback_tweaks["openrag_ingest_url"].endswith("/internal/ingest/chunks")
    assert callback_tweaks["openrag_ingest_run_id"]

    decoded_context, _ = token_service.validate_token(callback_tweaks["openrag_ingest_token"])
    assert decoded_context.owner == "user-1"
    assert decoded_context.filename == "source.pdf"
    assert decoded_context.mimetype == "application/pdf"
    assert decoded_context.file_size == len(b"content")
    assert captured["headers"]["X-Langflow-Global-Var-DOCUMENT_ID"] == decoded_context.document_id

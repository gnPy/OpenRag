from uuid import uuid4

import pytest
from opensearchpy import AsyncOpenSearch
from opensearchpy._async.http_aiohttp import AIOHttpConnection

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.openrag_skip_app_onboard,
]


def _build_admin_opensearch_client():
    from config.settings import (
        IBM_AUTH_ENABLED,
        OPENSEARCH_HOST,
        OPENSEARCH_PASSWORD,
        OPENSEARCH_PORT,
        OPENSEARCH_USERNAME,
    )

    if IBM_AUTH_ENABLED:
        pytest.skip("OSS JWT DLS group matching is not used in IBM auth mode")
    if not OPENSEARCH_PASSWORD:
        pytest.skip("OPENSEARCH_PASSWORD is required for direct OpenSearch DLS integration test")

    return AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        connection_class=AIOHttpConnection,
        scheme="https",
        use_ssl=True,
        verify_certs=False,
        ssl_assert_fingerprint=None,
        http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
        http_compress=True,
    )


async def _search_visible_document_ids(opensearch_client, index_name: str) -> set[str]:
    response = await opensearch_client.search(
        index=index_name,
        body={
            "query": {"match_all": {}},
            "sort": [{"document_id": "asc"}],
            "_source": ["document_id"],
            "size": 10,
        },
    )
    return {hit["_source"]["document_id"] for hit in response.get("hits", {}).get("hits", [])}


async def test_opensearch_dls_filters_group_only_documents():
    """Prove allowed_groups is enforced by OpenSearch DLS roles.

    This test avoids live connector dependencies. The admin client seeds a
    documents* index with group-only docs, then user-scoped OpenSearch clients
    search with JWT roles that should and should not match those groups.
    """
    from config.settings import INDEX_BODY, clients
    from session_manager import SessionManager, User
    from utils.opensearch_utils import setup_opensearch_security

    admin_client = _build_admin_opensearch_client()
    try:
        is_reachable = await admin_client.ping()
    except Exception:
        is_reachable = False
    if not is_reachable:
        await admin_client.close()
        pytest.skip("OpenSearch is not reachable")

    index_name = f"documents_group_acl_dls_{uuid4().hex}"
    matching_group = "g:test:tenant:engineering"
    other_group = "g:test:tenant:sales"

    try:
        await setup_opensearch_security(admin_client)

        await admin_client.indices.create(index=index_name, body=INDEX_BODY)
        await admin_client.bulk(
            body=[
                {"index": {"_index": index_name, "_id": "engineering-doc"}},
                {
                    "document_id": "engineering-doc",
                    "filename": "engineering.md",
                    "text": "Visible only to engineering",
                    "owner": "external-owner",
                    "allowed_users": [],
                    "allowed_groups": [matching_group],
                },
                {"index": {"_index": index_name, "_id": "sales-doc"}},
                {
                    "document_id": "sales-doc",
                    "filename": "sales.md",
                    "text": "Visible only to sales",
                    "owner": "external-owner",
                    "allowed_users": [],
                    "allowed_groups": [other_group],
                },
            ],
            refresh=True,
        )

        session_manager = SessionManager("test")
        user = User(
            user_id="group-dls-user",
            email="group-dls-user@example.com",
            name="Group DLS User",
        )
        matching_token = session_manager.create_opensearch_jwt_token(
            user,
            group_roles=[matching_group],
            ttl_seconds=120,
        )
        no_group_token = session_manager.create_opensearch_jwt_token(
            user,
            group_roles=[],
            ttl_seconds=120,
        )

        matching_client = clients.create_user_opensearch_client(matching_token)
        no_group_client = clients.create_user_opensearch_client(no_group_token)
        try:
            assert await _search_visible_document_ids(matching_client, index_name) == {
                "engineering-doc"
            }
            assert await _search_visible_document_ids(no_group_client, index_name) == set()
        finally:
            await matching_client.close()
            await no_group_client.close()
    finally:
        await admin_client.indices.delete(index=index_name, ignore_unavailable=True)
        await admin_client.close()

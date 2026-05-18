from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_onedrive_cached_download_path_returns_document_with_empty_acl(tmp_path):
    from connectors.onedrive.connector import OneDriveConnector

    connector = OneDriveConnector({"token_file": str(tmp_path / "token.json")})
    connector.authenticate = AsyncMock(return_value=True)
    connector._download_file_from_url = AsyncMock(return_value=b"cached bytes")
    connector.set_file_infos(
        [
            {
                "id": "cached-file",
                "name": "cached.pdf",
                "mimeType": "application/pdf",
                "downloadUrl": "https://download.example/cached.pdf",
                "webUrl": "https://onedrive.example/cached.pdf",
                "size": 12,
            }
        ]
    )

    doc = await connector.get_file_content("cached-file")

    connector._download_file_from_url.assert_awaited_once_with(
        "https://download.example/cached.pdf"
    )
    assert doc.id == "cached-file"
    assert doc.filename == "cached.pdf"
    assert doc.content == b"cached bytes"
    assert doc.acl.owner == ""
    assert doc.acl.allowed_users == []
    assert doc.acl.allowed_groups == []
    assert doc.acl.allowed_principals == []


@pytest.mark.asyncio
async def test_onedrive_sharing_id_fallback_returns_document_with_empty_acl(tmp_path):
    from connectors.onedrive.connector import OneDriveConnector

    class OAuth:
        def get_access_token(self):
            return "access-token"

    connector = OneDriveConnector({"token_file": str(tmp_path / "token.json")})
    connector.oauth = OAuth()
    connector.authenticate = AsyncMock(return_value=True)
    connector._get_file_metadata_by_id = AsyncMock(return_value=None)
    connector._download_via_shares_endpoint = AsyncMock(return_value=b"shared bytes")

    doc = await connector.get_file_content("drive-id!shared-item")

    connector._download_via_shares_endpoint.assert_awaited_once_with(
        "drive-id!shared-item",
        {"Authorization": "Bearer access-token"},
    )
    assert doc.id == "drive-id!shared-item"
    assert doc.content == b"shared bytes"
    assert doc.acl.owner == ""
    assert doc.acl.allowed_users == []
    assert doc.acl.allowed_groups == []
    assert doc.acl.allowed_principals == []

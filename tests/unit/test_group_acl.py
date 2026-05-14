import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import jwt
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_canonical_group_role_is_compact_and_provider_scoped():
    from utils.group_acl import canonical_group_role

    role = canonical_group_role(
        "m365",
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    )

    assert role == "g:m365:AAAAAAAAAAAAAAAAAAAAAQ:AAAAAAAAAAAAAAAAAAAAAg"


def test_opensearch_jwt_includes_group_roles(monkeypatch):
    from session_manager import SessionManager, User

    monkeypatch.setenv("JWT_SIGNING_KEY", "unit-test-secret-with-32-bytes!!")
    monkeypatch.delenv("OPENSEARCH_JWT_TOKEN", raising=False)

    manager = SessionManager("test")
    user = User(user_id="user-1", email="user@example.com", name="User")

    token = manager.create_opensearch_jwt_token(
        user,
        group_roles=["g:m365:t:g1", "g:m365:t:g2"],
        ttl_seconds=60,
    )
    payload = jwt.decode(
        token.removeprefix("Bearer "),
        "unit-test-secret-with-32-bytes!!",
        algorithms=["HS256"],
        audience=["opensearch", "openrag"],
    )

    assert payload["roles"] == ["openrag_user", "g:m365:t:g1", "g:m365:t:g2"]
    assert payload["sub"] == "user-1"


def test_opensearch_jwt_default_ttl_tracks_ingestion_timeout(monkeypatch):
    from session_manager import SessionManager, User

    monkeypatch.setenv("JWT_SIGNING_KEY", "unit-test-secret-with-32-bytes!!")
    monkeypatch.delenv("OPENSEARCH_JWT_TOKEN", raising=False)
    monkeypatch.delenv("OPENRAG_OPENSEARCH_JWT_TTL", raising=False)
    monkeypatch.setattr("config.settings.INGESTION_TIMEOUT", 3600)

    manager = SessionManager("test")
    user = User(user_id="user-1", email="user@example.com", name="User")

    token = manager.create_opensearch_jwt_token(user)
    payload = jwt.decode(
        token.removeprefix("Bearer "),
        "unit-test-secret-with-32-bytes!!",
        algorithms=["HS256"],
        audience=["opensearch", "openrag"],
    )

    assert payload["exp"] - payload["iat"] == 3900


@pytest.mark.asyncio
async def test_group_acl_service_uses_connector_hooks_generically():
    from services.group_acl_service import GroupACLService
    from session_manager import User

    @dataclass
    class Connection:
        connection_id: str
        connector_type: str
        is_active: bool = True

    class ConnectionManager:
        async def list_connections(self, user_id=None):
            assert user_id == "user-1"
            return [
                Connection("sharepoint-1", "sharepoint"),
                Connection("custom-1", "custom"),
            ]

    class Connector:
        def __init__(self, roles):
            self.roles = roles

        async def get_current_user_group_roles(self):
            return self.roles

    class ConnectorService:
        connection_manager = ConnectionManager()

        async def get_connector(self, connection_id):
            return {
                "sharepoint-1": Connector(["g:m365:t:g1", "g:m365:t:g2"]),
                "custom-1": Connector(["g:custom:t:g2", "g:m365:t:g1"]),
            }[connection_id]

    service = GroupACLService(ConnectorService(), cache_ttl_seconds=0)
    roles = await service.get_user_group_roles(
        User(user_id="user-1", email="user@example.com", name="User")
    )

    assert roles == ["g:m365:t:g1", "g:m365:t:g2", "g:custom:t:g2"]


def test_group_acl_service_invalidation_drops_cache_and_locks():
    from services.group_acl_service import GroupACLService

    service = GroupACLService(connector_service=object(), cache_ttl_seconds=60)
    service._cache["user-1"] = (999999.0, ["g:test:t:g1"])
    service._locks["user-1"] = asyncio.Lock()
    service._cache["user-2"] = (999999.0, ["g:test:t:g2"])
    service._locks["user-2"] = asyncio.Lock()

    service.invalidate_user("user-1")

    assert "user-1" not in service._cache
    assert "user-1" not in service._locks
    assert "user-2" in service._cache
    assert "user-2" in service._locks

    service.clear()

    assert service._cache == {}
    assert service._locks == {}


def test_security_roles_include_group_acl_terms_query():
    for rel_path in ("securityconfig/roles.yml", "cloud_securityconfig/roles.yml"):
        roles = yaml.safe_load((ROOT / rel_path).read_text())
        dls = roles["openrag_user_role"]["index_permissions"][0]["dls"]
        assert '{"terms":{"allowed_groups":[${user.roles}]}}' in dls


@pytest.mark.asyncio
@pytest.mark.parametrize("service_name", ["standard", "langflow"])
async def test_connector_services_mint_group_jwt_when_session_user_is_missing(
    service_name,
    monkeypatch,
):
    from session_manager import SessionManager

    monkeypatch.setenv("JWT_SIGNING_KEY", "unit-test-secret-with-32-bytes!!")
    monkeypatch.delenv("OPENSEARCH_JWT_TOKEN", raising=False)
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False)

    @dataclass
    class Connection:
        connection_id: str
        connector_type: str
        is_active: bool = True

    class Connector:
        async def get_current_user_group_roles(self):
            return ["g:test:t:g1"]

    class ConnectionManager:
        async def list_connections(self, user_id=None):
            assert user_id == "stored-user-id"
            return [Connection("connection-1", "custom")]

        async def get_connector(self, connection_id):
            assert connection_id == "connection-1"
            return Connector()

    session_manager = SessionManager("test")
    if service_name == "standard":
        from connectors.service import ConnectorService

        service = ConnectorService(
            patched_async_client=None,
            embed_model="test",
            index_name="test-index",
            session_manager=session_manager,
        )
    else:
        from connectors.langflow_connector_service import LangflowConnectorService

        service = LangflowConnectorService(session_manager=session_manager)

    service.connection_manager = ConnectionManager()

    token = await service._get_effective_sync_jwt("stored-user-id")
    payload = jwt.decode(
        token.removeprefix("Bearer "),
        "unit-test-secret-with-32-bytes!!",
        algorithms=["HS256"],
        audience=["opensearch", "openrag"],
    )

    assert payload["sub"] == "stored-user-id"
    assert payload["roles"] == ["openrag_user", "g:test:t:g1"]


def test_google_drive_file_acl_group_is_canonicalized(tmp_path):
    from connectors.google_drive.connector import GoogleDriveConnector
    from connectors.google_drive_acl import google_drive_group_role

    class Execute:
        def execute(self):
            return {
                "permissions": [
                    {
                        "type": "group",
                        "role": "reader",
                        "emailAddress": "Engineering@example.com",
                    },
                    {
                        "type": "user",
                        "role": "owner",
                        "emailAddress": "owner@example.com",
                    },
                ]
            }

    class Permissions:
        def list(self, **kwargs):
            assert kwargs["fileId"] == "file-1"
            return Execute()

    class Service:
        def permissions(self):
            return Permissions()

    connector = GoogleDriveConnector(
        {
            "client_id": "client",
            "client_secret": "secret",
            "token_file": str(tmp_path / "token.json"),
        }
    )
    connector.service = Service()

    acl = connector._extract_google_drive_acl({"id": "file-1"})

    assert acl.owner == "owner@example.com"
    assert acl.allowed_users == ["owner@example.com"]
    assert acl.allowed_groups == [google_drive_group_role("engineering@example.com")]


@pytest.mark.asyncio
async def test_google_drive_group_roles_use_directory_groups(monkeypatch):
    from connectors.google_drive_acl import (
        get_current_user_google_group_roles,
        google_drive_group_role,
    )

    class Credentials:
        id_token = jwt.encode(
            {"email": "user@example.com"},
            "google-test-secret-with-32-bytes",
            algorithm="HS256",
        )

    class Execute:
        def __init__(self, response):
            self.response = response

        def execute(self):
            return self.response

    class Groups:
        def list(self, **kwargs):
            assert kwargs["userKey"] == "user@example.com"
            assert kwargs["domain"] == "example.com"
            assert "customer" not in kwargs
            return Execute(
                {
                    "groups": [
                        {"email": "Engineering@example.com"},
                        {"email": "Security@example.com"},
                    ]
                }
            )

    class DirectoryService:
        def groups(self):
            return Groups()

    def fake_build(*args, **kwargs):
        if args[:2] == ("cloudidentity", "v1"):
            raise RuntimeError("Cloud Identity unavailable")
        assert args[:2] == ("admin", "directory_v1")
        return DirectoryService()

    monkeypatch.setattr("connectors.google_drive_acl.build", fake_build)

    roles = await get_current_user_google_group_roles(
        drive_service=None,
        credentials=Credentials(),
    )

    assert roles == [
        google_drive_group_role("engineering@example.com"),
        google_drive_group_role("security@example.com"),
    ]


@pytest.mark.asyncio
async def test_google_drive_group_roles_prefer_cloud_identity(monkeypatch):
    from connectors.google_drive_acl import (
        get_current_user_google_group_roles,
        google_drive_group_role,
    )

    class Credentials:
        id_token = jwt.encode(
            {"email": "user@example.com"},
            "google-test-secret-with-32-bytes",
            algorithm="HS256",
        )

    class Execute:
        def __init__(self, response):
            self.response = response

        def execute(self):
            return self.response

    class Memberships:
        def searchTransitiveGroups(self, **kwargs):
            assert kwargs["parent"] == "groups/-"
            assert "member_key_id == 'user@example.com'" in kwargs["query"]
            return Execute(
                {
                    "memberships": [
                        {"groupKey": {"id": "Engineering@example.com"}},
                        {"groupKey": {"id": "Security@example.com"}},
                    ]
                }
            )

    class Groups:
        def memberships(self):
            return Memberships()

    class CloudIdentityService:
        def groups(self):
            return Groups()

    def fake_build(*args, **kwargs):
        assert args[:2] == ("cloudidentity", "v1")
        return CloudIdentityService()

    monkeypatch.setattr("connectors.google_drive_acl.build", fake_build)

    roles = await get_current_user_google_group_roles(
        drive_service=None,
        credentials=Credentials(),
    )

    assert roles == [
        google_drive_group_role("engineering@example.com"),
        google_drive_group_role("security@example.com"),
    ]

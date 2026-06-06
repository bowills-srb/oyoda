from fastapi import HTTPException
import asyncio


def test_refresh_token_rotation_claims_are_preserved_and_revocation_is_enforced():
    from app.api.v1.endpoints import operator_app

    refresh = operator_app._make_refresh_token(
        "op_123",
        "admin@oyvoda.com",
        "super_admin",
        scoped_operator_id="tenant_456",
    )
    payload = operator_app._verify(refresh)

    assert payload is not None
    assert payload["email"] == "admin@oyvoda.com"
    assert payload["role"] == "super_admin"
    assert payload["scoped_op"] == "tenant_456"

    operator_app._revoke_jti(payload["jti"])

    assert operator_app._verify(refresh) is None


def test_operator_onboarding_requires_super_admin_scope_for_operator_actions():
    from app.api.v1.endpoints import operator_onboarding

    request = object()
    operator_onboarding._load_current_user = lambda _request: {
        "sub": "sa_001",
        "email": "admin@oyvoda.com",
        "role": "super_admin",
    }

    try:
        operator_onboarding._get_operator_access_context(request)
        raise AssertionError("Expected scoped super admin access to be required")
    except HTTPException as exc:
        assert exc.status_code == 403


def test_operator_onboarding_uses_scoped_operator_for_super_admin_context():
    from app.api.v1.endpoints import operator_onboarding

    request = object()
    operator_onboarding._load_current_user = lambda _request: {
        "sub": "sa_001",
        "email": "admin@oyvoda.com",
        "role": "super_admin",
        "scoped_op": "tenant_456",
    }

    ctx = operator_onboarding._get_operator_access_context(request)

    assert ctx["company_id"] == "tenant_456"
    assert ctx["role"] == "super_admin"


class _RecordingDB:
    def __init__(self):
        self.calls = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))
        return None

    async def commit(self):
        self.commits += 1


def test_store_gmail_creds_resets_inbox_go_live_at_on_connect():
    from app.services.auth.operator_auth_service import OperatorAuthService

    db = _RecordingDB()
    svc = OperatorAuthService()

    asyncio.run(
        svc.store_gmail_creds(
            db,
            operator_id="00000000-0000-0000-0000-000000000111",
            tenant_id="00000000-0000-0000-0000-000000000222",
            watched_email="info@example.com",
            refresh_token="refresh-token",
        )
    )

    statements = "\n".join(stmt for stmt, _ in db.calls)
    assert "ADD COLUMN IF NOT EXISTS inbox_go_live_at" in statements
    assert "inbox_go_live_at" in statements
    assert "inbox_go_live_at=NOW()" in statements
    assert db.commits == 1

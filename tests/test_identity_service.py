"""Real credential/session storage, isolated from any user's existing product."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util

import pytest

from visiondata_gate.product_service import ProductService

PASSWORD = "a synthetic correct password 42"


@pytest.fixture
def identity(tmp_path):
    assert importlib.util.find_spec("visiondata_gate.identity_service") is not None, (
        "Identity backend is not implemented"
    )
    from visiondata_gate.identity_service import IdentityService

    product = ProductService(tmp_path / "product", recover_interrupted=False)
    product.ensure_default_tenant()
    service = IdentityService(product)
    yield service, product
    product.close(wait=True)


def account(name):
    return dict(login_name=name, display_name=name, password=PASSWORD, email=None)


def test_setup_binds_existing_actor_and_register_is_unprivileged(identity):
    identity, product = identity
    assert identity.status()["setup_required"] is True
    admin = identity.setup("usr_local_demo", **account("ADMIN"))
    assert admin["user"]["user_id"] == "usr_local_demo"
    assert admin["user"]["login_name"] == "admin"
    pending = identity.register(**account("new-user"))
    assert pending["status"] == "PENDING" and pending["platform_role"] == "USER"
    with product.store._connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM workspace_members WHERE user_id=?",
                (pending["user_id"],),
            ).fetchone()[0]
            == 0
        )
    assert "access_token" not in pending
    with pytest.raises(Exception, match="identity_authentication_failed"):
        identity.login(login_name="new-user", password=PASSWORD)
    with product.store._connection() as connection:
        columns = [
            row["name"] for row in connection.execute("PRAGMA table_info(users)")
        ]
        assert columns == ["user_id", "display_name", "email", "created_at"]
        credential = dict(
            connection.execute(
                "SELECT * FROM identity_credentials WHERE user_id=?",
                (pending["user_id"],),
            ).fetchone()
        )
        sessions = [
            dict(row) for row in connection.execute("SELECT * FROM identity_sessions")
        ]
    assert PASSWORD not in repr(credential)
    assert admin["access_token"] not in repr(sessions)
    assert credential["kdf_iterations"] >= 600000


def test_setup_concurrency_has_one_winner(identity):
    identity, _ = identity

    def attempt(index):
        try:
            return identity.setup("usr_local_demo", **account(f"admin-{index}"))[
                "user"
            ]["platform_role"]
        except Exception as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert results.count("ADMIN") == 1
    assert results.count("identity_conflict") == 1


def test_approval_disable_and_last_admin(identity):
    identity, _ = identity
    admin = identity.setup("usr_local_demo", **account("admin"))
    aid = admin["user"]["user_id"]
    pending = identity.register(**account("alice"))
    identity.approve(aid, pending["user_id"])
    login = identity.login(login_name="ALICE", password=PASSWORD)
    assert identity.authenticate(login["access_token"])["user_id"] == pending["user_id"]
    identity.set_status(aid, pending["user_id"], "DISABLED")
    with pytest.raises(Exception, match="identity_authentication_failed"):
        identity.authenticate(login["access_token"])
    with pytest.raises(Exception, match="identity_conflict"):
        identity.set_status(aid, aid, "DISABLED")
    with pytest.raises(Exception, match="identity_conflict"):
        identity.set_role(aid, aid, "USER")


def test_sessions_password_rotation_and_reactivation(identity):
    identity, product = identity
    admin = identity.setup("usr_local_demo", **account("admin"))
    aid = admin["user"]["user_id"]
    second = identity.login(login_name="admin", password=PASSWORD)
    principal = identity.authenticate(second["access_token"])
    sessions = identity.list_sessions(aid, principal["session_id"])
    assert len(sessions) == 2 and sum(s["is_current"] for s in sessions) == 1
    identity.revoke_session(aid, principal["session_id"])
    with pytest.raises(Exception, match="identity_authentication_failed"):
        identity.authenticate(second["access_token"])
    identity.change_password(aid, PASSWORD, PASSWORD + " new")
    with pytest.raises(Exception, match="identity_authentication_failed"):
        identity.authenticate(admin["access_token"])
    fresh = identity.login(login_name="admin", password=PASSWORD + " new")
    with product.store._connection(immediate=True) as conn:
        conn.execute(
            "UPDATE identity_sessions SET expires_at='2000-01-01T00:00:00+00:00'"
        )
    with pytest.raises(Exception, match="identity_authentication_failed"):
        identity.authenticate(fresh["access_token"])


def test_owner_management_and_service_authority(identity):
    identity, product = identity
    admin = identity.setup("usr_local_demo", **account("admin"))
    aid = admin["user"]["user_id"]
    uid = identity.register(**account("alice"))["user_id"]
    identity.approve(aid, uid)
    with pytest.raises(Exception, match="identity_forbidden"):
        identity.list_users(uid)
    identity.add_member(aid, "wsp_local_demo", uid)
    assert len(identity.list_members(aid, "wsp_local_demo")) == 2
    with pytest.raises(Exception, match="identity_forbidden"):
        identity.remove_member(uid, "wsp_local_demo", aid)
    with pytest.raises(Exception, match="identity_conflict"):
        identity.remove_member(aid, "wsp_local_demo", aid)
    identity.remove_member(aid, "wsp_local_demo", uid)
    assert len(identity.list_members(aid, "wsp_local_demo")) == 1
    identity.set_status(aid, uid, "DISABLED")
    with pytest.raises(Exception, match="identity_authentication_failed"):
        product.list_workspaces(uid)


def test_throttle_and_validation_are_safe(identity):
    identity, _ = identity
    identity.setup("usr_local_demo", **account("admin"))
    identity.throttle("test", "key", 1, 60)
    with pytest.raises(Exception, match="identity_rate_limited"):
        identity.throttle("test", "key", 1, 60)
    with pytest.raises(Exception, match="invalid_request"):
        identity.register(**{**account("bad name"), "password": "short"})
    pending = identity.register(**account("safe-user"))
    assert pending["status"] == "PENDING"
    with pytest.raises(Exception, match="identity_authentication_failed"):
        identity.login(login_name="missing-user", password=PASSWORD)

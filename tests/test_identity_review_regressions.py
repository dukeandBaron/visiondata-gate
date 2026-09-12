"""Deterministic identity race regressions, backed only by temporary storage."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import threading

import pytest

from visiondata_gate import identity_service as identity_module
from visiondata_gate.identity_service import IdentityError, IdentityService
from visiondata_gate.product_service import ProductService


PASSWORD = "synthetic identity review password 42"
NEW_PASSWORD = "different synthetic review password 73"


@pytest.fixture
def isolated_identity(tmp_path: Path):
    product = ProductService(tmp_path / "product", recover_interrupted=False)
    product.ensure_default_tenant()
    identity = IdentityService(product)
    yield identity, product
    product.close(wait=True)


def _account(name: str) -> dict[str, str]:
    return {"login_name": name, "display_name": name, "password": PASSWORD}


def _admin(identity: IdentityService) -> dict:
    return identity.setup("usr_local_demo", **_account("administrator"))


@pytest.mark.parametrize("change", ["password", "disable_reactivate"])
def test_login_rechecks_credentials_after_concurrent_revocation(
    isolated_identity, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    identity, product = isolated_identity
    admin = _admin(identity)
    actor = admin["user"]["user_id"]
    target = identity.register(**_account("ordinary-user"))["user_id"]
    identity.approve(actor, target)
    old_session = identity.login(login_name="ordinary-user", password=PASSWORD)
    derived = threading.Event()
    release = threading.Event()
    real_derive = identity_module._derive

    def paused_derive(password: bytes, salt: bytes) -> bytes:
        result = real_derive(password, salt)
        if threading.current_thread().name.startswith("identity-race-login"):
            derived.set()
            assert release.wait(timeout=15), "login race was not released"
        return result

    monkeypatch.setattr(identity_module, "_derive", paused_derive)
    with ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="identity-race-login"
    ) as pool:
        future = pool.submit(
            identity.login, login_name="ordinary-user", password=PASSWORD
        )
        try:
            assert derived.wait(timeout=15), "login did not reach the KDF boundary"
            if change == "password":
                identity.change_password(target, PASSWORD, NEW_PASSWORD)
            else:
                identity.set_status(actor, target, "DISABLED")
                identity.set_status(actor, target, "ACTIVE")
        finally:
            release.set()
        with pytest.raises(IdentityError, match="identity_authentication_failed"):
            future.result(timeout=15)

    with product.store._connection() as connection:
        # The raced old credential must not create even an already-revoked token.
        count = connection.execute(
            "SELECT COUNT(*) FROM identity_sessions WHERE user_id=?", (target,)
        ).fetchone()[0]
        assert count == 1
    with pytest.raises(IdentityError, match="identity_authentication_failed"):
        identity.authenticate(old_session["access_token"])
    fresh = identity.login(
        login_name="ordinary-user",
        password=NEW_PASSWORD if change == "password" else PASSWORD,
    )
    assert identity.authenticate(fresh["access_token"])["user_id"] == target


@pytest.mark.parametrize("change", ["demote", "disable"])
def test_concurrent_admin_self_changes_preserve_one_active_admin(
    isolated_identity, change: str
) -> None:
    identity, product = isolated_identity
    admin = _admin(identity)
    first = admin["user"]["user_id"]
    second = identity.register(**_account("second-admin"))["user_id"]
    identity.approve(first, second)
    identity.set_role(first, second, "ADMIN")
    # Independent instances cannot rely on an object-local mutex or cached count.
    other = IdentityService(product)
    barrier = threading.Barrier(2)

    def update(service: IdentityService, actor: str) -> str:
        barrier.wait(timeout=15)
        try:
            if change == "demote":
                service.set_role(actor, actor, "USER")
            else:
                service.set_status(actor, actor, "DISABLED")
        except IdentityError as error:
            return error.code
        return "changed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(update, identity, first),
            pool.submit(update, other, second),
        ]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(results) == ["changed", "identity_conflict"]
    with product.store._connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM identity_credentials "
                "WHERE platform_role='ADMIN' AND status='ACTIVE'"
            ).fetchone()[0]
            == 1
        )


def test_independent_services_observe_setup_and_revocation_without_cached_state(
    isolated_identity,
) -> None:
    identity, product = isolated_identity
    other = IdentityService(product)
    assert other.status()["setup_required"] is True
    admin = _admin(identity)
    actor = admin["user"]["user_id"]
    assert other.status()["identity_required"] is True
    target = identity.register(**_account("ordinary-user"))["user_id"]
    identity.approve(actor, target)
    session = other.login(login_name="ordinary-user", password=PASSWORD)
    assert other.authenticate(session["access_token"])["user_id"] == target
    identity.set_status(actor, target, "DISABLED")
    with pytest.raises(IdentityError, match="identity_authentication_failed"):
        other.authenticate(session["access_token"])
    with pytest.raises(IdentityError, match="identity_authentication_failed"):
        product.list_workspaces(target)
    identity.set_status(actor, target, "ACTIVE")
    with pytest.raises(IdentityError, match="identity_authentication_failed"):
        other.authenticate(session["access_token"])


def test_session_ownership_denial_does_not_revoke_another_users_token(
    isolated_identity,
) -> None:
    identity, _ = isolated_identity
    admin = _admin(identity)
    actor = admin["user"]["user_id"]
    target = identity.register(**_account("ordinary-user"))["user_id"]
    identity.approve(actor, target)
    session = identity.login(login_name="ordinary-user", password=PASSWORD)
    principal = identity.authenticate(session["access_token"])
    # Platform ADMIN is not authority over another user's session API.
    with pytest.raises(IdentityError, match="identity_forbidden"):
        identity.revoke_session(actor, principal["session_id"])
    assert identity.authenticate(session["access_token"])["user_id"] == target


def test_credential_and_session_storage_use_real_kdf_and_token_digest(
    isolated_identity,
) -> None:
    identity, product = isolated_identity
    admin = _admin(identity)
    target = identity.register(**_account("ordinary-user"))["user_id"]
    with product.store._connection() as connection:
        rows = connection.execute(
            "SELECT * FROM identity_credentials ORDER BY user_id"
        ).fetchall()
        session = connection.execute("SELECT * FROM identity_sessions").fetchone()
    assert {row["user_id"] for row in rows} == {admin["user"]["user_id"], target}
    assert len({bytes(row["password_salt"]) for row in rows}) == 2
    for row in rows:
        assert row["kdf_name"] == "pbkdf2-hmac-sha256"
        assert row["kdf_iterations"] >= 600_000
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            PASSWORD.encode("utf-8"),
            bytes(row["password_salt"]),
            row["kdf_iterations"],
            dklen=32,
        )
        assert bytes(row["password_hash"]) == expected
    assert (
        session["token_sha256"]
        == hashlib.sha256(admin["access_token"].encode("ascii")).hexdigest()
    )
    assert admin["access_token"] not in repr(dict(session))


def test_kdf_capacity_is_nonblocking_and_reports_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use a private exhausted limiter so this test cannot seize another test's slot.
    limiter = threading.BoundedSemaphore(1)
    assert limiter.acquire(blocking=False)
    monkeypatch.setattr(identity_module, "_KDF_SLOTS", limiter)
    try:
        with pytest.raises(IdentityError, match="identity_rate_limited") as error:
            identity_module._derive(b"synthetic-test-password", b"synthetic-salt")
        assert error.value.status_code == 429
        assert error.value.retry_after >= 1
        assert "synthetic-test-password" not in str(error.value)
    finally:
        limiter.release()

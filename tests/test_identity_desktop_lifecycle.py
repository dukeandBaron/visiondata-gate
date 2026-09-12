"""Source-level desktop capability compatibility, not an installed-GUI claim."""

from threading import Event

from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.product_service import ProductService


def test_desktop_can_shutdown_after_account_logout_without_business_authority(
    tmp_path, monkeypatch
):
    capability = "synthetic-desktop-lifecycle-capability-20260913"
    monkeypatch.setenv("VISIONDATA_DESKTOP_SESSION_TOKEN", capability)
    monkeypatch.setenv("VISIONDATA_DESKTOP_STARTUP_SECRET", "synthetic-proof-" * 4)
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    product = ProductService(tmp_path / "product", recover_interrupted=False)
    stopped = Event()
    try:
        app = create_app(product)
        app.state.desktop_shutdown_callback = stopped.set
        headers = {"X-VisionData-Desktop-Token": capability}
        with TestClient(app, client=("127.0.0.1", 51234)) as client:
            setup = client.post(
                "/v1/identity/setup",
                headers=headers,
                json={
                    "login_name": "operator",
                    "display_name": "Operator",
                    "password": "synthetic long password 20260913",
                },
            )
            assert setup.status_code == 201
            bearer = {"Authorization": "Bearer " + setup.json()["access_token"]}
            assert client.post("/v1/identity/logout", headers=bearer).status_code == 204
            assert client.get("/v1/workspaces", headers=headers).status_code == 401
            forged = client.post(
                "/v1/desktop/shutdown",
                headers={**headers, "X-Forwarded-For": "127.0.0.1"},
            )
            assert forged.status_code == 403 and not stopped.is_set()
            with TestClient(app, client=("192.0.2.30", 51235)) as remote:
                assert (
                    remote.post("/v1/desktop/shutdown", headers=headers).status_code
                    == 403
                )
            assert not stopped.is_set()
            response = client.post("/v1/desktop/shutdown", headers=headers)
            assert response.status_code == 202
            assert response.json() == {"status": "SHUTTING_DOWN"}
            assert stopped.is_set()
    finally:
        product.close(wait=True)

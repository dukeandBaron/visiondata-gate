from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from visiondata_gate.api import create_app
from visiondata_gate.product_service import ProductService


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_API = ROOT / "web" / "src" / "data" / "privateIndustrialValidationApi.ts"


def _assert_frontend_names_every_response_field(
    source: str,
    value: object,
) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            assert f'"{key}"' in source, f"frontend contract omits API field: {key}"
            _assert_frontend_names_every_response_field(source, nested)
    elif isinstance(value, list) and value:
        _assert_frontend_names_every_response_field(source, value[0])


def test_scoped_industrial_validation_response_matches_frontend_contract(
    tmp_path: Path,
) -> None:
    service = ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        client = TestClient(
            create_app(
                service,
                enable_account_bootstrap=True,
                ensure_demo_tenant=False,
            )
        )
        user = client.post("/v1/users", json={"display_name": "Web contract owner"})
        assert user.status_code == 201
        user_id = user.json()["user_id"]
        headers = {"X-Actor-User-Id": user_id}
        workspace = client.post(
            "/v1/workspaces",
            headers=headers,
            json={"name": "Web contract workspace", "owner_user_id": user_id},
        )
        assert workspace.status_code == 201
        workspace_id = workspace.json()["workspace_id"]
        project = client.post(
            "/v1/projects",
            headers=headers,
            json={"workspace_id": workspace_id, "name": "Web contract project"},
        )
        assert project.status_code == 201
        project_id = project.json()["project_id"]

        response = client.get(
            f"/v1/workspaces/{workspace_id}/evaluation-evidence/industrial-validation",
            headers=headers,
            params={"project_id": project_id},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "HOLD"
        assert payload["availability"] == (
            "CURRENT_PUBLIC_PROXY_WITH_HISTORICAL_OFFLINE_EVIDENCE"
        )
        assert payload["scope"] == {
            "scope_kind": "PROJECT_REFERENCE",
            "workspace_id": workspace_id,
            "project_id": project_id,
            "association_status": "REFERENCE_ONLY_NOT_PROJECT_DERIVED",
            "read_only": True,
        }
        assert payload["production_release_allowed"] is False
        assert payload["machine_write_permitted"] is False
        assert payload["read_only"] is True
        assert response.headers["x-content-sha256"] == payload["projection_sha256"]
        assert response.headers["etag"] == f'"{payload["projection_sha256"]}"'
        assert response.headers["cache-control"] == "private, no-store"

        source = FRONTEND_API.read_text(encoding="utf-8")
        _assert_frontend_names_every_response_field(source, payload)
        assert "exactKeys(" in source
        assert 'domainJcsSha256("industrial-validation-projection", stable)' in source
        assert 'normalizedEtag(response.headers.get("ETag"))' in source
    finally:
        service.close(wait=True)

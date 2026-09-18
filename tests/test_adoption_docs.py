"""Public adoption docs must reference real entry points, not proposed commands."""

from pathlib import Path
import json
import re
import tomllib

import pytest
import yaml

from tools.export_public_repository import PUBLIC_EXACT_FILES


ROOT = Path(__file__).resolve().parents[1]
NEW_DOCS = (
    "docs/CROSS_PLATFORM_QUICKSTART.md",
    "docs/INTERFACE_SUPPORT.md",
    "docs/RELEASE_PREPARATION.md",
    "docs/EXTERNAL_REVIEW_RESPONSE.md",
    "docs/ENGINEERING_QUALITY_IMPLEMENTATION.md",
    "docs/PUBLIC_API.md",
    "docs/BENCHMARK_REPRODUCIBILITY.md",
    "docs/AUDIT_TRUST_BOUNDARY.md",
    "docs/API_QUICKSTART.md",
    "docs/ADOPTION_GUIDE.md",
    "docs/THIRD_PARTY_REPRODUCTION.md",
)


def test_portable_quickstart_points_to_a_real_launcher():
    quickstart = (ROOT / NEW_DOCS[0]).read_text(encoding="utf-8")
    assert "tools/run_cross_platform_workbench.py --check" in quickstart
    assert (ROOT / "tools/run_cross_platform_workbench.py").is_file()
    for block in re.findall(r"```[^\n]*\n(.*?)```", quickstart, flags=re.S):
        assert "visiondata-gate serve" not in block
        assert "INSECURE_TEST_ACTOR_HEADER_BYPASS" not in block
        assert "uvx visiondata-gate" not in block
    assert "--locked" in quickstart


def test_new_docs_have_resolvable_local_links_and_are_export_allowed():
    for relative in NEW_DOCS:
        path = ROOT / relative
        assert relative in PUBLIC_EXACT_FILES
        content = path.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", content):
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            resolved = (path.parent / target.split("#", 1)[0]).resolve()
            assert resolved.is_relative_to(ROOT), relative
            assert resolved.exists(), f"Missing local link in {relative}: {target}"


def test_citation_and_changelog_do_not_invent_a_distribution_release():
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert citation["cff-version"] == "1.2.0"
    assert citation["type"] == "software"
    assert citation["repository-code"] == (
        "https://github.com/dukeandBaron/visiondata-gate"
    )
    assert citation["authors"] == [{"name": "VisionData Gate contributors"}]
    assert "doi" not in citation
    assert "CITATION.cff" in PUBLIC_EXACT_FILES
    assert "CHANGELOG.md" in PUBLIC_EXACT_FILES
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert (
        metadata["project"]["scripts"]["visiondata-gate"] == "visiondata_gate.cli:main"
    )
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in changelog
    assert "not a claim of a matching PyPI package version" in changelog
    assert "prerelease" in changelog


def test_canonical_interface_does_not_promise_installer_or_model_authority():
    content = (ROOT / "docs/INTERFACE_SUPPORT.md").read_text(encoding="utf-8")
    assert "primary interactive product" in content
    for boundary in (
        "Legacy/compatibility",
        "Optional desktop wrapper",
        "Public synthetic replay",
    ):
        assert boundary in content
    assert "A Windows smoke pass does not certify them" in content
    assert "older Windows installer does not automatically contain" in content


def _documented_api_client():
    content = (ROOT / "docs/API_QUICKSTART.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", content, flags=re.S)
    matching = [block for block in blocks if "doc-contract: authenticated-synthetic-run" in block]
    assert len(matching) == 1, "API onboarding must include its executable HTTP client"
    namespace = {"__name__": "documented_api_test"}
    exec(compile(matching[0], "API_QUICKSTART.md", "exec"), namespace)
    return namespace["run_synthetic_example"]


def test_api_quickstart_uses_real_identity_and_non_private_first_input():
    text = (ROOT / "docs/API_QUICKSTART.md").read_text(encoding="utf-8")
    assert "uv sync --locked --extra api --extra qa" in text
    for endpoint in ("/v1/identity/status", "/v1/identity/setup", "/v1/identity/register", "/v1/identity/login"):
        assert endpoint in text
    assert "/v1/identity/bootstrap" not in text
    assert "X-VisionData-Session-Token" in text and "Bearer" in text
    assert "source_kind" in text and "synthetic_demo" in text
    assert "VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS" in text
    assert '"X-Actor-User-Id" = "usr_local_demo"' not in text
    assert "默认 API 不公开用户创建、用户枚举或工作区创建接口" not in text
    assert "不是注册、登录或租户管理服务" not in text
    _documented_api_client()


def test_adoption_paths_separate_dependencies_artifacts_pass_and_hold():
    path = ROOT / "docs/ADOPTION_GUIDE.md"
    assert path.is_file(), "three bounded adoption routes must be documented"
    content = path.read_text(encoding="utf-8")
    parent_setup = "Path('output/open-reuse').mkdir(parents=True, exist_ok=True)"
    assert parent_setup in content
    assert content.index(parent_setup) < content.index("tools/run_open_reuse_smoke.py")
    for marker in (
        "5 分钟", "无模型", "本地完整工作台", "BYOM Normality", "依赖", "产物", "PASS", "HOLD",
        "examples/reuse/metadata_skill.py", "tools/run_cross_platform_workbench.py", "NORMALITY_TTT.md",
        "不自动下载", "不等于", "--locked", "独立第三方",
    ):
        assert marker in content


def test_external_reproduction_template_starts_unverified_and_tracks_exact_evidence():
    path = ROOT / "docs/THIRD_PARTY_REPRODUCTION.md"
    assert path.is_file(), "external validation needs an honest reusable record template"
    content = path.read_text(encoding="utf-8")
    templates = re.findall(r"```json\n(.*?)```", content, flags=re.S)
    assert len(templates) == 1
    template = json.loads(templates[0])
    assert template["status"] == "NOT_RUN"
    for key in ("commit", "tree", "os", "versions", "exact_commands", "artifacts", "not_run", "independence", "privacy"):
        assert key in template
    assert template["commit"] is None and template["tree"] is None
    assert template["exact_commands"] == [] and template["artifacts"] == []
    assert template["independence"]["is_independent_third_party"] is None
    assert template["privacy"]["reviewed_for_publication"] is False
    assert "maintainer CI" in content and "不等于第三方" in content
    assert "SHA-256" in content and "未运行" in content


def test_documented_client_emits_reconciliation_key_before_unknown_task_write(capsys):
    import httpx

    run = _documented_api_client()

    class LostTaskResponse:
        request_key = None

        def request(self, method, route, **kwargs):
            if route == "/v1/tasks":
                self.request_key = kwargs["headers"]["Idempotency-Key"]
                raise RuntimeError("synthetic unknown POST result")
            payload = {
                "/v1/identity/status": {"setup_required": False},
                "/v1/identity/login": {"access_token": "synthetic-doc-token-only"},
                "/v1/identity/me": {"user_id": "synthetic_user"},
                "/v1/workspaces": {"workspace_id": "synthetic_workspace"},
                "/v1/projects": {"project_id": "synthetic_project"},
            }[route]
            return httpx.Response(200, json=payload, request=httpx.Request(method, "http://test" + route))

        def post(self, route, **kwargs):
            return httpx.Response(204, request=httpx.Request("POST", "http://test" + route))

    client = LostTaskResponse()
    with pytest.raises(RuntimeError, match="synthetic unknown POST result"):
        run(client, "synthetic_login", "synthetic password only", "Synthetic reviewer", lambda *_: True)
    output = capsys.readouterr().out
    assert client.request_key and client.request_key in output
    assert "synthetic-doc-token-only" not in output
    assert "synthetic password only" not in output


@pytest.mark.tier_integration
def test_documented_http_client_bootstraps_bearer_and_runs_synthetic_task(tmp_path, monkeypatch):
    run = _documented_api_client()
    capability = "synthetic-adoption-doc-startup-capability-42"
    password = "synthetic documentation password 73"
    monkeypatch.setenv("VISIONDATA_SESSION_TOKEN", capability)
    monkeypatch.setenv("VISIONDATA_SESSION_ACTOR_USER_ID", "usr_local_demo")
    monkeypatch.setenv("VISIONDATA_PRODUCT_ROOT", str(tmp_path / "default-product"))
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "false")
    from fastapi.testclient import TestClient
    from visiondata_gate.api import create_app
    from visiondata_gate.product_service import ProductService

    service = ProductService(tmp_path / "product", recover_interrupted=False)
    try:
        with TestClient(create_app(service), client=("127.0.0.1", 49681)) as client:
            result = run(client, "docs-reviewer", password, "Documentation reviewer", lambda plan, preflight: True, startup_capability=capability)
            assert result["execution_status"] == "COMPLETED"
            assert result["source_kind"] == "synthetic_demo"
            assert result["production_release_allowed"] is False
            assert re.fullmatch(r"[0-9a-f]{64}", result["trace_sha256"])
            assert re.fullmatch(r"[0-9a-f]{64}", result["evidence_sha256"])
            public = json.dumps(result)
            assert password not in public and capability not in public and "access_token" not in public
            assert client.get("/v1/workspaces", headers={"X-Actor-User-Id": "usr_local_demo"}).status_code == 401
            pending = client.post("/v1/identity/register", json={"login_name": "docs-pending", "display_name": "Pending reader", "password": password})
            assert pending.status_code == 201 and pending.json()["status"] == "PENDING"
            assert client.post("/v1/identity/login", json={"login_name": "docs-pending", "password": password}).status_code in (401, 403)
    finally:
        service.close(wait=True)

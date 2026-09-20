"""TTT API contracts use real registry/CAS bytes and a labelled worker double."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
import runpy

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from visiondata_gate import local_model_registry as registry
from visiondata_gate import normality_inference, normality_ttt, vision_model_api
from visiondata_gate.product_service import ProductService
from visiondata_gate.task_store import NotFoundError


def _module():
    assert importlib.util.find_spec("visiondata_gate.normality_adaptation_service"), (
        "TTT service missing"
    )
    return importlib.import_module("visiondata_gate.normality_adaptation_service")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_ttt_service_contract_is_available():
    assert importlib.util.find_spec("visiondata_gate.normality_adaptation_service"), (
        "TTT service missing"
    )


def test_ttt_request_schema_matches_runtime():
    path = (
        Path(__file__).resolve().parents[1] / "schemas/normality_ttt_requests.v1.json"
    )
    assert path.is_file()
    schema = json.loads(path.read_text("utf-8"))
    assert (
        schema["requests"]["RunNormalityTtt"]
        == _module().RunNormalityTtt.model_json_schema()
    )


@pytest.fixture
def ttt_scope(tmp_path, monkeypatch):
    module = _module()
    support = runpy.run_path(
        str(Path(__file__).with_name("test_normality_model_registry.py"))
    )
    product = ProductService(tmp_path / "product", recover_interrupted=False)
    actor, workspace, project = product.ensure_default_tenant()
    actor, project = actor.user_id, project.project_id
    service = module.NormalityAdaptationService(product)
    evidence = support["_real_evidence"](
        tmp_path / "evidence",
        pack_schema="visiondata-gate.yolo26-normality-model-pack.v2",
        stable=True,
    )
    support["_stub_stability_rebuild"](registry, evidence, monkeypatch)
    model = service.register_normality_model_pack(
        actor,
        project,
        support["_real_pack_request"](
            registry, evidence, request_key="ttt-pack-register-0001"
        ),
    )
    runtime_file = tmp_path / "runtime.exe"
    runtime_file.write_bytes(b"TTT HTTP contract runtime fixture; never execute")
    runtime = {
        "resource_id": "vision_runtime_" + "e" * 24,
        "runtime_id": "vision_runtime_" + "e" * 24,
        "project_id": project,
        "executable_sha256": _sha(runtime_file),
        "runtime_sha256": "9" * 64,
        "status": "PROBED",
        "probe": {"status": "ready", "import_status": "PASSED"},
    }
    with product.store._connection(immediate=True) as conn:
        service._put(conn, runtime, "runtime", {"executable_path": str(runtime_file)})
        model = service._put(
            conn,
            model
            | {
                "status": "APPROVE_SANDBOX",
                "usage_scope": "LOCAL_SANDBOX_ONLY",
                "sandbox_runtime_id": runtime["runtime_id"],
                "sandbox_runtime_sha256": runtime["runtime_sha256"],
                "sandbox_validation": {
                    "inference_backend_sha256": _sha(normality_inference.__file__)
                },
            },
            "model",
            replace=True,
        )
    assets = []
    for index in range(5):
        path = tmp_path / f"image_{index}.png"
        Image.new("RGB", (20, 16), (index * 40, 20, 30)).save(path)
        assets.append(
            service.register_inference_asset(
                actor,
                project,
                registry.RegisterVisionInferenceAsset(
                    request_key=f"ttt-asset-register-{index:04d}",
                    reviewer_identity="Test image owner",
                    note="Freeze explicit contract fixture bytes for TTT tests",
                    display_name=f"Frame {index}",
                    image_path=str(path),
                    expected_image_sha256=_sha(path),
                    operator_attests_read_authorized=True,
                ),
            )
        )

    def ref(index):
        asset = assets[index]
        return {
            "asset_id": asset["asset_id"],
            "expected_asset_receipt_sha256": asset["receipt_sha256"],
            "expected_image_sha256": asset["image_sha256"],
        }

    payload = {
        "request_key": "ttt-http-run-0001",
        "reviewer_identity": "Named TTT reviewer",
        "note": "Authorizes only this isolated CPU episode and human supplied guard labels",
        "expected_model_receipt_sha256": model["receipt_sha256"],
        **{
            f"expected_{key}": model[key]
            for key in (
                "model_pack_sha256",
                "backbone_weights_sha256",
                "source_binding_sha256",
                "source_index_sha256",
            )
        },
        "expected_runtime_sha256": runtime["runtime_sha256"],
        **ref(0),
        "max_seconds": 90,
        "operator_attests_execution_authorized": True,
        "operator_attests_trusted_runtime": True,
        "operator_attests_trusted_weights": True,
        "operator_attests_weights_only_load_authorized": True,
        "expected_ttt_implementation_sha256": _sha(normality_ttt.__file__),
        "adaptation_assets": [ref(1)],
        "replay_assets": [ref(2)],
        "guard_assets": [
            ref(3) | {"reference_label": "normal"},
            ref(4) | {"reference_label": "anomaly"},
        ],
        "budget": {"steps": 2, "learning_rate": 0.001, "max_seconds": 30, "seed": 7},
        "operator_attests_ttt_authorized": True,
        "operator_attests_replay_normal": True,
        "operator_attests_guard_labels_reviewed": True,
    }
    state = {"calls": 0, "error": None, "mutate": None, "during": None}

    def worker(**kwargs):
        state["calls"] += 1
        if state["during"]:
            state["during"]()
        if state["error"]:
            raise state["error"]
        heatmap = kwargs["output_root"] / "artifacts" / "heatmap.png"
        heatmap.parent.mkdir(parents=True)
        Image.new("L", (64, 64), 80).save(heatmap)
        groups = {
            name: {
                "count": len(kwargs[f"{name}_images"]),
                "sha256": [row["sha256"] for row in kwargs[f"{name}_images"]],
            }
            for name in ("adaptation", "replay", "guard")
        }
        matrix = {"tp": 1, "tn": 1, "fp": 0, "fn": 0}
        report = {
            "schema_version": "visiondata-gate.normality-ttt.v1",
            "strategy": "EPISODIC_MASKED_STUDENT",
            "status": "ACCEPTED_EPISODIC",
            "rollback_reason": None,
            "steps_completed": 2,
            "objective_before": 1.0,
            "objective_after": 0.85,
            "loss_curve": [
                {
                    "step": step,
                    "loss": loss,
                    "reconstruction_loss": loss,
                    "replay_loss": 0.0,
                    "anchor_loss": 0.0,
                    "gradient_norm": 0.1,
                }
                for step, loss in [(1, 1.0), (2, 0.9)]
            ],
            "parameter_sha256_before": "a" * 64,
            "parameter_sha256_after": "b" * 64,
            "attempted_parameter_sha256": "b" * 64,
            "effective_parameter_sha256": "b" * 64,
            "backbone_sha256_before": "c" * 64,
            "backbone_sha256_after": "c" * 64,
            "guard_before": matrix.copy(),
            "guard_after": matrix.copy(),
            "effective_guard": matrix.copy(),
            "reset_after_episode": True,
            "persistent_learning": False,
            "parent_pack_unchanged": True,
            "thresholds_unchanged": True,
            "budget": kwargs["budget"],
            "loss_weights": {
                "masked_reconstruction": 1.0,
                "teacher_replay": 1.0,
                "parameter_anchor": 0.1,
            },
            "mask_fraction": 0.25,
            "industrial_benefit_validated": False,
            "elapsed_seconds": 0.1,
            "input_groups": groups,
            "implementation_sha256": _sha(normality_ttt.__file__),
            "guard_policy": {
                "min_true_positive": 1,
                "min_true_negative": 1,
                "max_fp_increase": 0,
                "max_fn_increase": 0,
            },
        }
        result = {
            "schema_version": "visiondata-gate.normality-inference-result.v1",
            "status": "COMPLETED_LOCAL_SANDBOX_INFERENCE",
            **{
                key: kwargs[f"expected_{key}"]
                for key in (
                    "model_pack_sha256",
                    "backbone_weights_sha256",
                    "source_binding_sha256",
                    "source_index_sha256",
                    "runtime_sha256",
                    "image_sha256",
                )
            },
            "model_pack_schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
            "inference_backend_sha256": _sha(normality_inference.__file__),
            "ttt_backend_sha256": _sha(normality_ttt.__file__),
            "image_score": 0.7,
            "image_threshold": 0.5,
            "pixel_threshold": 0.8,
            "positive_pixel_fraction": 0.1,
            "predicted_anomaly": True,
            "heatmap": {
                "sha256": _sha(heatmap),
                "bytes": heatmap.stat().st_size,
                "width": 64,
                "height": 64,
                "format": "png",
            },
            "device": "cpu",
            "production_release_allowed": False,
            "machine_write_permitted": False,
            "ttt": report,
        }
        if state["mutate"]:
            state["mutate"](result)
        return result

    monkeypatch.setattr(normality_ttt, "run_normality_ttt", worker)
    app = FastAPI()

    def principal(x_test_session: str | None = Header(default=None)):
        if x_test_session == "owner":
            return actor
        if x_test_session == "outsider":
            return "outsider"
        raise HTTPException(401)

    @app.exception_handler(NotFoundError)
    def missing(_request, _error):
        return JSONResponse(status_code=404, content={"error": "not_found"})

    vision_model_api.install_vision_model_routes(app, principal, lambda: product)
    yield (
        module,
        product,
        service,
        actor,
        project,
        workspace.workspace_id,
        model,
        assets,
        payload,
        state,
        app,
    )
    product.close(wait=True)


def _run(scope, payload=None):
    return scope[2].run_ttt(
        scope[3],
        scope[4],
        scope[6]["model_id"],
        scope[0].RunNormalityTtt.model_validate(payload or scope[8]),
    )


def test_ttt_capability_and_real_png_endpoint(ttt_scope):
    (
        module,
        _product,
        service,
        actor,
        project,
        _workspace,
        model,
        _assets,
        payload,
        state,
        app,
    ) = ttt_scope
    with TestClient(app, client=("127.0.0.1", 9000)) as client:
        base = f"/v1/projects/{project}"
        cap = client.get(
            base + "/vision-ttt-capabilities", headers={"X-Test-Session": "owner"}
        )
        assert cap.status_code == 200
        assert (
            cap.json()["implementation_sha256"]
            == payload["expected_ttt_implementation_sha256"]
        )
        assert cap.json()["max_steps"] == 8
        response = client.post(
            base + f"/vision-models/{model['model_id']}/ttt-inferences",
            headers={"X-Test-Session": "owner"},
            json=payload,
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert registry._seal(result) == result
        assert result["authorization_sha256"] == registry._sha(
            module.RunNormalityTtt.model_validate(payload).model_dump(mode="json")
        )
        assert result["ttt"]["status"] == "ACCEPTED_EPISODIC"
        assert result["production_release_allowed"] is False
        assert result["machine_write_permitted"] is False
        assert (
            client.get(
                base + f"/vision-inferences/{result['inference_id']}/heatmap",
                headers={"X-Test-Session": "owner"},
            ).status_code
            == 200
        )
    assert _run(ttt_scope) == result
    assert state["calls"] == 1
    assert (
        service.get_operation(
            actor,
            project,
            "run_normality_ttt:" + model["model_id"],
            payload["request_key"],
        )["resource"]
        == result
    )


@pytest.mark.parametrize(
    "error,code",
    [
        (ValueError("NORMALITY_WORKER_TIMEOUT"), "TTT_WORKER_TIMEOUT"),
        (ValueError("NORMALITY_WORKER_FAILED"), "TTT_WORKER_FAILED"),
        (RuntimeError("E:/private-secret/runtime"), "TTT_EXECUTION_FAILED"),
    ],
)
def test_failed_worker_has_durable_terminal_receipt_and_never_auto_replays(
    ttt_scope, error, code
):
    ttt_scope[9]["error"] = error
    result = _run(ttt_scope)
    assert result["schema_version"] == "visiondata-gate.vision_ttt_failure.v1"
    assert result["status"] == "FAILED_CLOSED"
    assert result["failure_code"] == code
    assert result["measurements_available"] is False
    assert result["retry_policy"] == "NEW_EXPLICIT_AUTHORIZATION_REQUIRED"
    assert "image_score" not in result and "ttt" not in result
    assert "private-secret" not in json.dumps(result)
    assert _run(ttt_scope) == result
    assert ttt_scope[9]["calls"] == 1
    assert ttt_scope[2].list_failures(ttt_scope[3], ttt_scope[4])["items"] == [result]


@pytest.mark.parametrize(
    "field,value",
    [
        ("operator_attests_ttt_authorized", False),
        ("operator_attests_replay_normal", 1),
        ("operator_attests_guard_labels_reviewed", False),
        ("budget", {"steps": 9, "learning_rate": 0.001, "max_seconds": 20, "seed": 0}),
        ("guard_assets", []),
    ],
)
def test_invalid_authority_and_budget_rejected_without_worker(ttt_scope, field, value):
    with pytest.raises(ValueError):
        _run(ttt_scope, ttt_scope[8] | {field: value})
    assert ttt_scope[9]["calls"] == 0


@pytest.mark.parametrize(
    "mutation", ["implementation", "split_overlap", "stale_asset", "same_guard_class"]
)
def test_invalid_input_binding_never_starts_worker(ttt_scope, mutation):
    payload = copy.deepcopy(ttt_scope[8])
    if mutation == "implementation":
        payload["expected_ttt_implementation_sha256"] = "0" * 64
    elif mutation == "split_overlap":
        payload["replay_assets"] = payload["adaptation_assets"]
    elif mutation == "stale_asset":
        payload["replay_assets"][0]["expected_image_sha256"] = "0" * 64
    else:
        payload["guard_assets"][1]["reference_label"] = "normal"
    with pytest.raises((ValueError, registry.VisionModelError)):
        _run(ttt_scope, payload)
    assert ttt_scope[9]["calls"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("guard_after", {"tp": 0, "tn": 1, "fp": 0, "fn": 1}),
        ("effective_parameter_sha256", "a" * 64),
        ("steps_completed", 0),
        ("backbone_sha256_after", "d" * 64),
        ("budget", {"steps": 8}),
        ("input_groups", {}),
        ("guard_before", None),
        ("attempt_measurements_available", False),
        (
            "guard_policy",
            {
                "min_true_positive": True,
                "min_true_negative": 1,
                "max_fp_increase": 0,
                "max_fn_increase": 0,
            },
        ),
    ],
)
def test_inconsistent_worker_measurements_fail_closed(ttt_scope, field, value):
    ttt_scope[9]["mutate"] = lambda result: result["ttt"].update({field: value})
    result = _run(ttt_scope)
    assert result["status"] == "FAILED_CLOSED"
    assert result["failure_code"] == "TTT_RESULT_CONTRACT_INVALID"
    assert ttt_scope[2].list_inferences(ttt_scope[3], ttt_scope[4])["items"] == []


def test_real_measured_rollback_preserves_baseline_effective_identity(ttt_scope):
    def rollback(result):
        report = result["ttt"]
        report.update(
            status="ROLLED_BACK",
            rollback_reason="TTT_GUARD_REGRESSION",
            effective_parameter_sha256=report["parameter_sha256_before"],
            effective_guard=report["guard_before"],
            guard_after={"tp": 0, "tn": 1, "fp": 0, "fn": 1},
        )

    ttt_scope[9]["mutate"] = rollback
    result = _run(ttt_scope)
    assert result["status"] == "COMPLETED_LOCAL_SANDBOX_INFERENCE"
    assert result["ttt"]["status"] == "ROLLED_BACK"


def test_false_baseline_unqualified_reason_is_not_a_measured_rollback(ttt_scope):
    def false_reason(result):
        report = result["ttt"]
        report.update(
            status="ROLLED_BACK",
            rollback_reason="TTT_GUARD_BASELINE_UNQUALIFIED",
            effective_parameter_sha256=report["parameter_sha256_before"],
            effective_guard=report["guard_before"],
        )

    ttt_scope[9]["mutate"] = false_reason
    result = _run(ttt_scope)
    assert result["status"] == "FAILED_CLOSED"


def test_model_revoked_during_episode_cannot_publish_inference(ttt_scope):
    def revoke():
        with ttt_scope[1].store._connection(immediate=True) as conn:
            ttt_scope[2]._put(
                conn, ttt_scope[6] | {"status": "REJECT"}, "model", replace=True
            )

    ttt_scope[9]["during"] = revoke
    result = _run(ttt_scope)
    assert result["status"] == "FAILED_CLOSED"
    assert result["failure_code"] == "TTT_AUTHORITY_OR_INPUT_CHANGED"


@pytest.mark.parametrize(
    "target", ["replay_asset", "runtime", "parent_pack", "implementation"]
)
def test_post_worker_byte_or_implementation_drift_cannot_publish_inference(
    ttt_scope, monkeypatch, target
):
    (
        module,
        product,
        service,
        _actor,
        project,
        _workspace,
        model,
        assets,
        _payload,
        state,
        _app,
    ) = ttt_scope

    def mutate():
        if target == "implementation":
            monkeypatch.setattr(module, "ttt_implementation_sha256", lambda: "0" * 64)
            return
        with product.store._connection() as conn:
            if target == "replay_asset":
                _asset, private = service._read(
                    conn, project, assets[2]["asset_id"], "inference_asset"
                )
                path = Path(private["cas_path"])
            elif target == "runtime":
                _runtime, private = service._read(
                    conn, project, model["sandbox_runtime_id"], "runtime"
                )
                path = Path(private["executable_path"])
            else:
                _model, private = service._read(
                    conn, project, model["model_id"], "model"
                )
                path = registry._verify_normality_pack_cas(
                    service.root, model, private
                )["model_pack"]
        path.write_bytes(b"changed while the authorized test worker was active")

    state["during"] = mutate
    result = _run(ttt_scope)
    assert result["status"] == "FAILED_CLOSED"
    assert result["failure_code"] == "TTT_AUTHORITY_OR_INPUT_CHANGED"
    assert service.list_inferences(ttt_scope[3], project)["items"] == []


def test_membership_revocation_during_worker_keeps_only_failure_audit(ttt_scope):
    from visiondata_gate.product_models import CreateUserRequest

    (
        module,
        product,
        service,
        actor,
        project,
        workspace,
        _model,
        _assets,
        payload,
        state,
        _app,
    ) = ttt_scope
    other = product.create_user(
        CreateUserRequest(display_name="Remaining authorized reviewer")
    )
    with product.store._connection(immediate=True) as conn:
        conn.execute(
            "INSERT INTO workspace_members VALUES (?, ?, 'member', ?)",
            (workspace, other.user_id, registry._now()),
        )

    def revoke():
        with product.store._connection(immediate=True) as conn:
            conn.execute(
                "DELETE FROM workspace_members WHERE workspace_id=? AND user_id=?",
                (workspace, actor),
            )

    state["during"] = revoke
    with pytest.raises(NotFoundError):
        _run(ttt_scope)
    failures = service.list_failures(other.user_id, project)["items"]
    assert (
        len(failures) == 1
        and failures[0]["failure_code"] == "TTT_AUTHORITY_OR_INPUT_CHANGED"
    )
    assert service.list_inferences(other.user_id, project)["items"] == []
    with pytest.raises(NotFoundError):
        service.list_failures(actor, project)


def test_unauthorized_initial_request_has_zero_records_and_no_worker(ttt_scope):
    with ttt_scope[1].store._connection() as conn:
        before = conn.execute("SELECT COUNT(*) FROM vision_records").fetchone()[0]
    with pytest.raises(NotFoundError):
        ttt_scope[2].run_ttt(
            "outsider",
            ttt_scope[4],
            ttt_scope[6]["model_id"],
            ttt_scope[0].RunNormalityTtt.model_validate(ttt_scope[8]),
        )
    with ttt_scope[1].store._connection() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM vision_records").fetchone()[0] == before
        )
    assert ttt_scope[9]["calls"] == 0


def test_capability_exposes_guard_floor_not_industrial_validation(ttt_scope):
    cap = ttt_scope[2].ttt_capabilities(ttt_scope[3], ttt_scope[4])
    assert cap["guard_policy"] == {
        "min_true_positive": 1,
        "min_true_negative": 1,
        "max_fp_increase": 0,
        "max_fn_increase": 0,
    }
    assert cap["industrial_benefit_validated"] is False


def test_unqualified_baseline_is_measured_zero_step_rollback(ttt_scope):
    def rollback(result):
        report = result["ttt"]
        matrix = {"tp": 0, "tn": 1, "fp": 0, "fn": 1}
        report.update(
            status="ROLLED_BACK",
            rollback_reason="TTT_GUARD_BASELINE_UNQUALIFIED",
            steps_completed=0,
            objective_before=None,
            objective_after=None,
            loss_curve=[],
            guard_before=matrix,
            guard_after=None,
            effective_guard=matrix,
            parameter_sha256_after=report["parameter_sha256_before"],
            attempted_parameter_sha256=report["parameter_sha256_before"],
            effective_parameter_sha256=report["parameter_sha256_before"],
        )

    ttt_scope[9]["mutate"] = rollback
    result = _run(ttt_scope)
    assert result["status"] == "COMPLETED_LOCAL_SANDBOX_INFERENCE"
    assert result["ttt"]["steps_completed"] == 0


def test_reencoded_identical_pixels_cannot_cross_guard_split(ttt_scope, tmp_path):
    (
        module,
        _product,
        service,
        actor,
        project,
        _ws,
        _model,
        _assets,
        payload,
        state,
        _app,
    ) = ttt_scope
    path = tmp_path / "same-query-pixels-different-encoding.png"
    Image.new("RGB", (20, 16), (0, 20, 30)).save(path, compress_level=0)
    asset = service.register_inference_asset(
        actor,
        project,
        registry.RegisterVisionInferenceAsset(
            request_key="ttt-reencoded-asset-0001",
            reviewer_identity="Test reviewer",
            note="Separate encoding of query pixels for negative split test",
            display_name="Duplicate pixels",
            image_path=str(path),
            expected_image_sha256=_sha(path),
            operator_attests_read_authorized=True,
        ),
    )
    payload = copy.deepcopy(payload)
    assert asset["image_sha256"] != payload["expected_image_sha256"]
    payload["guard_assets"][0] = {
        "asset_id": asset["asset_id"],
        "expected_asset_receipt_sha256": asset["receipt_sha256"],
        "expected_image_sha256": asset["image_sha256"],
        "reference_label": "normal",
    }
    with pytest.raises(registry.VisionModelError, match="TTT_DECODED_PIXEL_OVERLAP"):
        _run(ttt_scope, payload)
    assert state["calls"] == 0


def test_cross_language_service_receipts(ttt_scope):
    """Emit actual sealed service DTOs, explicitly not actual model-run evidence."""
    accepted = _run(ttt_scope)

    def rollback(result):
        report = result["ttt"]
        report.update(
            status="ROLLED_BACK",
            rollback_reason="TTT_GUARD_REGRESSION",
            effective_parameter_sha256=report["parameter_sha256_before"],
            effective_guard=report["guard_before"],
            guard_after={"tp": 0, "tn": 1, "fp": 0, "fn": 1},
        )

    ttt_scope[9]["mutate"] = rollback
    rolled_back = _run(
        ttt_scope, ttt_scope[8] | {"request_key": "ttt-cross-language-rollback-0001"}
    )
    ttt_scope[9]["error"] = ValueError("NORMALITY_WORKER_TIMEOUT")
    failed = _run(
        ttt_scope, ttt_scope[8] | {"request_key": "ttt-cross-language-failure-0001"}
    )
    assert accepted["ttt"]["status"] == "ACCEPTED_EPISODIC"
    assert rolled_back["ttt"]["status"] == "ROLLED_BACK"
    assert failed["failure_code"] == "TTT_WORKER_TIMEOUT"
    value = {
        "evidence_origin": "REAL_SERVICE_RECEIPTS_WITH_SYNTHETIC_WORKER_NOT_MODEL_EXECUTION",
        "capabilities": ttt_scope[2].ttt_capabilities(ttt_scope[3], ttt_scope[4]),
        "accepted": accepted,
        "rolled_back": rolled_back,
        "failed": failed,
    }
    print("TTT_CONTRACT_JSON:" + json.dumps(value, sort_keys=True))


def test_accepted_episode_requires_actual_final_objective_improvement(ttt_scope):
    def unchanged(result):
        result["ttt"]["objective_after"] = result["ttt"]["objective_before"]

    ttt_scope[9]["mutate"] = unchanged
    assert _run(ttt_scope)["status"] == "FAILED_CLOSED"


def test_final_objective_can_improve_even_when_last_preupdate_loss_did_not(ttt_scope):
    def last_preupdate(result):
        row = result["ttt"]["loss_curve"][-1]
        row["loss"] = row["reconstruction_loss"] = 1.0

    ttt_scope[9]["mutate"] = last_preupdate
    assert _run(ttt_scope)["status"] == "COMPLETED_LOCAL_SANDBOX_INFERENCE"


def test_interrupted_episode_does_not_fabricate_unmeasured_final_objective(ttt_scope):
    def incomplete(result):
        report = result["ttt"]
        report.update(
            status="ROLLED_BACK",
            rollback_reason="TTT_TIME_BUDGET_EXCEEDED",
            objective_after=None,
            guard_after=None,
            effective_guard=report["guard_before"],
            effective_parameter_sha256=report["parameter_sha256_before"],
        )

    ttt_scope[9]["mutate"] = incomplete
    result = _run(ttt_scope)
    assert result["status"] == "COMPLETED_LOCAL_SANDBOX_INFERENCE"
    assert result["ttt"]["objective_before"] == 1.0
    assert result["ttt"]["objective_after"] is None

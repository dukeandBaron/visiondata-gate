"""Fail-closed registry contracts for self-contained normality model packs."""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
import pytest
from PIL import Image

from visiondata_gate.product_models import (
    CreateProjectRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
)
from visiondata_gate.product_service import ProductService
from visiondata_gate.audit_envelope import canonical_jcs_bytes
from visiondata_gate.evidence import canonical_json_bytes
from visiondata_gate.public_governance_bench import (
    VisaSourceIndex,
    VisaSourceSample,
    _sealed_model,
    build_public_source_binding,
    visa_csv_header_sha256,
)


@pytest.fixture
def product_scope(tmp_path):
    product = ProductService(tmp_path / "product", recover_interrupted=False)
    user = product.create_user(CreateUserRequest(display_name="Model reviewer"))
    workspace = product.create_workspace(
        CreateWorkspaceRequest(name="Vision", owner_user_id=user.user_id)
    )
    project = product.create_project(
        user.user_id,
        CreateProjectRequest(workspace_id=workspace.workspace_id, name="Models"),
    )
    yield product, user.user_id, project.project_id
    product.close(wait=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _seal(value: dict) -> dict:
    return value | {
        "receipt_sha256": hashlib.sha256(canonical_jcs_bytes(value)).hexdigest()
    }


def _real_evidence(root: Path, *, pack_schema: str, stable: bool) -> dict:
    run = root / "run-seed-1"
    peers = [root / "peer-seed-2", root / "peer-seed-3"]
    for peer in peers:
        peer.mkdir(parents=True, exist_ok=True)
    pack = run / "private" / "worker" / "best_normality_model_pack.pt"
    pack.parent.mkdir(parents=True)
    pack.write_bytes(b"opaque model-pack fixture; registration must not deserialize")
    backbone = root / "yolo26n-cls.pt"
    backbone.write_bytes(b"opaque backbone fixture")

    binding = build_public_source_binding(
        dataset_version="VisA_20220922",
        source_homepage_url="https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/",
        source_archive_sha256="a" * 64,
        license_text_sha256="b" * 64,
        attribution_text_sha256="c" * 64,
        bound_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    sample = _sealed_model(
        VisaSourceSample,
        "sample_sha256",
        {
            "source_sample_id": "visa_" + "1" * 24,
            "row_number": 2,
            "object_class": "capsules",
            "split": "train",
            "product_label": "normal",
            "image_relative_path": "capsules/train.png",
            "image_sha256": "d" * 64,
            "image_size_bytes": 10,
            "mask_relative_path": None,
            "mask_sha256": None,
            "mask_size_bytes": None,
            "product_label_governance_authority": "none",
        },
        domain="visa-source-sample",
    )
    header = ["object", "split", "label", "image", "mask"]
    index = _sealed_model(
        VisaSourceIndex,
        "index_sha256",
        {
            "schema_version": "visiondata-gate.visa-source-index.v1",
            "source_binding_sha256": binding.binding_sha256,
            "split_csv_relative_path": "split_csv/1cls.csv",
            "split_csv_sha256": "e" * 64,
            "csv_header": header,
            "csv_header_sha256": visa_csv_header_sha256(header),
            "column_mapping": {
                "object_column": "object",
                "split_column": "split",
                "product_label_column": "label",
                "image_path_column": "image",
                "mask_path_column": "mask",
            },
            "sample_count": 1,
            "samples": [sample],
            "source_assets_copied": False,
            "product_labels_used_as_governance_truth": False,
        },
        domain="visa-source-index",
    )
    binding_path = root / "source_binding.json"
    index_path = root / "source_index.json"
    _write_json(binding_path, binding.model_dump(mode="json"))
    _write_json(index_path, index.model_dump(mode="json"))

    architecture = "YOLO26N_CLASSIFICATION_MULTISCALE_FEATURE_AUTOENCODER"
    plan = _seal(
        {
            "schema_version": "visiondata-gate.model-experiment-plan.v1",
            "architecture": architecture,
            "feature_layers": [4, 6, 9],
            "split_seed": 20260913,
            "model_seed": 20260913,
            "source_binding_sha256": binding.binding_sha256,
            "source_index_sha256": index.index_sha256,
            "production_release_allowed": False,
            "machine_write_permitted": False,
        }
    )
    normalization = {
        "color_space": "RGB",
        "value_scale": [0.0, 1.0],
        "resize": [256, 256],
        "mean": [0.0, 0.0, 0.0],
        "std": [1.0, 1.0, 1.0],
    }
    result = {
        "schema_version": "visiondata-gate.yolo26-normality-worker-result.v1",
        "status": "COMPLETED",
        "architecture": architecture,
        "feature_layers": [4, 6, 9],
        "split_seed": 20260913,
        "model_seed": 20260913,
        "stability_schema_version": "visiondata-gate.model-stability.v3",
        "backbone_weights_sha256": _sha(backbone),
        "checkpoint": {
            "relative_path": "private/worker/best_normality_model_pack.pt",
            "sha256": _sha(pack),
            "schema_version": pack_schema,
            "feature_layers": [4, 6, 9],
            "roundtrip_validation": {
                "checkpoint_sha256": _sha(pack),
                "tensor_count": 1,
                "all_tensors_cpu_and_finite": True,
                "backbone_state_dict_reload": "PASS",
                "student_state_dict_reload": {"4": "PASS", "6": "PASS", "9": "PASS"},
            },
            "validation_view": {"input_normalization": normalization},
        },
        "production_release_allowed": False,
    }
    agent = _seal(
        {
            "schema_version": "visiondata-gate.model-experiment-agent-receipt.v1",
            "checkpoint_sha256": _sha(pack),
            "source_binding_sha256": binding.binding_sha256,
            "source_index_sha256": index.index_sha256,
            "feature_layers": [4, 6, 9],
            "split_seed": 20260913,
            "model_seed": 20260913,
            "execution_result_sha256": "f" * 64,
            "runtime_event_chain_sha256": "9" * 64,
            "final_disposition": "HOLD",
            "production_release_allowed": False,
            "machine_write_permitted": False,
        }
    )
    selection = {
        "schema_version": "visiondata-gate.visa-model-selection.v1",
        "production_release_allowed": False,
    }
    plan_path = run / "model_experiment_plan.json"
    result_path = run / "model_result.json"
    agent_path = run / "model_experiment_agent_receipt.json"
    selection_path = run / "selection_manifest.json"
    _write_json(plan_path, plan)
    _write_json(result_path, result)
    _write_json(agent_path, agent)
    _write_json(selection_path, selection)
    events_path = run / "agent_runtime_events.json"
    _write_json(events_path, [{"sequence": 1, "status": "COMPLETED"}])
    private_result_path = run / "private" / "worker_result.json"
    _write_json(
        private_result_path,
        {"status": "COMPLETED", "production_release_allowed": False},
    )
    agent["execution_result_sha256"] = _sha(private_result_path)
    agent = _seal({key: value for key, value in agent.items() if key != "receipt_sha256"})
    _write_json(agent_path, agent)
    run_receipt = {
        "schema_version": "visiondata-gate.visa-yolo26-normality-experiment.v1",
        "status": "LOCAL_PUBLIC_PROXY_EXPERIMENT_COMPLETED",
        "optimization_status": "CONVERGED",
        "effectiveness_status": (
            "OBSERVED_ON_PUBLIC_DEVELOPMENT_PROXY" if stable else "NOT_ESTABLISHED"
        ),
        "architecture": architecture,
        "feature_layers": [4, 6, 9],
        "split_seed": 20260913,
        "model_seed": 20260913,
        "stability_schema_version": "visiondata-gate.model-stability.v3",
        "checkpoint_sha256": _sha(pack),
        "backbone_weights_sha256": _sha(backbone),
        "model_result_file_sha256": _sha(result_path),
        "plan_file_sha256": _sha(plan_path),
        "agent_receipt_file_sha256": _sha(agent_path),
        "runtime_event_file_sha256": _sha(events_path),
        "selection_manifest_sha256": _sha(selection_path),
        "production_release_allowed": False,
        "machine_write_permitted": False,
    }
    run_receipt_path = run / "RUN_RECEIPT.json"
    _write_json(run_receipt_path, run_receipt)
    artifacts = {
        "RUN_RECEIPT.json": _sha(run_receipt_path),
        "model_result.json": _sha(result_path),
        "model_experiment_plan.json": _sha(plan_path),
        "selection_manifest.json": _sha(selection_path),
        "agent_runtime_events.json": _sha(events_path),
        "model_experiment_agent_receipt.json": _sha(agent_path),
        "private/worker_result.json": _sha(private_result_path),
        "private/worker/best_normality_model_pack.pt": _sha(pack),
    }
    for peer in peers:
        shutil.copytree(run, peer, dirs_exist_ok=True)
    stability_module = importlib.import_module("visiondata_gate.model_stability")
    outcome_module = importlib.import_module("visiondata_gate.model_experiment_agent")
    summary = {
        "schema_version": "visiondata-gate.model-stability.v4",
        "verification_implementation": {
            "stability_module_sha256": _sha(Path(stability_module.__file__)),
            "outcome_policy_module_sha256": _sha(Path(outcome_module.__file__)),
            "outcome_policy_function": "classify_experiment_outcome",
        },
        "evidence_contract": {
            "required_artifacts": list(artifacts),
            "model_pack_schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
            "model_pack_deserialization": "NOT_PERFORMED_NO_TORCH_IMPORT",
            "evaluation_membership_source": "PRIVATE_WORKER_RESULT",
            "outcome_derivation": "RECOMPUTED_WITH_BOUND_CLASSIFY_EXPERIMENT_OUTCOME",
        },
        "evaluated_run_count": 3,
        "comparability": {"status": "PASS", "failed_check_ids": []},
        "outcome_requirements": {
            "all_runs_completed": True,
            "all_optimization_converged": True,
            "all_effectiveness_observed": stable,
        },
        "runs": [
            {
                "run_label": run.name,
                "artifact_sha256": artifacts,
                "agent_evidence_sha256": {
                    "agent_receipt_self_seal_sha256": agent["receipt_sha256"],
                    "private_execution_result_sha256": _sha(private_result_path),
                    "runtime_event_chain_sha256": agent["runtime_event_chain_sha256"],
                },
            },
            {
                "run_label": "peer-seed-2",
                "artifact_sha256": artifacts,
                "agent_evidence_sha256": {
                    "agent_receipt_self_seal_sha256": agent["receipt_sha256"],
                    "private_execution_result_sha256": _sha(private_result_path),
                    "runtime_event_chain_sha256": agent["runtime_event_chain_sha256"],
                },
            },
            {
                "run_label": "peer-seed-3",
                "artifact_sha256": artifacts,
                "agent_evidence_sha256": {
                    "agent_receipt_self_seal_sha256": agent["receipt_sha256"],
                    "private_execution_result_sha256": _sha(private_result_path),
                    "runtime_event_chain_sha256": agent["runtime_event_chain_sha256"],
                },
            },
        ],
        "promotion_gate": {
            "status": "PUBLIC_PROXY_STABLE" if stable else "MODEL_PROMOTION_HOLD",
            "eligible": stable,
            "criterion_checks": {"comparability_contract": True},
            "blockers": [] if stable else ["EFFECTIVENESS_NOT_OBSERVED_ALL_SEEDS"],
        },
        "production_release_allowed": False,
    }
    summary_path = root / "MODEL_STABILITY_SUMMARY.json"
    _write_json(summary_path, summary)
    return {
        "run": run,
        "run_directories": [run, *peers],
        "pack": pack,
        "pack_sha": _sha(pack),
        "summary": summary_path,
        "binding": binding_path,
        "binding_sha": binding.binding_sha256,
        "index": index_path,
        "index_sha": index.index_sha256,
        "backbone": backbone,
        "backbone_sha": _sha(backbone),
    }


def _real_pack_request(module, evidence: dict, *, request_key: str):
    return module.RegisterNormalityModelPack(
        request_key=request_key,
        reviewer_identity="Named evidence reviewer",
        note="Verify and internalize the detached public-proxy evidence chain",
        display_name="Stable public-proxy candidate",
        model_pack_path=str(evidence["pack"]),
        expected_model_pack_sha256=evidence["pack_sha"],
        run_directory=str(evidence["run"]),
        stability_run_directories=[str(path) for path in evidence["run_directories"]],
        target_model_seed=20260913,
        stability_summary_path=str(evidence["summary"]),
        expected_stability_summary_sha256=_sha(evidence["summary"]),
        source_binding_path=str(evidence["binding"]),
        expected_source_binding_file_sha256=_sha(evidence["binding"]),
        expected_source_binding_sha256=evidence["binding_sha"],
        source_index_path=str(evidence["index"]),
        expected_source_index_file_sha256=_sha(evidence["index"]),
        expected_source_index_sha256=evidence["index_sha"],
        backbone_weights_path=str(evidence["backbone"]),
        expected_backbone_weights_sha256=evidence["backbone_sha"],
        operator_attests_read_authorized=True,
        operator_attests_weights_only_load_authorized=True,
        ultralytics_license_acknowledged=True,
    )


def _stub_stability_rebuild(module, evidence: dict, monkeypatch) -> None:
    summary = json.loads(evidence["summary"].read_text(encoding="utf-8"))
    monkeypatch.setattr(
        module,
        "_rebuild_normality_stability_summary",
        lambda _directories: summary,
    )


def _pack_request(module, root: Path, **updates):
    run = root / "run-seed-1"
    run.mkdir(parents=True, exist_ok=True)
    peers = [root / "peer-seed-2", root / "peer-seed-3"]
    for peer in peers:
        peer.mkdir()
    pack = run / "model-pack.pt"
    pack.write_bytes(b"opaque local model pack; never deserialize during registration")
    stability = root / "MODEL_STABILITY_SUMMARY.json"
    stability.write_text("{}", encoding="utf-8")
    binding = root / "source_binding.json"
    binding.write_text("{}", encoding="utf-8")
    index = root / "source_index.json"
    index.write_text("{}", encoding="utf-8")
    backbone = root / "yolo26n-cls.pt"
    backbone.write_bytes(b"opaque public backbone fixture")
    payload = {
        "request_key": "normality-pack-register-0001",
        "reviewer_identity": "Named model reviewer",
        "note": "Bind a self-contained pack to its frozen public-proxy evidence",
        "display_name": "YOLO26 normality research pack",
        "model_pack_path": str(pack),
        "expected_model_pack_sha256": _sha(pack),
        "run_directory": str(run),
        "stability_run_directories": [str(run), *(str(peer) for peer in peers)],
        "target_model_seed": 20260913,
        "stability_summary_path": str(stability),
        "expected_stability_summary_sha256": _sha(stability),
        "source_binding_path": str(binding),
        "expected_source_binding_file_sha256": _sha(binding),
        "expected_source_binding_sha256": "4" * 64,
        "source_index_path": str(index),
        "expected_source_index_file_sha256": _sha(index),
        "expected_source_index_sha256": "6" * 64,
        "backbone_weights_path": str(backbone),
        "expected_backbone_weights_sha256": _sha(backbone),
        "operator_attests_read_authorized": True,
        "operator_attests_weights_only_load_authorized": True,
        "ultralytics_license_acknowledged": True,
        **updates,
    }
    return module.RegisterNormalityModelPack.model_validate(payload)


def test_model_pack_registration_requires_weights_only_and_license_authority():
    from visiondata_gate.local_model_registry import RegisterNormalityModelPack

    payload = {
        "request_key": "normality-pack-register-0001",
        "reviewer_identity": "Named model reviewer",
        "note": "Bind a self-contained pack to its frozen public-proxy evidence",
        "display_name": "YOLO26 normality research pack",
        "model_pack_path": "E:/fixtures/model-pack.pt",
        "expected_model_pack_sha256": "1" * 64,
        "run_directory": "E:/fixtures/run-seed-1",
        "stability_run_directories": [
            "E:/fixtures/run-seed-1",
            "E:/fixtures/run-seed-2",
            "E:/fixtures/run-seed-3",
        ],
        "target_model_seed": 20260913,
        "stability_summary_path": "E:/fixtures/MODEL_STABILITY_SUMMARY.json",
        "expected_stability_summary_sha256": "2" * 64,
        "source_binding_path": "E:/fixtures/source_binding.json",
        "expected_source_binding_file_sha256": "3" * 64,
        "expected_source_binding_sha256": "4" * 64,
        "source_index_path": "E:/fixtures/source_index.json",
        "expected_source_index_file_sha256": "5" * 64,
        "expected_source_index_sha256": "6" * 64,
        "backbone_weights_path": "E:/fixtures/yolo26n-cls.pt",
        "expected_backbone_weights_sha256": "7" * 64,
        "operator_attests_read_authorized": True,
        "operator_attests_weights_only_load_authorized": True,
        "ultralytics_license_acknowledged": True,
    }

    request = RegisterNormalityModelPack.model_validate(payload)
    assert request.operator_attests_weights_only_load_authorized is True
    assert request.ultralytics_license_acknowledged is True
    with pytest.raises(ValidationError):
        RegisterNormalityModelPack.model_validate(
            payload | {"operator_attests_weights_only_load_authorized": False}
        )
    with pytest.raises(ValidationError):
        RegisterNormalityModelPack.model_validate(
            payload | {"ultralytics_license_acknowledged": False}
        )


def test_legacy_v1_pack_is_rejected_by_governed_normality_registry(
    product_scope, tmp_path, monkeypatch
):
    module = importlib.import_module("visiondata_gate.local_model_registry")
    product, actor, project_id = product_scope
    evidence = _real_evidence(
        tmp_path / "evidence",
        pack_schema="visiondata-gate.yolo26-normality-model-pack.v1",
        stable=False,
    )
    request = _real_pack_request(
        module, evidence, request_key="normality-legacy-register-0001"
    )
    _stub_stability_rebuild(module, evidence, monkeypatch)

    service = module.LocalVisionModelService(product)
    with pytest.raises(module.VisionModelError, match="MODEL_PACK_V2_REQUIRED"):
        service.register_normality_model_pack(actor, project_id, request)


def test_registration_evidence_binds_v2_pack_to_detached_sha_chain(
    tmp_path, monkeypatch
):
    module = importlib.import_module("visiondata_gate.local_model_registry")
    evidence = _real_evidence(
        tmp_path / "real-evidence",
        pack_schema="visiondata-gate.yolo26-normality-model-pack.v2",
        stable=True,
    )
    request = _real_pack_request(
        module, evidence, request_key="normality-evidence-verify-0001"
    )
    _stub_stability_rebuild(module, evidence, monkeypatch)

    verified = module._verify_normality_pack_registration_evidence(request)

    assert verified["pack_schema_version"].endswith(".v2")
    assert verified["stability_status"] == "PUBLIC_PROXY_STABLE"
    assert verified["stability_eligible"] is True
    assert verified["source_binding_sha256"] == evidence["binding_sha"]
    assert verified["source_index_sha256"] == evidence["index_sha"]
    assert verified["backbone_weights_sha256"] == evidence["backbone_sha"]


def test_registration_internalizes_pack_and_evidence_in_content_addressed_storage(
    product_scope, tmp_path, monkeypatch
):
    module = importlib.import_module("visiondata_gate.local_model_registry")
    product, actor, project_id = product_scope
    evidence_root = tmp_path / "movable-external-evidence"
    evidence = _real_evidence(
        evidence_root,
        pack_schema="visiondata-gate.yolo26-normality-model-pack.v2",
        stable=True,
    )
    request = _real_pack_request(
        module, evidence, request_key="normality-cas-register-0001"
    )
    _stub_stability_rebuild(module, evidence, monkeypatch)
    service = module.LocalVisionModelService(product)

    model = service.register_normality_model_pack(actor, project_id, request)
    moved = tmp_path / "external-evidence-moved-after-registration"
    evidence_root.rename(moved)
    with product.store._connection() as connection:
        _public, private = service._read(
            connection, project_id, model["model_id"], "model"
        )
    verified = module._verify_normality_pack_cas(service.root, model, private)

    assert model["storage_scope"] == "REGISTRY_OWNED_CONTENT_ADDRESSED"
    assert str(evidence_root) not in json.dumps(private)
    assert len(private["cas_files"]) == 27
    assert verified["model_pack"].is_file()
    assert _sha(verified["model_pack"]) == model["model_pack_sha256"]


def test_cas_copy_rejects_junction_before_writing_digest_path(
    tmp_path, monkeypatch
):
    module = importlib.import_module("visiondata_gate.local_model_registry")
    registry_root = tmp_path / "vision_models"
    registry_root.mkdir()
    source = tmp_path / "source.bin"
    source.write_bytes(b"registry-owned content")
    digest = _sha(source)
    target_parent = registry_root / "cas" / "sha256" / digest[:2]
    real_is_junction = Path.is_junction

    def simulated_junction(path):
        if path.absolute() == target_parent.absolute():
            return True
        return real_is_junction(path)

    monkeypatch.setattr(Path, "is_junction", simulated_junction)

    with pytest.raises(module.VisionModelError, match="REGISTRY_PATH_LINK_FORBIDDEN"):
        module._cas_copy(registry_root, source, digest)

    assert not (target_parent / digest).exists()


def test_cas_copy_rechecks_parent_for_junction_after_writing(
    tmp_path, monkeypatch
):
    module = importlib.import_module("visiondata_gate.local_model_registry")
    registry_root = tmp_path / "vision_models"
    registry_root.mkdir()
    source = tmp_path / "source.bin"
    source.write_bytes(b"registry-owned race fixture")
    digest = _sha(source)
    target_parent = registry_root / "cas" / "sha256" / digest[:2]
    real_is_junction = Path.is_junction
    target_checks = 0

    def junction_after_write(path):
        nonlocal target_checks
        if path.absolute() == target_parent.absolute():
            target_checks += 1
            return target_checks >= 4
        return real_is_junction(path)

    monkeypatch.setattr(Path, "is_junction", junction_after_write)

    with pytest.raises(module.VisionModelError, match="REGISTRY_PATH_LINK_FORBIDDEN"):
        module._cas_copy(registry_root, source, digest)

    assert target_checks >= 4


def test_stable_v2_pack_requires_named_runtime_validation_before_sandbox_approval(
    product_scope, tmp_path, monkeypatch
):
    module = importlib.import_module("visiondata_gate.local_model_registry")
    backend = importlib.import_module("visiondata_gate.learning_yolo_backend")
    inference = importlib.import_module("visiondata_gate.normality_inference")
    product, actor, project_id = product_scope
    evidence = _real_evidence(
        tmp_path / "stable-evidence",
        pack_schema="visiondata-gate.yolo26-normality-model-pack.v2",
        stable=True,
    )
    request = _real_pack_request(
        module, evidence, request_key="normality-stable-register-0001"
    )
    _stub_stability_rebuild(module, evidence, monkeypatch)
    runtime_file = tmp_path / "runtime.exe"
    runtime_file.write_bytes(b"synthetic runtime identity")
    executable_sha = _sha(runtime_file)
    runtime_sha = "9" * 64
    inference_backend_sha = _sha(Path(inference.__file__))
    monkeypatch.setattr(
        backend,
        "probe_vision_runtime",
        lambda *_args, import_check=False, **_kwargs: {
            "status": "ready",
            "runtime_sha256": runtime_sha,
            "import_status": "PASSED" if import_check else "NOT_RUN",
        },
    )
    validation_calls = []

    def validate(**kwargs):
        validation_calls.append(kwargs)
        return {
            "schema_version": "visiondata-gate.normality-pack-validation.v1",
            "status": "VALIDATED_FOR_LOCAL_SANDBOX",
            "model_pack_sha256": request.expected_model_pack_sha256,
            "backbone_weights_sha256": request.expected_backbone_weights_sha256,
            "source_binding_sha256": request.expected_source_binding_sha256,
            "source_index_sha256": request.expected_source_index_sha256,
            "runtime_sha256": runtime_sha,
            "inference_backend_sha256": inference_backend_sha,
            "model_pack_schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
            "production_release_allowed": False,
        }

    monkeypatch.setattr(inference, "validate_normality_model_pack", validate)
    service = module.LocalVisionModelService(product)
    model = service.register_normality_model_pack(actor, project_id, request)
    assert model["status"] == "MODEL_PACK_EVIDENCE_VERIFIED"
    runtime = service.register_runtime(
        actor,
        project_id,
        module.RegisterVisionRuntime(
            request_key="normality-runtime-register-0001",
            reviewer_identity="Named runtime reviewer",
            note="Register an explicitly selected local runtime for pack validation",
            display_name="Synthetic runtime",
            executable_path=str(runtime_file),
            expected_executable_sha256=executable_sha,
            operator_attests_trusted_runtime=True,
            operator_attests_execution_authorized=True,
        ),
    )
    runtime = service.probe_runtime(
        actor,
        project_id,
        runtime["runtime_id"],
        module.ProbeVisionRuntime(
            request_key="normality-runtime-probe-0001",
            reviewer_identity="Named runtime reviewer",
            note="Import the selected runtime before any model pack deserialization",
            expected_runtime_sha256=runtime_sha,
            operator_attests_trusted_runtime=True,
            operator_attests_execution_authorized=True,
            import_check=True,
        ),
    )
    approval_request = module.ApproveNormalityModelPack(
        request_key="normality-sandbox-approval-0001",
        reviewer_identity="Named model approver",
        note="Approve only the exact v2 pack for bounded local sandbox inference",
        action="APPROVE_SANDBOX",
        expected_model_receipt_sha256=model["receipt_sha256"],
        expected_model_pack_sha256=request.expected_model_pack_sha256,
        expected_backbone_weights_sha256=request.expected_backbone_weights_sha256,
        expected_source_binding_sha256=request.expected_source_binding_sha256,
        expected_source_index_sha256=request.expected_source_index_sha256,
        runtime_id=runtime["runtime_id"],
        expected_runtime_sha256=runtime_sha,
        operator_attests_reviewed=True,
        operator_attests_trusted_runtime=True,
        operator_attests_execution_authorized=True,
        operator_attests_trusted_weights=True,
        operator_attests_weights_only_load_authorized=True,
        ultralytics_license_acknowledged=True,
    )
    real_is_junction = Path.is_junction
    validation_root = service.root / "pack_validations"

    def validation_junction(path):
        if path.absolute() == validation_root.absolute():
            return True
        return real_is_junction(path)

    monkeypatch.setattr(Path, "is_junction", validation_junction)
    with pytest.raises(module.VisionModelError, match="REGISTRY_PATH_LINK_FORBIDDEN"):
        service.approve_normality_model_pack(
            actor, project_id, model["model_id"], approval_request
        )
    monkeypatch.setattr(Path, "is_junction", real_is_junction)

    approved = service.approve_normality_model_pack(
        actor,
        project_id,
        model["model_id"],
        approval_request,
    )

    assert approved["status"] == "APPROVE_SANDBOX"
    assert approved["sandbox_runtime_id"] == runtime["runtime_id"]
    assert (
        approved["sandbox_validation"]["inference_backend_sha256"]
        == inference_backend_sha
    )
    assert approved["loaded"] is False
    assert approved["production_release_allowed"] is False
    assert len(validation_calls) == 1
    assert _sha(validation_calls[0]["model_pack"]) == request.expected_model_pack_sha256
    assert validation_calls[0]["model_pack"].is_relative_to(service.root)


def test_inference_asset_is_frozen_in_registry_without_exposing_source_path(
    product_scope, tmp_path
):
    module = importlib.import_module("visiondata_gate.local_model_registry")
    product, actor, project_id = product_scope
    source = tmp_path / "operator-source.png"
    Image.new("RGB", (24, 16), (30, 80, 120)).save(source)
    service = module.LocalVisionModelService(product)

    asset = service.register_inference_asset(
        actor,
        project_id,
        module.RegisterVisionInferenceAsset(
            request_key="normality-asset-register-0001",
            reviewer_identity="Named image reviewer",
            note="Freeze an authorized local image for one bounded inference request",
            display_name="Inspection frame 001",
            image_path=str(source),
            expected_image_sha256=_sha(source),
            operator_attests_read_authorized=True,
        ),
    )
    source.unlink()
    with product.store._connection() as connection:
        _public, private = service._read(
            connection, project_id, asset["asset_id"], "inference_asset"
        )

    assert asset["status"] == "FROZEN_LOCAL_INFERENCE_ASSET"
    assert asset["image_width"] == 24
    assert asset["image_height"] == 16
    assert asset["production_release_allowed"] is False
    assert str(tmp_path) not in json.dumps(asset)
    assert _sha(Path(private["cas_path"])) == asset["image_sha256"]


def test_inference_uses_only_approved_registry_model_and_frozen_asset_ids(
    product_scope, tmp_path, monkeypatch
):
    module = importlib.import_module("visiondata_gate.local_model_registry")
    backend = importlib.import_module("visiondata_gate.learning_yolo_backend")
    inference = importlib.import_module("visiondata_gate.normality_inference")
    product, actor, project_id = product_scope
    evidence = _real_evidence(
        tmp_path / "inference-evidence",
        pack_schema="visiondata-gate.yolo26-normality-model-pack.v2",
        stable=True,
    )
    pack_request = _real_pack_request(
        module, evidence, request_key="normality-infer-pack-register-0001"
    )
    _stub_stability_rebuild(module, evidence, monkeypatch)
    runtime_file = tmp_path / "inference-runtime.exe"
    runtime_file.write_bytes(b"synthetic runtime identity")
    executable_sha = _sha(runtime_file)
    runtime_sha = "9" * 64
    inference_backend_sha = _sha(Path(inference.__file__))
    monkeypatch.setattr(
        backend,
        "probe_vision_runtime",
        lambda *_args, import_check=False, **_kwargs: {
            "status": "ready",
            "runtime_sha256": runtime_sha,
            "import_status": "PASSED" if import_check else "NOT_RUN",
        },
    )
    monkeypatch.setattr(
        inference,
        "validate_normality_model_pack",
        lambda **_kwargs: {
            "schema_version": "visiondata-gate.normality-pack-validation.v1",
            "status": "VALIDATED_FOR_LOCAL_SANDBOX",
            "model_pack_sha256": pack_request.expected_model_pack_sha256,
            "backbone_weights_sha256": pack_request.expected_backbone_weights_sha256,
            "source_binding_sha256": pack_request.expected_source_binding_sha256,
            "source_index_sha256": pack_request.expected_source_index_sha256,
            "runtime_sha256": runtime_sha,
            "inference_backend_sha256": inference_backend_sha,
            "model_pack_schema_version": "visiondata-gate.yolo26-normality-model-pack.v2",
            "production_release_allowed": False,
        },
    )
    service = module.LocalVisionModelService(product)
    model = service.register_normality_model_pack(actor, project_id, pack_request)
    runtime = service.register_runtime(
        actor,
        project_id,
        module.RegisterVisionRuntime(
            request_key="normality-infer-runtime-register-0001",
            reviewer_identity="Named runtime reviewer",
            note="Register a local runtime for the registry inference test",
            display_name="Synthetic runtime",
            executable_path=str(runtime_file),
            expected_executable_sha256=executable_sha,
            operator_attests_trusted_runtime=True,
            operator_attests_execution_authorized=True,
        ),
    )
    runtime = service.probe_runtime(
        actor,
        project_id,
        runtime["runtime_id"],
        module.ProbeVisionRuntime(
            request_key="normality-infer-runtime-probe-0001",
            reviewer_identity="Named runtime reviewer",
            note="Import probe the exact runtime before bounded inference",
            expected_runtime_sha256=runtime_sha,
            operator_attests_trusted_runtime=True,
            operator_attests_execution_authorized=True,
            import_check=True,
        ),
    )
    approved = service.approve_normality_model_pack(
        actor,
        project_id,
        model["model_id"],
        module.ApproveNormalityModelPack(
            request_key="normality-infer-sandbox-approve-0001",
            reviewer_identity="Named model approver",
            note="Approve this exact v2 pack for local sandbox inference only",
            action="APPROVE_SANDBOX",
            expected_model_receipt_sha256=model["receipt_sha256"],
            expected_model_pack_sha256=pack_request.expected_model_pack_sha256,
            expected_backbone_weights_sha256=pack_request.expected_backbone_weights_sha256,
            expected_source_binding_sha256=pack_request.expected_source_binding_sha256,
            expected_source_index_sha256=pack_request.expected_source_index_sha256,
            runtime_id=runtime["runtime_id"],
            expected_runtime_sha256=runtime_sha,
            operator_attests_reviewed=True,
            operator_attests_trusted_runtime=True,
            operator_attests_execution_authorized=True,
            operator_attests_trusted_weights=True,
            operator_attests_weights_only_load_authorized=True,
            ultralytics_license_acknowledged=True,
        ),
    )
    image = tmp_path / "asset.png"
    Image.new("RGB", (20, 12), (100, 50, 25)).save(image)
    asset = service.register_inference_asset(
        actor,
        project_id,
        module.RegisterVisionInferenceAsset(
            request_key="normality-infer-asset-register-0001",
            reviewer_identity="Named image reviewer",
            note="Freeze a local image before the inference request uses its asset ID",
            display_name="Frame 001",
            image_path=str(image),
            expected_image_sha256=_sha(image),
            operator_attests_read_authorized=True,
        ),
    )
    calls = []

    def infer(**kwargs):
        calls.append(kwargs)
        heatmap = kwargs["output_root"] / "artifacts" / "heatmap.png"
        heatmap.parent.mkdir(parents=True)
        heatmap.write_bytes(b"registry heatmap")
        return {
            "schema_version": "visiondata-gate.normality-inference-result.v1",
            "status": "COMPLETED_LOCAL_SANDBOX_INFERENCE",
            "model_pack_sha256": approved["model_pack_sha256"],
            "model_pack_schema_version": approved["model_pack_schema_version"],
            "backbone_weights_sha256": approved["backbone_weights_sha256"],
            "source_binding_sha256": approved["source_binding_sha256"],
            "source_index_sha256": approved["source_index_sha256"],
            "runtime_sha256": runtime_sha,
            "inference_backend_sha256": inference_backend_sha,
            "image_sha256": asset["image_sha256"],
            "image_score": 0.75,
            "image_threshold": 0.5,
            "pixel_threshold": 1.5,
            "predicted_anomaly": True,
            "positive_pixel_fraction": 0.125,
            "heatmap": {
                "sha256": _sha(heatmap),
                "bytes": heatmap.stat().st_size,
                "width": 64,
                "height": 64,
                "format": "png",
            },
            "device": "cpu",
            "decision_scope": "MODEL_SIGNAL_ONLY_NOT_GATE_OR_PRODUCTION_DECISION",
            "machine_write_permitted": False,
            "production_release_allowed": False,
        }

    monkeypatch.setattr(inference, "run_normality_inference", infer)
    inference_request = module.RunNormalityInference(
        request_key="normality-inference-run-0001",
        reviewer_identity="Named inference operator",
        note="Run one bounded local model signal without granting a gate decision",
        expected_model_receipt_sha256=approved["receipt_sha256"],
        expected_model_pack_sha256=approved["model_pack_sha256"],
        expected_backbone_weights_sha256=approved["backbone_weights_sha256"],
        expected_source_binding_sha256=approved["source_binding_sha256"],
        expected_source_index_sha256=approved["source_index_sha256"],
        expected_runtime_sha256=runtime_sha,
        asset_id=asset["asset_id"],
        expected_asset_receipt_sha256=asset["receipt_sha256"],
        expected_image_sha256=asset["image_sha256"],
        max_seconds=120,
        operator_attests_execution_authorized=True,
        operator_attests_trusted_runtime=True,
        operator_attests_trusted_weights=True,
        operator_attests_weights_only_load_authorized=True,
    )
    real_is_junction = Path.is_junction
    inference_root = service.root / "inferences"

    def inference_junction(path):
        if path.absolute() == inference_root.absolute():
            return True
        return real_is_junction(path)

    monkeypatch.setattr(Path, "is_junction", inference_junction)
    with pytest.raises(module.VisionModelError, match="REGISTRY_PATH_LINK_FORBIDDEN"):
        service.run_normality_inference(
            actor,
            project_id,
            approved["model_id"],
            inference_request,
        )
    monkeypatch.setattr(Path, "is_junction", real_is_junction)

    receipt = service.run_normality_inference(
        actor,
        project_id,
        approved["model_id"],
        inference_request,
    )

    assert receipt["status"] == "COMPLETED_LOCAL_SANDBOX_INFERENCE"
    assert receipt["model_id"] == approved["model_id"]
    assert receipt["asset_id"] == asset["asset_id"]
    assert receipt["heatmap_artifact_id"].startswith("normality_heatmap_")
    assert receipt["inference_backend_sha256"] == inference_backend_sha
    assert receipt["production_release_allowed"] is False
    assert len(calls) == 1
    assert calls[0]["model_pack"].is_relative_to(service.root)
    assert calls[0]["image"].is_relative_to(service.root)
    assert str(tmp_path) not in json.dumps(receipt)

    monkeypatch.setattr(
        module,
        "_normality_backend_sha256",
        lambda: "0" * 64,
        raising=False,
    )
    with pytest.raises(
        module.VisionModelError,
        match="INFERENCE_BACKEND_CHANGED_SINCE_SANDBOX_APPROVAL",
    ):
        service.run_normality_inference(
            actor,
            project_id,
            approved["model_id"],
            inference_request.model_copy(
                update={"request_key": "normality-inference-run-drift-0001"}
            ),
        )

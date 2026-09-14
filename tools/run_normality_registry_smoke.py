"""Run the complete registry-owned YOLO26 normality sandbox smoke.

All local inputs are explicit CLI arguments.  The command recomputes the
three-run stability contract, copies every required artifact into registry CAS,
import-probes the selected runtime, validates the pack with weights_only=True,
and runs two predeclared model-signal examples.  It never grants a Gate or
production decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visiondata_gate.evidence import canonical_json_bytes  # noqa: E402
from visiondata_gate.local_model_registry import (  # noqa: E402
    ApproveNormalityModelPack,
    LocalVisionModelService,
    ProbeVisionRuntime,
    RegisterNormalityModelPack,
    RegisterVisionInferenceAsset,
    RegisterVisionRuntime,
    RunNormalityInference,
    _seal,
)
from visiondata_gate.product_service import ProductService  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute v4 evidence and run registry-owned local normality "
            "validation plus two model-signal inferences."
        )
    )
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--target-run-dir", required=True)
    parser.add_argument("--target-model-seed", type=int, default=20260913)
    parser.add_argument("--stability-summary", required=True)
    parser.add_argument("--source-binding", required=True)
    parser.add_argument("--source-index", required=True)
    parser.add_argument("--backbone-weights", required=True)
    parser.add_argument("--runtime-python", required=True)
    parser.add_argument("--normal-image", required=True)
    parser.add_argument("--anomaly-image", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--reviewer-identity", required=True)
    parser.add_argument(
        "--authorize-local-execution", action="store_true", required=True
    )
    parser.add_argument(
        "--authorize-weights-only-load", action="store_true", required=True
    )
    parser.add_argument(
        "--acknowledge-ultralytics-license-review",
        action="store_true",
        required=True,
    )
    return parser


def _resolved_file(value: str) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file() or path.is_symlink():
        raise ValueError("SMOKE_FILE_INPUT_INVALID")
    return path


def _resolved_directory(value: str) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir() or path.is_symlink() or path.is_junction():
        raise ValueError("SMOKE_DIRECTORY_INPUT_INVALID")
    return path


def _write_receipt(output: Path, body: dict) -> dict:
    receipt = _seal(body)
    (output / "ACTUAL_REGISTRY_SMOKE_RECEIPT.json").write_bytes(
        canonical_json_bytes(receipt)
    )
    return receipt


def _inference_backend_projection(approved: dict, results: dict) -> str:
    backend_sha = approved.get("sandbox_validation", {}).get(
        "inference_backend_sha256"
    )
    if (
        not isinstance(backend_sha, str)
        or len(backend_sha) != 64
        or any(character not in "0123456789abcdef" for character in backend_sha)
        or set(results) != {"normal", "anomaly"}
        or any(
            result.get("inference_backend_sha256") != backend_sha
            for result in results.values()
        )
    ):
        raise ValueError("SMOKE_INFERENCE_BACKEND_IDENTITY_MISMATCH")
    return backend_sha


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        print("REGISTRY_SMOKE_FRESH_OUTPUT_REQUIRED", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=False)
    product: ProductService | None = None
    try:
        if len(args.run_dir) != 3 or len(set(args.run_dir)) != 3:
            raise ValueError("THREE_UNIQUE_STABILITY_RUNS_REQUIRED")
        if args.target_model_seed != 20260913:
            raise ValueError("PREDECLARED_TARGET_MODEL_SEED_REQUIRED")
        runs = [_resolved_directory(value) for value in args.run_dir]
        target_run = _resolved_directory(args.target_run_dir)
        if target_run not in runs:
            raise ValueError("TARGET_RUN_NOT_IN_STABILITY_RUNS")
        stability = _resolved_file(args.stability_summary)
        binding = _resolved_file(args.source_binding)
        index = _resolved_file(args.source_index)
        backbone = _resolved_file(args.backbone_weights)
        runtime_path = _resolved_file(args.runtime_python)
        normal_image = _resolved_file(args.normal_image)
        anomaly_image = _resolved_file(args.anomaly_image)
        model_pack = _resolved_file(
            str(
                target_run
                / "private"
                / "worker"
                / "best_normality_model_pack.pt"
            )
        )
        binding_value = json.loads(binding.read_text(encoding="utf-8"))
        index_value = json.loads(index.read_text(encoding="utf-8"))

        product = ProductService(output / "product", recover_interrupted=False)
        user, _workspace, project = product.ensure_default_tenant()
        actor, project_id = user.user_id, project.project_id
        service = LocalVisionModelService(product)
        model = service.register_normality_model_pack(
            actor,
            project_id,
            RegisterNormalityModelPack(
                request_key="normality-smoke-pack-register-0001",
                reviewer_identity=args.reviewer_identity,
                note="Recompute three runs and internalize the predeclared v2 pack",
                display_name="YOLO26 normality predeclared seed13 pack",
                model_pack_path=str(model_pack),
                expected_model_pack_sha256=_sha256(model_pack),
                run_directory=str(target_run),
                stability_run_directories=[str(path) for path in runs],
                target_model_seed=args.target_model_seed,
                stability_summary_path=str(stability),
                expected_stability_summary_sha256=_sha256(stability),
                source_binding_path=str(binding),
                expected_source_binding_file_sha256=_sha256(binding),
                expected_source_binding_sha256=binding_value["binding_sha256"],
                source_index_path=str(index),
                expected_source_index_file_sha256=_sha256(index),
                expected_source_index_sha256=index_value["index_sha256"],
                backbone_weights_path=str(backbone),
                expected_backbone_weights_sha256=_sha256(backbone),
                operator_attests_read_authorized=True,
                operator_attests_weights_only_load_authorized=(
                    args.authorize_weights_only_load
                ),
                ultralytics_license_acknowledged=(
                    args.acknowledge_ultralytics_license_review
                ),
            ),
        )
        runtime = service.register_runtime(
            actor,
            project_id,
            RegisterVisionRuntime(
                request_key="normality-smoke-runtime-register-0001",
                reviewer_identity=args.reviewer_identity,
                note="Register the explicit external runtime for bounded local smoke",
                display_name="Explicit external normality runtime",
                executable_path=str(runtime_path),
                expected_executable_sha256=_sha256(runtime_path),
                operator_attests_trusted_runtime=True,
                operator_attests_execution_authorized=args.authorize_local_execution,
            ),
        )
        runtime = service.probe_runtime(
            actor,
            project_id,
            runtime["runtime_id"],
            ProbeVisionRuntime(
                request_key="normality-smoke-runtime-probe-0001",
                reviewer_identity=args.reviewer_identity,
                note="Import-probe the exact runtime before weights-only loading",
                expected_runtime_sha256=runtime["runtime_sha256"],
                operator_attests_trusted_runtime=True,
                operator_attests_execution_authorized=args.authorize_local_execution,
                import_check=True,
            ),
        )
        approved = service.approve_normality_model_pack(
            actor,
            project_id,
            model["model_id"],
            ApproveNormalityModelPack(
                request_key="normality-smoke-sandbox-approval-0001",
                reviewer_identity=args.reviewer_identity,
                note="Approve the exact v2 pack for local sandbox inference only",
                action="APPROVE_SANDBOX",
                expected_model_receipt_sha256=model["receipt_sha256"],
                expected_model_pack_sha256=model["model_pack_sha256"],
                expected_backbone_weights_sha256=model["backbone_weights_sha256"],
                expected_source_binding_sha256=model["source_binding_sha256"],
                expected_source_index_sha256=model["source_index_sha256"],
                runtime_id=runtime["runtime_id"],
                expected_runtime_sha256=runtime["runtime_sha256"],
                operator_attests_reviewed=True,
                operator_attests_trusted_runtime=True,
                operator_attests_execution_authorized=args.authorize_local_execution,
                operator_attests_trusted_weights=True,
                operator_attests_weights_only_load_authorized=(
                    args.authorize_weights_only_load
                ),
                ultralytics_license_acknowledged=(
                    args.acknowledge_ultralytics_license_review
                ),
            ),
        )

        results = {}
        for label, image in (("normal", normal_image), ("anomaly", anomaly_image)):
            asset = service.register_inference_asset(
                actor,
                project_id,
                RegisterVisionInferenceAsset(
                    request_key=f"normality-smoke-{label}-asset-0001",
                    reviewer_identity=args.reviewer_identity,
                    note=f"Freeze the predeclared {label} image into registry CAS",
                    display_name=f"Predeclared {label} evidence image",
                    image_path=str(image),
                    expected_image_sha256=_sha256(image),
                    operator_attests_read_authorized=True,
                ),
            )
            inference = service.run_normality_inference(
                actor,
                project_id,
                approved["model_id"],
                RunNormalityInference(
                    request_key=f"normality-smoke-{label}-inference-0001",
                    reviewer_identity=args.reviewer_identity,
                    note=f"Run one bounded {label} signal without a Gate decision",
                    expected_model_receipt_sha256=approved["receipt_sha256"],
                    expected_model_pack_sha256=approved["model_pack_sha256"],
                    expected_backbone_weights_sha256=approved[
                        "backbone_weights_sha256"
                    ],
                    expected_source_binding_sha256=approved[
                        "source_binding_sha256"
                    ],
                    expected_source_index_sha256=approved["source_index_sha256"],
                    expected_runtime_sha256=approved["sandbox_runtime_sha256"],
                    asset_id=asset["asset_id"],
                    expected_asset_receipt_sha256=asset["receipt_sha256"],
                    expected_image_sha256=asset["image_sha256"],
                    max_seconds=120,
                    operator_attests_execution_authorized=(
                        args.authorize_local_execution
                    ),
                    operator_attests_trusted_runtime=True,
                    operator_attests_trusted_weights=True,
                    operator_attests_weights_only_load_authorized=(
                        args.authorize_weights_only_load
                    ),
                ),
            )
            results[label] = {
                "reference_label": label,
                "label_truth_authority": False,
                "asset_id": asset["asset_id"],
                "image_sha256": asset["image_sha256"],
                "inference_id": inference["inference_id"],
                "status": inference["status"],
                "image_score": inference["image_score"],
                "image_threshold": inference["image_threshold"],
                "predicted_anomaly": inference["predicted_anomaly"],
                "inference_backend_sha256": inference[
                    "inference_backend_sha256"
                ],
                "heatmap_sha256": inference["heatmap"]["sha256"],
                "receipt_sha256": inference["receipt_sha256"],
                "production_release_allowed": False,
            }
        receipt = _write_receipt(
            output,
            {
                "schema_version": (
                    "visiondata-gate.actual-normality-registry-smoke.v1"
                ),
                "model_id": approved["model_id"],
                "model_status": approved["status"],
                "model_pack_sha256": approved["model_pack_sha256"],
                "stability_schema_version": approved["stability_schema_version"],
                "stability_status": approved["stability_status"],
                "verification_implementation": approved[
                    "verification_implementation"
                ],
                "runtime_id": runtime["runtime_id"],
                "runtime_sha256": runtime["runtime_sha256"],
                "runtime_import_status": runtime["probe"]["import_status"],
                "inference_backend_sha256": _inference_backend_projection(
                    approved, results
                ),
                "cas_logical_file_count": (
                    len(approved["stability_run_artifact_sha256"]) * 8 + 3
                ),
                "results": results,
                "claim_boundary": (
                    "Local registry and model-signal smoke only. Reference labels "
                    "are retained for transparency but are not governance truth; "
                    "no factory, Gate, or production claim is made."
                ),
                "machine_write_permitted": False,
                "production_release_allowed": False,
            },
        )
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except Exception as error:
        failure = _write_receipt(
            output,
            {
                "schema_version": (
                    "visiondata-gate.actual-normality-registry-smoke-failure.v1"
                ),
                "status": "HOLD",
                "error_type": type(error).__name__,
                "error_code": str(error).split(":", 1)[0][:120],
                "machine_write_permitted": False,
                "production_release_allowed": False,
            },
        )
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 2
    finally:
        if product is not None:
            product.close(wait=True)


if __name__ == "__main__":
    raise SystemExit(main())

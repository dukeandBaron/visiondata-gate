"""Command-line interface for the complete VisionData Gate demo."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

_MODEL_BACKEND_CHOICES = (
    "deterministic",
    "openai_compatible",
    "longcat_openai_compatible",
)
_SCENARIO_CHOICES = (
    "generic",
    "industrial",
    "automotive",
    "finance",
    "education",
    "wearable",
)
_DEFAULT_MODEL_BACKEND = "deterministic"
_DEFAULT_SCENARIO = "generic"
_DEFAULT_MAX_REPROJECTION_ERROR_PX = 2.5


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="visiondata-gate",
        description="Auditable industrial-vision data release gate",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser(
        "generate", help="generate a deterministic demo dataset"
    )
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--seed", type=int, default=20260809)

    gate = subparsers.add_parser("gate", help="run the release gate on one manifest")
    gate.add_argument("--batch-root", type=Path, required=True)
    gate.add_argument("--manifest", type=Path, required=True)
    gate.add_argument("--contract", type=Path)
    gate.add_argument("--output", type=Path, required=True)
    gate.add_argument(
        "--scenario",
        choices=_SCENARIO_CHOICES,
        default=_DEFAULT_SCENARIO,
        help="scenario profile for governance thresholds",
    )

    geometry_gate = subparsers.add_parser(
        "geometry-gate",
        help="merge a normalized VGGT/OmniVGGT receipt into an explicit gate run",
    )
    geometry_gate.add_argument("--batch-root", type=Path, required=True)
    geometry_gate.add_argument("--manifest", type=Path, required=True)
    geometry_gate.add_argument("--contract", type=Path)
    geometry_gate.add_argument("--geometry-evidence", type=Path)
    geometry_gate.add_argument("--geometry-endpoint")
    geometry_gate.add_argument(
        "--geometry-backend", choices=["vggt", "omnivggt"], default="vggt"
    )
    geometry_gate.add_argument(
        "--geometry-backend-mode",
        choices=["contract_test", "real"],
        default="contract_test",
    )
    geometry_gate.add_argument("--geometry-expected-checkpoint-sha256")
    geometry_gate.add_argument("--geometry-endpoint-host", action="append", default=[])
    geometry_gate.add_argument("--allow-remote-geometry", action="store_true")
    geometry_gate.add_argument("--allow-geometry-image-upload", action="store_true")
    geometry_gate.add_argument("--geometry-timeout-seconds", type=float, default=30.0)
    geometry_gate.add_argument("--output", type=Path, required=True)
    geometry_gate.add_argument(
        "--scenario",
        choices=_SCENARIO_CHOICES,
        default="industrial",
        help="scenario profile for governance thresholds",
    )
    geometry_gate.add_argument(
        "--optional",
        action="store_true",
        help="treat a missing geometry receipt as NOT_TESTED instead of fail-closed",
    )
    geometry_gate.add_argument(
        "--max-reprojection-error-px",
        type=float,
        default=_DEFAULT_MAX_REPROJECTION_ERROR_PX,
    )

    demo = subparsers.add_parser("demo", help="run generate-to-repair closed loop")
    demo.add_argument("--output", type=Path, required=True)
    demo.add_argument("--seed", type=int, default=20260809)
    demo.add_argument(
        "--scenario",
        choices=_SCENARIO_CHOICES,
        default=_DEFAULT_SCENARIO,
        help="scenario profile for governance thresholds",
    )

    agent_demo = subparsers.add_parser(
        "agent-demo",
        help="run the observable Router/Workers/Council/Judge closed loop",
    )
    agent_demo.add_argument("--output", type=Path, required=True)
    agent_demo.add_argument("--seed", type=int, default=20260809)
    agent_demo.add_argument(
        "--goal",
        default=(
            "审核工业视觉数据批次能否进入沙箱实验训练池；若阻断，"
            "生成可执行工单并在同合同下复验。"
        ),
    )
    agent_demo.add_argument(
        "--backend",
        choices=_MODEL_BACKEND_CHOICES,
        default=_DEFAULT_MODEL_BACKEND,
    )
    agent_demo.add_argument("--model", default="local-evidence-reasoner-v2")
    agent_demo.add_argument("--endpoint")
    agent_demo.add_argument("--allow-remote-model", action="store_true")
    agent_demo.add_argument("--endpoint-host", action="append", default=[])
    agent_demo.add_argument(
        "--backend-mode",
        choices=["contract_test", "real"],
        default="contract_test",
    )
    agent_demo.add_argument("--model-timeout-seconds", type=float, default=30.0)
    agent_demo.add_argument("--model-max-retries", type=int, default=1)
    agent_demo.add_argument("--model-backoff-seconds", type=float, default=0.05)
    agent_demo.add_argument("--model-circuit-failure-threshold", type=int, default=2)
    agent_demo.add_argument("--model-circuit-recovery-seconds", type=float, default=5.0)
    agent_demo.add_argument("--memory-path", type=Path)
    agent_demo.add_argument(
        "--scenario",
        choices=_SCENARIO_CHOICES,
        default=_DEFAULT_SCENARIO,
        help="scenario profile for governance thresholds",
    )

    agent_eval = subparsers.add_parser(
        "agent-eval",
        help="fault-inject a saved trace to measure the local evaluator's sensitivity",
    )
    agent_eval.add_argument("--runtime-trace", type=Path, required=True)
    agent_eval.add_argument("--initial-result", type=Path, required=True)
    agent_eval.add_argument("--repaired-result", type=Path, required=True)
    agent_eval.add_argument("--output", type=Path, required=True)

    tool_fault_eval = subparsers.add_parser(
        "tool-fault-eval",
        help="inject runtime tool-response faults and verify fail-closed policy",
    )
    tool_fault_eval.add_argument("--batch-root", type=Path, required=True)
    tool_fault_eval.add_argument("--manifest", type=Path, required=True)
    tool_fault_eval.add_argument("--contract", type=Path)
    tool_fault_eval.add_argument("--output", type=Path, required=True)
    tool_fault_eval.add_argument(
        "--scenario",
        choices=_SCENARIO_CHOICES,
        default=_DEFAULT_SCENARIO,
        help="scenario profile for the deterministic Policy Judge",
    )

    network_eval = subparsers.add_parser(
        "network-resilience-eval",
        help="exercise real loopback timeout/retry/circuit/redirect behavior",
    )
    network_eval.add_argument("--output", type=Path, required=True)

    injection_eval = subparsers.add_parser(
        "prompt-injection-eval",
        help="run the fixed prompt-injection attack and benign utility sets",
    )
    injection_eval.add_argument("--output", type=Path, required=True)

    backend_eval = subparsers.add_parser(
        "backend-contract-eval",
        help="run local LongCat/VGGT/OmniVGGT connector contract fixtures",
    )
    backend_eval.add_argument("--output", type=Path, required=True)

    omni_smoke = subparsers.add_parser(
        "omni-smoke",
        help="run a path-redacted read-only smoke on an external Omni-AD-30 tree",
    )
    omni_smoke.add_argument("--root", type=Path, required=True)
    omni_smoke.add_argument("--output", type=Path, required=True)
    omni_smoke.add_argument("--source-archive-sha256", required=True)
    omni_smoke.add_argument("--per-bucket", type=int, default=2)
    omni_smoke.add_argument("--seed", type=int, default=20260813)
    omni_smoke.add_argument("--full-decode", action="store_true")

    omni_gate = subparsers.add_parser(
        "omni-gate",
        help="run external Omni-AD-30 bytes through Workers, Council, and Policy Gate",
    )
    omni_gate.add_argument("--root", type=Path, required=True)
    omni_gate.add_argument("--output", type=Path, required=True)
    omni_gate.add_argument("--source-archive-sha256", required=True)
    omni_gate.add_argument("--per-bucket", type=int, default=2)
    omni_gate.add_argument("--seed", type=int, default=20260813)
    omni_gate.add_argument(
        "--followup-tool-budget",
        type=int,
        default=3,
        help="bounded evidence follow-up budget in tool cost units (0-8)",
    )
    omni_gate.add_argument(
        "--rulepack",
        type=Path,
        help=(
            "optional fail-closed industrial rule pack; activation rejects unknown "
            "tools, thresholds, actions, predicates, or Worker capabilities"
        ),
    )

    product_run = subparsers.add_parser(
        "product-run",
        help=(
            "run the production ProductService kernel on one explicitly authorized "
            "local Omni source"
        ),
    )
    product_run.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="local Omni release directory; read in place and never copied",
    )
    product_run.add_argument(
        "--source-archive-sha256",
        required=True,
        help="explicit lowercase SHA-256 of the authorized source archive",
    )
    product_run.add_argument(
        "--purpose",
        required=True,
        help="bounded purpose for this local source authorization",
    )
    product_run.add_argument(
        "--rights-basis",
        required=True,
        help="operator-provided rights or permission basis",
    )
    product_run.add_argument(
        "--attest-authorized-use",
        action="store_true",
        required=True,
        help="explicitly attest that this local read-only use is authorized",
    )
    product_run.add_argument(
        "--product-root",
        type=Path,
        required=True,
        help="private ProductService state and immutable evidence root",
    )
    product_run.add_argument(
        "--source-display-name",
        default="Authorized local Omni source",
        help="path-free display name stored in the authorization receipt",
    )
    product_run.add_argument(
        "--goal",
        default=(
            "审核授权工业视觉数据，依据中间证据动态补证，交付可追溯裁决与整改工单。"
        ),
    )
    product_run.add_argument("--seed", type=int, default=20_260_828)

    benchmark = subparsers.add_parser(
        "architecture-benchmark",
        help="compare traditional, single-Agent, and multi-Agent paths under one protocol",
    )
    benchmark.add_argument("--output", type=Path, required=True)
    benchmark.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=[20260809, 20260810, 20260811, 20260812],
    )
    benchmark.add_argument("--repeats", type=int, default=1)
    dynamic_benchmark = subparsers.add_parser(
        "dynamic-benchmark",
        help=(
            "compare traditional, single, fixed multi-Agent, and Dynamic Leader "
            "under one labelled trigger protocol"
        ),
    )
    dynamic_benchmark.add_argument("--output", type=Path, required=True)
    dynamic_benchmark.add_argument("--repeats", type=int, default=3)
    dynamic_benchmark.add_argument("--tool-budget", type=int, default=3)
    dynamic_benchmark.add_argument("--timeout-ms", type=float, default=500.0)
    adapter_conformance = subparsers.add_parser(
        "adapter-conformance",
        help="validate one adapter manifest and observation without network access",
    )
    adapter_conformance.add_argument("--manifest", type=Path, required=True)
    adapter_conformance.add_argument("--observation", type=Path, required=True)
    adapter_conformance.add_argument("--output", type=Path, required=True)
    rulepack_verify = subparsers.add_parser(
        "rulepack-verify",
        help="validate and hash one fail-closed industrial rule pack",
    )
    rulepack_verify.add_argument("--rulepack", type=Path, required=True)
    rulepack_verify.add_argument("--output", type=Path, required=True)
    incident_evaluate = subparsers.add_parser(
        "incident-evaluate",
        help=("evaluate one hash-bound industrial incident from local read-only JSON"),
    )
    incident_evaluate.add_argument("--request", type=Path, required=True)
    incident_evaluate.add_argument("--gate-context", type=Path, required=True)
    incident_evaluate.add_argument("--output", type=Path, required=True)
    incident_audit_verify = subparsers.add_parser(
        "incident-audit-verify",
        help="independently verify one governed industrial incident case directory",
    )
    incident_audit_verify.add_argument("--case-dir", type=Path, required=True)
    return parser


def _path_payload(paths: dict[str, Path]) -> dict[str, str]:
    return {key: str(path) for key, path in sorted(paths.items())}


class _ProductRunCliError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _product_run_error(code: str, message: str) -> int:
    import sys

    print(
        json.dumps(
            {
                "schema_version": "visiondata-gate.product-run-cli-error.v1",
                "command_status": "FAILED",
                "error": {"code": code, "message": message},
                "production_release_allowed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


def _execute_product_run(args: argparse.Namespace) -> dict[str, object]:
    """Execute only the public, offline ProductService lifecycle."""

    import hashlib
    import hmac

    from .evidence import canonical_json_bytes
    from .industrial_delivery import IndustrialDeliveryReceipt
    from .product_models import (
        AuthorizeLocalSourceRequest,
        CreateProjectRequest,
        CreateTaskRequest,
        CreateUserRequest,
        CreateWorkspaceRequest,
        DataSourceKind,
        TaskExecutionStatus,
    )
    from .product_runs import ProductKernelRunReceipt
    from .product_service import ProductService

    source_root = args.source_root.expanduser().resolve(strict=True)
    if not source_root.is_dir():
        raise _ProductRunCliError(
            "INVALID_SOURCE_ROOT", "--source-root must resolve to a directory"
        )
    product_root = args.product_root.expanduser().resolve(strict=False)
    if (
        product_root == source_root
        or product_root.is_relative_to(source_root)
        or source_root.is_relative_to(product_root)
    ):
        raise _ProductRunCliError(
            "PRODUCT_ROOT_OVERLAPS_SOURCE",
            "--product-root and --source-root must be separate, non-overlapping trees",
        )
    source_archive_sha256 = args.source_archive_sha256.strip()
    if len(source_archive_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in source_archive_sha256
    ):
        raise _ProductRunCliError(
            "INVALID_SOURCE_ARCHIVE_SHA256",
            "--source-archive-sha256 must be exactly 64 lowercase hexadecimal characters",
        )
    if not args.attest_authorized_use:
        raise _ProductRunCliError(
            "AUTHORIZATION_ATTESTATION_REQUIRED",
            "--attest-authorized-use is required for a local source run",
        )

    service = ProductService(
        product_root,
        recover_interrupted=False,
        local_source_allow_roots=[source_root],
        incident_model_planner=None,
        omni_rulepack_path=None,
        hosted_agentteams=None,
    )
    try:
        actor = service.create_user(
            CreateUserRequest(display_name="VisionData Gate Product Operator")
        )
        workspace = service.create_workspace(
            CreateWorkspaceRequest(
                name="Authorized Industrial Vision Workspace",
                owner_user_id=actor.user_id,
            )
        )
        authorization = service.authorize_local_source(
            actor.user_id,
            AuthorizeLocalSourceRequest(
                workspace_id=workspace.workspace_id,
                display_name=args.source_display_name,
                root_path=str(source_root),
                source_archive_sha256=source_archive_sha256,
                purpose=args.purpose,
                rights_basis=args.rights_basis,
                operator_attests_authorized_use=True,
            ),
        )
        project = service.create_project(
            actor.user_id,
            CreateProjectRequest(
                workspace_id=workspace.workspace_id,
                name="Authorized Industrial Vision Gate",
                description=(
                    "Offline, read-only ProductService kernel execution on an "
                    "operator-authorized local source."
                ),
                source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
            ),
        )
        task = service.create_task(
            actor.user_id,
            CreateTaskRequest(
                project_id=project.project_id,
                goal=args.goal,
                seed=args.seed,
                source_kind=DataSourceKind.LOCAL_AUTHORIZED_DIRECTORY,
                source_id=authorization.source_id,
                plan_approval_required=False,
            ),
            auto_start=False,
        )
        preflight = service.task_preflight(actor.user_id, task.task_id)
        if not preflight.execution_ready:
            raise _ProductRunCliError(
                "TASK_PREFLIGHT_BLOCKED",
                f"ProductService preflight is not execution-ready: {preflight.overall_status}",
            )

        completed = service.run_task_sync(task.task_id)
        if completed.execution_status is not TaskExecutionStatus.COMPLETED:
            error_code = completed.error_code or "UNSPECIFIED_PRODUCT_KERNEL_ERROR"
            raise _ProductRunCliError(
                "TASK_EXECUTION_FAILED",
                f"ProductService task failed closed with error code {error_code}",
            )
        if not completed.evidence_sha256:
            raise _ProductRunCliError(
                "TASK_EVIDENCE_UNAVAILABLE",
                "completed ProductService task has no immutable evidence digest",
            )

        kernel_payload = service.read_evidence_zip_json(
            actor.user_id, task.task_id, "product_kernel_run_receipt.json"
        )
        kernel = ProductKernelRunReceipt.model_validate(kernel_payload)
        stable_kernel = kernel.model_dump(mode="json", exclude={"receipt_sha256"})
        expected_kernel_sha256 = hashlib.sha256(
            canonical_json_bytes(stable_kernel)
        ).hexdigest()
        if not hmac.compare_digest(expected_kernel_sha256, kernel.receipt_sha256):
            raise _ProductRunCliError(
                "KERNEL_RECEIPT_INTEGRITY_FAILED",
                "ProductKernelRun receipt digest does not match its canonical payload",
            )
        if not (
            kernel.runtime_kind == "authorized_local_readonly"
            and kernel.runtime_status.value == completed.runtime_status
            and kernel.initial_decision.value == completed.initial_decision
            and kernel.final_decision.value == completed.final_decision
        ):
            raise _ProductRunCliError(
                "KERNEL_RECEIPT_TASK_MISMATCH",
                "ProductKernelRun receipt does not match the completed task record",
            )

        delivery_payload = service.read_evidence_zip_json(
            actor.user_id, task.task_id, "industrial_delivery_receipt.json"
        )
        delivery = IndustrialDeliveryReceipt.model_validate(delivery_payload)
        if not (
            delivery.task_id == task.task_id
            and delivery.run_id == kernel.run_id
            and delivery.final_decision == completed.final_decision
            and delivery.production_human_approval_required
            and delivery.production_approval_status == "pending"
        ):
            raise _ProductRunCliError(
                "INDUSTRIAL_DELIVERY_TASK_MISMATCH",
                "industrial delivery boundary does not match the completed kernel task",
            )

        return {
            "schema_version": "visiondata-gate.product-run-cli.v1",
            "command_status": "COMPLETED_LOCAL_PRODUCT_KERNEL",
            "task_execution_status": completed.execution_status.value,
            "kernel_receipt_status": "TASK_BOUND_IN_SHA_VERIFIED_EVIDENCE",
            "tenant_user_id": actor.user_id,
            "workspace_id": workspace.workspace_id,
            "project_id": project.project_id,
            "source_id": authorization.source_id,
            "task_id": task.task_id,
            "run_id": kernel.run_id,
            "runtime_kind": kernel.runtime_kind,
            "runtime_status": kernel.runtime_status.value,
            "initial_decision": kernel.initial_decision.value,
            "final_decision": kernel.final_decision.value,
            "completion_contract": kernel.completion_contract,
            "event_count": kernel.event_count,
            "tool_call_count": kernel.tool_call_count,
            "kernel_receipt_sha256": kernel.receipt_sha256,
            "evidence_sha256": completed.evidence_sha256,
            "source_read_mode": "READ_ONLY_IN_PLACE",
            "source_assets_copied_into_product": (
                authorization.source_assets_copied_into_product
            ),
            "network_mode": "OFFLINE_NO_EXTERNAL_TRANSPORT",
            "external_model_call_count": delivery.model_call_count,
            "production_human_approval_required": (
                delivery.production_human_approval_required
            ),
            "production_approval_status": delivery.production_approval_status,
            "production_release_allowed": False,
            "claim_boundary": (
                "Local ProductKernel completion is not a PASS claim, customer "
                "acceptance, factory deployment, safety certification, or production "
                "release authorization. Gate decisions require separate human review."
            ),
        }
    finally:
        service.close(wait=True)


def _run_product_run_command(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from .product_service import ProductServiceError

    try:
        payload = _execute_product_run(args)
    except _ProductRunCliError as error:
        return _product_run_error(error.code, str(error))
    except ValidationError:
        return _product_run_error(
            "INVALID_TYPED_REQUEST",
            "product-run arguments did not satisfy the typed ProductService contract",
        )
    except ProductServiceError as error:
        return _product_run_error(type(error).__name__, str(error))
    except (OSError, RuntimeError, ValueError) as error:
        return _product_run_error(
            type(error).__name__,
            "local ProductService execution failed before a kernel receipt was delivered",
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "product-run":
        return _run_product_run_command(args)

    if args.command == "generate":
        from .generator import generate_demo_dataset

        paths = generate_demo_dataset(args.output, seed=args.seed)
        print(json.dumps(_path_payload(paths), ensure_ascii=False, indent=2))
        return 0

    if args.command == "gate":
        from .contracts import BatchContract
        from .evidence import write_canonical_json
        from .pipeline import run_gate
        from .runtime_models import ScenarioProfile

        contract: BatchContract | Path | None = args.contract
        result = run_gate(
            args.batch_root,
            args.manifest,
            contract,
            scenario_profile=ScenarioProfile(args.scenario),
        )
        write_canonical_json(args.output, result)
        print(
            json.dumps(
                {
                    "decision": result.decision.value,
                    "finding_count": len(result.findings),
                    "output": str(args.output.resolve()),
                    "run_id": result.run_id,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "geometry-gate":
        from .contracts import BatchContract, BatchManifest
        from .evidence import write_canonical_json
        from .geometry_backends import GeometryBackendConfig, run_http_geometry_backend
        from .geometry_consistency import GeometryThresholds, run_geometry_gate
        from .runtime_models import ScenarioProfile

        contract: BatchContract | Path | None = args.contract
        if args.geometry_evidence and args.geometry_endpoint:
            raise SystemExit(
                "--geometry-evidence and --geometry-endpoint are mutually exclusive"
            )
        geometry_evidence = args.geometry_evidence
        backend_connection_receipt: dict[str, object] | None = None
        backend_connection_path: Path | None = None
        if args.geometry_endpoint:
            manifest_model = BatchManifest.model_validate_json(
                args.manifest.read_bytes()
            )
            contract_model = (
                BatchContract.model_validate_json(args.contract.read_bytes())
                if args.contract
                else BatchContract()
            )
            connected = run_http_geometry_backend(
                GeometryBackendConfig(
                    backend=args.geometry_backend,
                    endpoint=args.geometry_endpoint,
                    allowed_hosts=args.geometry_endpoint_host,
                    allow_remote=args.allow_remote_geometry,
                    allow_image_upload=args.allow_geometry_image_upload,
                    execution_mode=args.geometry_backend_mode,
                    expected_checkpoint_sha256=(
                        args.geometry_expected_checkpoint_sha256
                    ),
                    timeout_seconds=args.geometry_timeout_seconds,
                ),
                args.batch_root,
                manifest_model,
                contract_model,
            )
            args.output.mkdir(parents=True, exist_ok=True)
            backend_connection_path = (
                args.output / "geometry_backend_connection_receipt.json"
            )
            write_canonical_json(backend_connection_path, connected.receipt)
            backend_connection_receipt = connected.receipt.model_dump(mode="json")
            if connected.evidence is not None:
                geometry_evidence = args.output / "geometry_backend_evidence.json"
                write_canonical_json(geometry_evidence, connected.evidence)
        run = run_geometry_gate(
            args.batch_root,
            args.manifest,
            contract,
            geometry_evidence,
            args.output,
            thresholds=GeometryThresholds(
                max_reprojection_error_px=args.max_reprojection_error_px,
            ),
            required=not args.optional,
            scenario_profile=ScenarioProfile(args.scenario),
            backend_connection_receipt=backend_connection_receipt,
        )
        print(
            json.dumps(
                {
                    "status": run.geometry.status,
                    "decision": run.gate_result.decision.value,
                    "finding_count": len(run.gate_result.findings),
                    "geometry_finding_count": len(run.geometry.findings),
                    "gate_result": str(
                        (run.output_root / "gate_result.json").resolve()
                    ),
                    "receipt": str(run.receipt_path),
                    "receipt_sha256": run.receipt_sha256,
                    "dynamic_geometry_plan": str(run.followup_plan_path),
                    "backend_connection_receipt": (
                        str(backend_connection_path)
                        if backend_connection_path is not None
                        else None
                    ),
                    "backend_connection_status": (
                        backend_connection_receipt.get("status")
                        if backend_connection_receipt is not None
                        else "REAL_BACKEND_NOT_CONNECTED"
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "demo":
        from .pipeline import run_full_demo
        from .runtime_models import ScenarioProfile

        run = run_full_demo(
            args.output,
            seed=args.seed,
            scenario_profile=ScenarioProfile(args.scenario),
        )
        payload = {
            "initial_decision": run.initial_result.decision.value,
            "initial_findings": len(run.initial_result.findings),
            "repaired_decision": run.repaired_result.decision.value,
            "repaired_findings": len(run.repaired_result.findings),
            "precision": run.evaluation.precision,
            "recall": run.evaluation.recall,
            "f1": run.evaluation.f1,
            "post_repair_correct_pass": run.evaluation.post_repair_correct_pass,
            "summary": str(run.summary_path),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if run.evaluation.post_repair_correct_pass else 2

    if args.command == "agent-demo":
        from .agent_runtime import run_agentic_demo
        from .runtime_models import ModelBackendKind, RuntimeConfig, ScenarioProfile

        config = RuntimeConfig(
            backend=ModelBackendKind(args.backend),
            model=args.model,
            endpoint=args.endpoint,
            allow_remote_model=args.allow_remote_model,
            remote_endpoint_hosts=args.endpoint_host,
            backend_execution_mode=args.backend_mode,
            model_timeout_seconds=args.model_timeout_seconds,
            model_max_retries=args.model_max_retries,
            model_backoff_seconds=args.model_backoff_seconds,
            model_circuit_failure_threshold=args.model_circuit_failure_threshold,
            model_circuit_recovery_seconds=args.model_circuit_recovery_seconds,
            scenario_profile=ScenarioProfile(args.scenario),
        )
        run = run_agentic_demo(
            args.output,
            seed=args.seed,
            goal=args.goal,
            config=config,
            memory_path=args.memory_path,
            api_key=os.environ.get("VISIONDATA_LLM_API_KEY"),
        )
        payload = {
            "runtime_status": run.runtime_trace.status.value,
            "runtime_id": run.runtime_trace.run_id,
            "backend": run.runtime_trace.backend,
            "events": len(run.runtime_trace.events),
            "tool_calls": run.runtime_trace.tool_call_count,
            "model_calls": run.runtime_trace.model_call_count,
            "initial_decision": run.initial_result.decision.value,
            "repaired_decision": run.repaired_result.decision.value,
            "runtime_trace": str(run.runtime_trace_path),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if run.evaluation.post_repair_correct_pass else 2

    if args.command == "agent-eval":
        from .agent_evaluation import build_agent_evaluation_receipt
        from .contracts import GateResult
        from .evidence import write_canonical_json
        from .runtime_models import RuntimeTrace

        trace = RuntimeTrace.model_validate_json(args.runtime_trace.read_bytes())
        initial = GateResult.model_validate_json(args.initial_result.read_bytes())
        repaired = GateResult.model_validate_json(args.repaired_result.read_bytes())
        receipt = build_agent_evaluation_receipt(trace, initial, repaired)
        receipt_sha256 = write_canonical_json(args.output, receipt)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "detected_count": receipt["summary"]["detected_count"],
                    "intervention_count": receipt["summary"]["intervention_count"],
                    "detection_rate": receipt["summary"]["detection_rate"],
                    "valid_variant_false_positive_count": receipt["summary"][
                        "valid_variant_false_positive_count"
                    ],
                    "output": str(args.output.resolve()),
                    "output_sha256": receipt_sha256,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if receipt["status"] == "PASS_LOCAL" else 2

    if args.command == "tool-fault-eval":
        from .contracts import BatchContract, BatchManifest
        from .evidence import write_canonical_json
        from .runtime_models import ScenarioProfile
        from .tool_fault_evaluation import build_tool_fault_evaluation_receipt

        manifest = BatchManifest.model_validate_json(args.manifest.read_bytes())
        contract = (
            BatchContract.model_validate_json(args.contract.read_bytes())
            if args.contract
            else BatchContract()
        )
        scenario = ScenarioProfile(args.scenario)
        receipt = build_tool_fault_evaluation_receipt(
            str(args.batch_root.resolve()),
            manifest,
            contract,
            scenario_profile=scenario,
            include_optional=scenario is not ScenarioProfile.GENERIC,
        )
        receipt_sha256 = write_canonical_json(args.output, receipt)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "detected_count": receipt["summary"]["detected_count"],
                    "intervention_count": receipt["summary"]["intervention_count"],
                    "typed_error_trace_count": receipt["summary"][
                        "typed_error_trace_count"
                    ],
                    "policy_defer_count": receipt["summary"]["policy_defer_count"],
                    "output": str(args.output.resolve()),
                    "output_sha256": receipt_sha256,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if receipt["status"] == "PASS_LOCAL" else 2

    if args.command == "network-resilience-eval":
        from .evidence import write_canonical_json
        from .network_resilience_evaluation import (
            build_network_resilience_evaluation_receipt,
        )

        receipt = build_network_resilience_evaluation_receipt()
        receipt_sha256 = write_canonical_json(args.output, receipt)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "fixed_denominator": receipt["fixed_denominator"],
                    "passed_count": receipt["passed_count"],
                    "output": str(args.output.resolve()),
                    "output_sha256": receipt_sha256,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if receipt["status"] == "PASS_LOCAL" else 2

    if args.command == "prompt-injection-eval":
        from .evidence import write_canonical_json
        from .prompt_injection_evaluation import (
            build_prompt_injection_evaluation_receipt,
        )

        receipt = build_prompt_injection_evaluation_receipt()
        receipt_sha256 = write_canonical_json(args.output, receipt)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "attack_denominator": receipt["attack"]["fixed_denominator"],
                    "blocked_count": receipt["attack"]["blocked_count"],
                    "benign_denominator": receipt["benign_utility"][
                        "fixed_denominator"
                    ],
                    "benign_allowed_count": receipt["benign_utility"]["allowed_count"],
                    "output": str(args.output.resolve()),
                    "output_sha256": receipt_sha256,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if receipt["status"] == "PASS_LOCAL_FIXED_ATTACK_SET" else 2

    if args.command == "backend-contract-eval":
        from .backend_contract_evaluation import (
            build_backend_contract_evaluation_receipt,
        )
        from .evidence import write_canonical_json

        receipt = build_backend_contract_evaluation_receipt()
        receipt_sha256 = write_canonical_json(args.output, receipt)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "fixed_denominator": receipt["fixed_denominator"],
                    "contract_connected_count": receipt["contract_connected_count"],
                    "real_backend_status": receipt["real_backend_status"],
                    "output": str(args.output.resolve()),
                    "output_sha256": receipt_sha256,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if receipt["status"] == "PASS_LOCAL_CONTRACTS_ONLY" else 2

    if args.command == "omni-smoke":
        from .omni_adapter import run_omni_readonly_smoke

        run = run_omni_readonly_smoke(
            args.root,
            args.output,
            source_archive_sha256=args.source_archive_sha256,
            per_bucket=args.per_bucket,
            seed=args.seed,
            full_decode=args.full_decode,
        )
        print(
            json.dumps(
                {
                    "completion_state": run.summary["completion_state"],
                    "release_decision": run.summary["release_decision"],
                    "selected_image_count": run.summary["scope"][
                        "selected_image_count"
                    ],
                    "report": str(run.summary_path),
                    "report_sha256": run.summary_sha256,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "omni-gate":
        from .omni_adapter import run_omni_readonly_gate

        run = run_omni_readonly_gate(
            args.root,
            args.output,
            source_archive_sha256=args.source_archive_sha256,
            per_bucket=args.per_bucket,
            seed=args.seed,
            followup_tool_budget=args.followup_tool_budget,
            rulepack_path=args.rulepack,
        )
        print(
            json.dumps(
                {
                    "completion_state": "REAL_DATA_GATE_COMPLETED",
                    "decision": run.gate_result.decision.value,
                    "run_id": run.gate_result.run_id,
                    "finding_count": len(run.gate_result.findings),
                    "work_order_count": len(run.gate_result.work_orders),
                    "gate_result": str(run.gate_result_path),
                    "gate_result_sha256": run.gate_result_sha256,
                    "receipt": str(run.receipt_path),
                    "receipt_sha256": run.receipt_sha256,
                    "dynamic_leader_plan": str(run.leader_plan_path),
                    "dynamic_leader_plan_sha256": run.leader_plan_sha256,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "architecture-benchmark":
        from .architecture_benchmark import run_architecture_benchmark

        run = run_architecture_benchmark(
            args.output,
            seeds=args.seeds,
            repeats=args.repeats,
        )
        print(
            json.dumps(
                {
                    "status": run.report["status"],
                    "report": str(run.report_path),
                    "report_sha256": run.report_sha256,
                    "summaries": run.report["summaries"],
                    "multi_agent_vs_traditional": run.report[
                        "multi_agent_vs_traditional"
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "dynamic-benchmark":
        from .dynamic_benchmark import run_dynamic_benchmark

        run = run_dynamic_benchmark(
            args.output,
            repeats=args.repeats,
            tool_budget=args.tool_budget,
            timeout_ms=args.timeout_ms,
        )
        print(
            json.dumps(
                {
                    "status": run.report["status"],
                    "report": str(run.report_path),
                    "report_sha256": run.report_sha256,
                    "fixed_denominators": run.report["fixed_denominators"],
                    "summaries": run.report["summaries"],
                    "comparisons": run.report["comparisons"],
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "adapter-conformance":
        from .adapter_sdk import verify_adapter_conformance

        receipt = verify_adapter_conformance(
            args.manifest, args.observation, output=args.output
        )
        print(json.dumps(receipt, ensure_ascii=False))
        return 0 if receipt["status"] == "PASS" else 2

    if args.command == "rulepack-verify":
        from .rulepack import verify_rule_pack

        receipt = verify_rule_pack(args.rulepack, output=args.output)
        print(receipt.model_dump_json())
        return 0

    if args.command == "incident-evaluate":
        from .evidence import write_canonical_json
        from .incident_model_planner import incident_model_planner_from_environment
        from .industrial_incident import (
            IndustrialGateContext,
            build_industrial_incident_case,
            parse_industrial_incident_request_json,
        )

        request = parse_industrial_incident_request_json(args.request.read_bytes())
        gate_context = IndustrialGateContext.model_validate_json(
            args.gate_context.read_bytes()
        )
        case = build_industrial_incident_case(
            request,
            gate_context,
            model_planner=incident_model_planner_from_environment(),
        )
        case_sha256 = write_canonical_json(args.output, case)
        print(
            json.dumps(
                {
                    "execution_status": "COMPLETED_LOCAL_READ_ONLY_EVALUATION",
                    "case_id": case.case_id,
                    "case_version": case.case_version,
                    "status": case.status.value,
                    "recommendation": case.recommendation.value,
                    "root_cause_status": case.root_cause_status,
                    "production_release_allowed": case.production_release_allowed,
                    "model_planner_mode": (
                        case.model_planner_receipt.mode.value
                        if case.model_planner_receipt is not None
                        else "off"
                    ),
                    "model_connection_status": (
                        case.model_planner_receipt.connection_status
                        if case.model_planner_receipt is not None
                        else "REAL_BACKEND_NOT_CONNECTED"
                    ),
                    "external_model_call_count": case.external_model_call_count,
                    "output": str(args.output.resolve()),
                    "output_sha256": case_sha256,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "incident-audit-verify":
        from .audit_envelope import verify_governed_audit_case_directory

        try:
            envelope = verify_governed_audit_case_directory(args.case_dir)
        except (OSError, ValueError) as error:
            print(
                json.dumps(
                    {
                        "verification_status": "FAIL",
                        "case_directory": str(args.case_dir.resolve(strict=False)),
                        "error": str(error),
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        print(
            json.dumps(
                {
                    "verification_status": "PASS",
                    "case_id": envelope.subject.case_id,
                    "legacy_case_sha256": envelope.subject.legacy_case_sha256,
                    "case_audit_sha256": envelope.subject.audit_digest.value,
                    "audit_root_sha256": envelope.audit_root.value,
                    "canonical_payloads": "PASS",
                    "event_chain": "PASS",
                    "parent_child_binding": (
                        "PASS"
                        if envelope.lineage.transition_type == "CHILD_CASE_CREATED"
                        else "NOT_APPLICABLE"
                    ),
                    "worker_receipts": "PASS",
                    "governance_bindings": "PASS",
                    "signature": envelope.signature.status,
                },
                ensure_ascii=False,
            )
        )
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

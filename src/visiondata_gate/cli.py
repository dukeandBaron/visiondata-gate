"""Command-line interface for the complete VisionData Gate demo."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .agent_runtime import run_agentic_demo
from .architecture_benchmark import run_architecture_benchmark
from .contracts import BatchContract
from .evidence import write_canonical_json
from .generator import generate_demo_dataset
from .omni_adapter import run_omni_readonly_gate, run_omni_readonly_smoke
from .pipeline import run_full_demo, run_gate
from .runtime_models import ModelBackendKind, RuntimeConfig, ScenarioProfile


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
        choices=[item.value for item in ScenarioProfile],
        default=ScenarioProfile.GENERIC.value,
        help="scenario profile for governance thresholds",
    )

    demo = subparsers.add_parser("demo", help="run generate-to-repair closed loop")
    demo.add_argument("--output", type=Path, required=True)
    demo.add_argument("--seed", type=int, default=20260809)
    demo.add_argument(
        "--scenario",
        choices=[item.value for item in ScenarioProfile],
        default=ScenarioProfile.GENERIC.value,
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
        choices=[item.value for item in ModelBackendKind],
        default=ModelBackendKind.DETERMINISTIC.value,
    )
    agent_demo.add_argument("--model", default="local-evidence-reasoner-v2")
    agent_demo.add_argument("--endpoint")
    agent_demo.add_argument("--allow-remote-model", action="store_true")
    agent_demo.add_argument("--memory-path", type=Path)
    agent_demo.add_argument(
        "--scenario",
        choices=[item.value for item in ScenarioProfile],
        default=ScenarioProfile.GENERIC.value,
        help="scenario profile for governance thresholds",
    )

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
    return parser


def _path_payload(paths: dict[str, Path]) -> dict[str, str]:
    return {key: str(path) for key, path in sorted(paths.items())}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "generate":
        paths = generate_demo_dataset(args.output, seed=args.seed)
        print(json.dumps(_path_payload(paths), ensure_ascii=False, indent=2))
        return 0

    if args.command == "gate":
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

    if args.command == "demo":
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
        config = RuntimeConfig(
            backend=ModelBackendKind(args.backend),
            model=args.model,
            endpoint=args.endpoint,
            allow_remote_model=args.allow_remote_model,
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

    if args.command == "omni-smoke":
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
        run = run_omni_readonly_gate(
            args.root,
            args.output,
            source_archive_sha256=args.source_archive_sha256,
            per_bucket=args.per_bucket,
            seed=args.seed,
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

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

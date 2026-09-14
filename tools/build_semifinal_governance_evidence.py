"""Build hash-sealed GOAI semifinal governance-effectiveness evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from visiondata_gate.governance_effectiveness_v2 import (
    build_omni_rc3_governance_effectiveness_report,
    build_paired_comparison_from_dynamic_benchmark,
    verify_governance_effectiveness_v2_report,
    verify_paired_strategy_comparison_v2_report,
    write_governance_v2_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build per-unit private-shadow metrics and/or a same-input "
            "Dynamic-vs-Fixed comparison."
        )
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--evaluated-at")
    parser.add_argument("--dynamic-benchmark")
    parser.add_argument("--product-pilot-receipt")
    parser.add_argument("--capa-pilot-receipt")
    parser.add_argument("--expected-product-receipt-sha256")
    parser.add_argument("--expected-capa-receipt-sha256")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evaluated_at = args.evaluated_at or datetime.now(timezone.utc).isoformat()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, dict[str, str]] = {}

    if args.dynamic_benchmark:
        rule_comparison = build_paired_comparison_from_dynamic_benchmark(
            args.dynamic_benchmark,
            evaluated_at=evaluated_at,
            baseline_architecture="traditional_pipeline",
        )
        verify_paired_strategy_comparison_v2_report(rule_comparison)
        rule_path = write_governance_v2_report(
            output_dir / "dynamic_vs_fixed_rule_paired_comparison.json",
            rule_comparison,
        )
        outputs["dynamic_vs_fixed_rule"] = {
            "path": str(rule_path),
            "report_sha256": rule_comparison.report_sha256,
            "verdict": rule_comparison.complex_conflict_verdict,
        }
        exhaustive_comparison = build_paired_comparison_from_dynamic_benchmark(
            args.dynamic_benchmark,
            evaluated_at=evaluated_at,
            baseline_architecture="fixed_multi_agent",
        )
        verify_paired_strategy_comparison_v2_report(exhaustive_comparison)
        exhaustive_path = write_governance_v2_report(
            output_dir / "dynamic_vs_fixed_exhaustive_paired_comparison.json",
            exhaustive_comparison,
        )
        outputs["dynamic_vs_fixed_exhaustive"] = {
            "path": str(exhaustive_path),
            "report_sha256": exhaustive_comparison.report_sha256,
            "verdict": exhaustive_comparison.complex_conflict_verdict,
        }

    omni_values = (
        args.product_pilot_receipt,
        args.capa_pilot_receipt,
        args.expected_product_receipt_sha256,
        args.expected_capa_receipt_sha256,
    )
    if any(omni_values) and not all(omni_values):
        raise SystemExit(
            "Omni evidence requires product receipt, CAPA receipt, and both expected SHA-256 values."
        )
    if all(omni_values):
        omni = build_omni_rc3_governance_effectiveness_report(
            product_pilot_receipt_path=args.product_pilot_receipt,
            capa_pilot_receipt_path=args.capa_pilot_receipt,
            expected_product_receipt_sha256=args.expected_product_receipt_sha256,
            expected_capa_receipt_sha256=args.expected_capa_receipt_sha256,
            evaluated_at=evaluated_at,
        )
        verify_governance_effectiveness_v2_report(omni)
        path = write_governance_v2_report(
            output_dir / "omni_private_shadow_governance_effectiveness.json",
            omni,
        )
        outputs["omni_private_shadow"] = {
            "path": str(path),
            "report_sha256": omni.report_sha256,
            "measurement_status": omni.measurement_status,
        }

    if not outputs:
        raise SystemExit("No evidence source was selected.")
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

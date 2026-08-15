"""Validate the static reviewer website against frozen release evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ROOT = PROJECT_ROOT / "evidence" / "submission" / "vdg-20260816-rc1"
SITE_DATA = PROJECT_ROOT / "website" / "data" / "site-data.json"
SITE_INDEX = PROJECT_ROOT / "website" / "index.html"


class WebsiteValidationError(RuntimeError):
    """Raised when the reviewer site drifts from release evidence."""


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WebsiteValidationError(message)


def validate_website_data() -> dict[str, Any]:
    site = _load(SITE_DATA)
    receipt = _load(RELEASE_ROOT / "scenario_delivery_receipt.json")
    manifest = _load(RELEASE_ROOT / "release_manifest.json")
    gate = _load(RELEASE_ROOT / "omni_gate_result.json")
    benchmark = _load(RELEASE_ROOT / "architecture_benchmark.json")
    html = SITE_INDEX.read_text(encoding="utf-8")

    _require(site["release_id"] == receipt["release_id"], "release id drift")
    expected_receipt_sha = manifest["artifacts"]["scenario_delivery_receipt"]["sha256"]
    _require(
        site["receipt_sha256"] == expected_receipt_sha,
        "scenario receipt digest drift",
    )

    observed = receipt["observed_pilot"]
    for key in (
        "decision",
        "fixed_image_denominator",
        "replan_count",
        "dynamic_worker_count",
        "finding_count",
        "work_order_count",
        "rule_check_count",
        "failed_rule_check_count",
    ):
        _require(site["pilot"][key] == observed[key], f"pilot field drift: {key}")

    receipt_triggers = {item["task_id"]: item for item in observed["dynamic_triggers"]}
    site_triggers = {item["task_id"]: item for item in site["dynamic_triggers"]}
    _require(
        site_triggers.keys() == receipt_triggers.keys(), "dynamic trigger set drift"
    )
    for task_id, expected in receipt_triggers.items():
        actual = site_triggers[task_id]
        for site_key, receipt_key in (
            ("signal", "signal"),
            ("observed_value", "observed_value"),
            ("unit", "unit"),
            ("action", "dynamic_action"),
        ):
            _require(
                actual[site_key] == expected[receipt_key],
                f"dynamic trigger drift: {task_id}/{site_key}",
            )

    gate_rules = {item["check_id"]: item["status"] for item in gate["rule_checks"]}
    site_rules = {item["id"]: item["status"] for item in site["rule_checks"]}
    _require(site_rules == gate_rules, "rule check ids or status drift")

    summaries = benchmark["summaries"]
    architecture = site["architecture_control"]
    _require(
        architecture["record_count"] == len(benchmark["records"]),
        "architecture record count drift",
    )
    _require(
        architecture["fixed_sop_multi_agent_necessity_supported"]
        == benchmark["multi_agent_vs_traditional"][
            "fixed_sop_multi_agent_necessity_supported"
        ],
        "architecture conclusion drift",
    )
    for name in architecture["architectures"]:
        _require(name in summaries, f"missing architecture summary: {name}")
        _require(
            round(summaries[name]["mean_f1"], 2) == architecture["f1"],
            f"F1 drift: {name}",
        )
        _require(
            summaries[name]["error_release_rate"]
            == architecture["unsafe_release_rate"],
            f"unsafe release rate drift: {name}",
        )

    prohibited_phrases = (
        "客户已验收",
        "工厂已上线",
        "生产级已部署",
        "AgentTeams 已接入",
        "全量 Omni 已认证",
    )
    for phrase in prohibited_phrases:
        _require(phrase not in html, f"unsupported public claim in website: {phrase}")

    required_copy = (
        "Omni-180-v1",
        "RECAPTURE",
        "45 findings → 45 工单",
        "评委网站展示固定公开运行，不冒充生产 SaaS",
        "v0.1.0-goai-rc1",
        "downloads/SHA256SUMS.txt",
    )
    for phrase in required_copy:
        _require(phrase in html, f"required reviewer copy missing: {phrase}")

    return {
        "status": "PASS",
        "release_id": site["release_id"],
        "receipt_sha256": site["receipt_sha256"],
        "pilot_denominator": site["pilot"]["fixed_image_denominator"],
        "dynamic_trigger_count": len(site_triggers),
        "rule_check_count": len(site_rules),
        "architecture_record_count": architecture["record_count"],
    }


def main() -> int:
    print(json.dumps(validate_website_data(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

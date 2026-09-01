"""Read-only worktree inventory for the private VisionData Gate RC3 branch.

The command never stages, deletes, formats, or rewrites files.  It separates
current engineering work from frozen historical evidence and local generated
outputs so a dirty worktree is understandable before a release candidate is
assembled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


FROZEN_PREFIXES = ("07_results/", "deliverables/", "evidence/", "release/")
PRIVATE_PREFIXES = ("output/", "tmp/", ".streamlit/secrets.toml")
EXPERIMENTAL_MARKERS = (
    "agentteams",
    "longcat",
    "geometry",
    "vggt",
    "model_backends",
)

CURRENT_CLAIM_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "README.md": ("_05", "_06", "NOT_ESTIMABLE", "DynamicBench-v1"),
    "docs/00_OVERVIEW.md": ("_05", "_06", "NOT_ESTIMABLE", "DynamicBench-v1"),
    "docs/CLAIM_SCOPE.md": (
        "_05",
        "_06",
        "NOT_ESTIMABLE",
        "DynamicBench-v1",
        "实际模型调用",
    ),
    "docs/REVIEWER_READINESS_MATRIX.md": (
        "_05",
        "_06",
        "NOT_ESTIMABLE",
        "DynamicBench-v1",
    ),
    "docs/GOAI_requirements_matrix.md": (
        "_05",
        "_06",
        "NOT_ESTIMABLE",
        "DynamicBench-v1",
        "实际外部模型调用",
    ),
    "docs/DATA_SOURCE_AND_COMPLIANCE_SEMIFINAL_RC3.md": (
        "_05",
        "_06",
        "NOT_ESTIMABLE",
        "实际外部模型调用",
    ),
    "docs/one_pager.md": ("_05", "_06", "NOT_ESTIMABLE", "DynamicBench-v1"),
    "docs/submission_form_copy.md": (
        "_05",
        "_06",
        "NOT_ESTIMABLE",
        "DynamicBench-v1",
    ),
    "01_planner/PROGRESS_BOARD.md": (
        "_05",
        "_06",
        "NOT_ESTIMABLE",
        "DynamicBench-v1",
    ),
    "01_planner/PROJECT_SPEC.md": (
        "_05",
        "_06",
        "NOT_ESTIMABLE",
        "DynamicBench-v1",
    ),
}

STALE_CURRENT_CLAIM_PATTERNS: dict[str, re.Pattern[str]] = {
    "all_plans_unexecuted": re.compile(r"(?:所有|三套)方案[^\n]{0,40}(?:都)?尚未执行"),
    "current_full_regression_overclaimed": re.compile(
        r"当前(?:开发树|工作树)[^\n]{0,60}全量[^\n]{0,30}(?:已通过|通过)"
    ),
    "public_demo_overclaimed": re.compile(r"当前可确认[^\n]{0,80}公开评委站点"),
    "nonzero_actual_model_calls": re.compile(
        r"实际(?:外部)?模型调用(?:为|、Token[^\n]{0,20}均为)\s*[1-9][0-9]*"
    ),
}

LOCAL_EVIDENCE_HASHES: dict[str, str] = {
    "output/goai_rc3_omni_capa_20260825_05/authorized_capa_pilot_receipt.json": (
        "eaf897f91bb092c4dcb7a22a3ffb0dec0982217d4c084d01855ca8eac27b52b1"
    ),
    "output/goai_rc3_capa_assessment_20260825_06/capa_outcome_assessment.json": (
        "35326a027591cd7eb0ea43470b8c50d1d3161ff654ea2f1cf4b9a4d892f00c63"
    ),
    "output/goai_rc3_dynamic_bench_20260825/dynamic_benchmark.json": (
        "2623cb1c11738a35a052f8edb45488be85c1b2698d99bf907c2871305117ff8b"
    ),
    "rulepacks/industrial-v1.json": (
        "dcf05a1ccdb7053c9ab7a11eb78f20d3087a79ef046198fe42018a785523a70b"
    ),
    "output/goai_rc3_reuse_20260825_02/adapter_conformance_receipt.json": (
        "cae357945a2f2bbc73b83be9be0a094e3d9904edf9b35d5f4a5820ee05e96cec"
    ),
}

LOCAL_EVIDENCE_EMBEDDED_HASHES: dict[str, tuple[str, str]] = {
    "output/goai_rc3_capa_assessment_20260825_06/capa_outcome_assessment.json": (
        "assessment_sha256",
        "18c2ad68b160c716792aeb64811f438488e24d5570648f1d3a6a8fbd8a2f0485",
    ),
    "output/goai_rc3_reuse_20260825_02/adapter_conformance_receipt.json": (
        "receipt_sha256",
        "92848901e1ac46f3ffd22e0e2398571273d8b313a8f54dc2617e3c8abbe5a16e",
    ),
}

LOCAL_EVIDENCE_SEMANTICS: dict[str, dict[str, Any]] = {
    "output/goai_rc3_omni_capa_20260825_05/authorized_capa_pilot_receipt.json": {
        "parent_finding_count": 49,
        "child_finding_count": 33,
        "derived_image_count": 180,
        "derived_mask_count": 60,
        "verified_closed_work_order_count": 6,
        "remaining_work_order_count": 43,
        "recovery_status": "TRANSFERRED_TO_INVESTIGATION",
        "recovery_success": False,
        "actual_model_call_count": 0,
        "production_release_allowed": False,
    },
    "output/goai_rc3_capa_assessment_20260825_06/capa_outcome_assessment.json": {
        "release_feasibility_status": (
            "NO_FEASIBLE_RELEASE_OBSERVED_IN_CURRENT_AUTHORIZED_POOL"
        ),
        "minimum_observed_relative_effort_points": None,
        "observed_release_candidate_found": False,
    },
    "output/goai_rc3_dynamic_bench_20260825/dynamic_benchmark.json": {
        "actual_model_call_count": 0,
        "actual_model_token_count": 0,
        "provider_billed_api_cost_cny": 0.0,
        "summaries.dynamic_leader.dynamic_trigger_precision": 1.0,
        "summaries.dynamic_leader.dynamic_trigger_recall": 1.0,
        "summaries.fixed_multi_agent.redundant_or_duplicate_tool_call_count": 57,
        "comparisons.single_agent_and_dynamic_leader_quality_tied": True,
        "comparisons.dynamic_leader_p95_latency_below_single_agent_observed": False,
    },
    "output/goai_rc3_reuse_20260825_02/adapter_conformance_receipt.json": {
        "status": "PASS",
        "actual_model_call_count": 0,
        "network_probe_performed": False,
    },
}


def _git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def _status_entries(root: Path) -> list[dict[str, str]]:
    fields = _git(root, "status", "--porcelain=v1", "-z").split(b"\0")
    entries: list[dict[str, str]] = []
    index = 0
    while index < len(fields):
        raw = fields[index]
        index += 1
        if not raw:
            continue
        decoded = raw.decode("utf-8", errors="strict")
        status = decoded[:2]
        path = decoded[3:].replace("\\", "/")
        entry = {"status": status, "path": path}
        if "R" in status or "C" in status:
            if index >= len(fields) or not fields[index]:
                raise RuntimeError("git status rename record is incomplete")
            entry["source_path"] = fields[index].decode("utf-8").replace("\\", "/")
            index += 1
        entries.append(entry)
    return entries


def _namespace(path: str) -> str:
    lowered = path.casefold()
    if path.startswith(FROZEN_PREFIXES):
        return "FROZEN_HISTORY"
    if path.startswith(PRIVATE_PREFIXES):
        return "PRIVATE_LOCAL_NOT_FOR_GIT"
    if path.startswith("website/"):
        return "PRIVATE_UI_PENDING_PUBLICATION_GATE"
    if any(marker in lowered for marker in EXPERIMENTAL_MARKERS):
        return "EXPERIMENTAL_NOT_CONNECTED"
    if path == "app.py" or path.startswith(("src/", "tests/", "tools/")):
        return "CURRENT_ENGINEERING"
    if path == "README.md" or path.startswith(("01_planner/", "docs/", "10_reports/")):
        return "CURRENT_CLAIMS_AND_QA"
    return "REPOSITORY_SUPPORT"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nested_value(payload: Any, dotted_key: str) -> Any:
    value = payload
    for key in dotted_key.split("."):
        if not isinstance(value, dict) or key not in value:
            raise KeyError(dotted_key)
        value = value[key]
    return value


def _audit_current_claims(
    root: Path, *, require_local_evidence: bool
) -> dict[str, Any]:
    missing_requirements: list[dict[str, Any]] = []
    stale_claim_hits: list[dict[str, Any]] = []
    for relative, required_tokens in CURRENT_CLAIM_REQUIREMENTS.items():
        path = root / relative
        if not path.is_file():
            missing_requirements.append(
                {"path": relative, "missing_tokens": list(required_tokens)}
            )
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            missing_requirements.append({"path": relative, "missing_tokens": missing})
        for pattern_id, pattern in STALE_CURRENT_CLAIM_PATTERNS.items():
            for match in pattern.finditer(text):
                stale_claim_hits.append(
                    {
                        "path": relative,
                        "pattern_id": pattern_id,
                        "line": text.count("\n", 0, match.start()) + 1,
                        "excerpt": match.group(0),
                    }
                )

    evidence_checks: list[dict[str, Any]] = []
    evidence_failures: list[dict[str, Any]] = []
    for relative, expected in LOCAL_EVIDENCE_HASHES.items():
        path = root / relative
        if not path.is_file():
            check = {
                "path": relative,
                "status": "MISSING_LOCAL_EVIDENCE",
                "expected_sha256": expected,
            }
            evidence_checks.append(check)
            if require_local_evidence:
                evidence_failures.append(check)
            continue
        observed = _sha256(path)
        check = {
            "path": relative,
            "status": "PASS" if observed == expected else "SHA256_MISMATCH",
            "expected_sha256": expected,
            "observed_sha256": observed,
        }
        evidence_checks.append(check)
        if observed != expected:
            evidence_failures.append(check)
            continue
        payload: dict[str, Any] | None = None
        embedded = LOCAL_EVIDENCE_EMBEDDED_HASHES.get(relative)
        if embedded is not None:
            field, embedded_expected = embedded
            payload = json.loads(path.read_text(encoding="utf-8"))
            embedded_observed = payload.get(field)
            check["embedded_field"] = field
            check["embedded_expected"] = embedded_expected
            check["embedded_observed"] = embedded_observed
            if embedded_observed != embedded_expected:
                check["status"] = "EMBEDDED_SHA256_MISMATCH"
                evidence_failures.append(check)
        expected_semantics = LOCAL_EVIDENCE_SEMANTICS.get(relative)
        if expected_semantics is not None:
            if payload is None:
                payload = json.loads(path.read_text(encoding="utf-8"))
            semantic_mismatches: list[dict[str, Any]] = []
            for dotted_key, semantic_expected in expected_semantics.items():
                try:
                    semantic_observed = _nested_value(payload, dotted_key)
                except KeyError:
                    semantic_observed = "MISSING_FIELD"
                if semantic_observed != semantic_expected:
                    semantic_mismatches.append(
                        {
                            "field": dotted_key,
                            "expected": semantic_expected,
                            "observed": semantic_observed,
                        }
                    )
            check["semantic_status"] = (
                "PASS" if not semantic_mismatches else "SEMANTIC_MISMATCH"
            )
            check["semantic_mismatches"] = semantic_mismatches
            if semantic_mismatches:
                check["status"] = "SEMANTIC_MISMATCH"
                evidence_failures.append(check)

    passed = not missing_requirements and not stale_claim_hits and not evidence_failures
    return {
        "status": "PASS" if passed else "FAIL",
        "current_claim_file_count": len(CURRENT_CLAIM_REQUIREMENTS),
        "missing_requirements": missing_requirements,
        "stale_claim_hits": stale_claim_hits,
        "local_evidence_checks": evidence_checks,
        "local_evidence_required": require_local_evidence,
    }


def build_inventory(
    root: Path, *, require_local_evidence: bool = False
) -> dict[str, Any]:
    entries = _status_entries(root)
    grouped: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        grouped.setdefault(_namespace(entry["path"]), []).append(entry)
    for values in grouped.values():
        values.sort(key=lambda item: item["path"])

    generated: dict[str, Any] = {}
    for name in ("output", "tmp"):
        directory = root / name
        if directory.is_dir():
            children = sorted(item.name for item in directory.iterdir())
            generated[name] = {
                "child_count": len(children),
                "children": children,
                "tracked": bool(_git(root, "ls-files", "--", name).strip()),
            }

    frozen_drift = grouped.get("FROZEN_HISTORY", [])
    claim_consistency = _audit_current_claims(
        root, require_local_evidence=require_local_evidence
    )
    return {
        "schema_version": "visiondata-gate.worktree-namespace-audit.v1",
        "branch": _git(root, "branch", "--show-current").decode("utf-8").strip(),
        "dirty_entry_count": len(entries),
        "namespaces": grouped,
        "local_generated_roots": generated,
        "frozen_history_modified": bool(frozen_drift),
        "claim_consistency": claim_consistency,
        "release_candidate_ready": not entries
        and claim_consistency["status"] == "PASS",
        "policy": {
            "destructive_cleanup_performed": False,
            "historical_evidence_may_be_deleted": False,
            "full_test_required_during_feature_work": False,
            "full_test_required_before_final_freeze": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print canonical JSON")
    parser.add_argument(
        "--require-local-evidence",
        action="store_true",
        help="fail when the private RC3 receipt files are unavailable",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    inventory = build_inventory(
        root, require_local_evidence=args.require_local_evidence
    )
    if args.json:
        print(json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"branch: {inventory['branch']}")
        print(f"dirty entries: {inventory['dirty_entry_count']}")
        for namespace, entries in sorted(inventory["namespaces"].items()):
            print(f"{namespace}: {len(entries)}")
        print(
            "frozen history modified: "
            + ("YES" if inventory["frozen_history_modified"] else "NO")
        )
        print(
            "release candidate ready: "
            + ("YES" if inventory["release_candidate_ready"] else "NO")
        )
        print(f"claim consistency: {inventory['claim_consistency']['status']}")
    return (
        2
        if inventory["frozen_history_modified"]
        or inventory["claim_consistency"]["status"] != "PASS"
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())

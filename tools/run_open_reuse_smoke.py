"""Run public synthetic Skill/Rule Pack/Adapter APIs with no model or network.

This is a maintainer or user local check, not proof of third-party adoption.
Only a new explicitly named output directory is written. No subprocesses run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
for location in (ROOT, ROOT / "src"):
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))

from examples.reuse.metadata_skill import run_example  # noqa: E402
from visiondata_gate.adapter_sdk import verify_adapter_conformance  # noqa: E402
from visiondata_gate.audit_envelope import canonical_jcs_bytes  # noqa: E402
from visiondata_gate.evidence import canonical_json_bytes  # noqa: E402
from visiondata_gate.industrial_skills import (  # noqa: E402
    IndustrialSkillReceipt,
    verify_industrial_skill_receipt,
)
from visiondata_gate.rulepack import (  # noqa: E402
    IndustrialRulePack,
    RulePackVerificationReceipt,
    verify_rule_pack,
)


INPUTS = {
    "rulepack": ROOT / "rulepacks/industrial-v1.json",
    "adapter_manifest": ROOT / "adapters/examples/omni-readonly-manifest.json",
    "adapter_observation": ROOT / "adapters/examples/omni-readonly-observation.json",
}
CLAIMS = {
    "schema_version": "visiondata-gate.open-reuse-receipt.v1",
    "status": "PASS_OPEN_REUSE_SMOKE",
    "execution_scope": "MAINTAINER_OR_USER_LOCAL_SYNTHETIC_OPEN_REUSE",
    "evidence_scope": "MAINTAINER_CI_CLEAN_CHECKOUT_NOT_THIRD_PARTY_ADOPTION",
    "third_party_reproduction_status": "THIRD_PARTY_REPRODUCTION_PENDING",
    "actual_model_call_count": 0,
    "network_call_count": 0,
    "production_release_allowed": False,
    "third_party_adoption_verified": False,
    "independent_external_reproduction_verified": False,
    "industrial_performance_verified": False,
    "ci_execution_attested_by_this_tool": False,
    "integrity_scope": "UNSIGNED_CONTENT_IDENTITY_NOT_INDEPENDENT_ATTESTATION",
}
ARTIFACTS = {name: name + ".json" for name in ("skill", "rulepack", "adapter")}
RECEIPT_NAME = "OPEN_REUSE_RECEIPT.json"
MAX_JSON_BYTES = 1024 * 1024


class OpenReuseSmokeError(ValueError):
    """Controlled path-free error code for local synthetic reuse checks."""


def _require(condition, code):
    if not condition:
        raise OpenReuseSmokeError(code)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _no_links(path):
    for member in (path, *path.parents):
        try:
            info = member.lstat()
        except FileNotFoundError:
            continue
        _require(
            not stat.S_ISLNK(info.st_mode)
            and not (getattr(info, "st_file_attributes", 0) & 0x400),
            "OUTPUT_LINK_OR_REPARSE",
        )


def _local_absolute(value):
    _require(
        not str(value).replace("\\", "/").startswith("//"),
        "OUTPUT_NETWORK_PATH_FORBIDDEN",
    )
    root = Path(os.path.abspath(value))
    _require(not root.as_posix().startswith("//"), "OUTPUT_NETWORK_PATH_FORBIDDEN")
    return root


def _new_root(value):
    root = _local_absolute(value)
    _require(root != Path(root.anchor), "OUTPUT_ROOT_FORBIDDEN")
    _no_links(root)
    _require(not root.exists(), "OUTPUT_ROOT_EXISTS")
    _require(root.parent.is_dir(), "OUTPUT_PARENT_REQUIRED")
    root.mkdir(exist_ok=False)
    return root


def _read_bytes(path):
    _no_links(path)
    _require(
        path.is_file() and path.stat().st_size <= MAX_JSON_BYTES, "RECEIPT_FILE_INVALID"
    )
    return path.read_bytes()


def _inputs():
    return {name: _read_bytes(path) for name, path in INPUTS.items()}


def _validate_components(values, inputs):
    skill = IndustrialSkillReceipt.model_validate(values["skill"])
    _require(verify_industrial_skill_receipt(skill), "SKILL_RECEIPT_INVALID")
    _require(
        skill.outcome.status == "OK"
        and skill.outcome.actual_model_call_count == 0
        and skill.outcome.network_call_count == 0,
        "SKILL_RESULT_NOT_PUBLIC_SYNTHETIC",
    )
    _require(
        len(skill.outcome.observations) == 1
        and skill.outcome.observations[0].decision.observed_value == 2
        and skill.outcome.observations[0].decision.is_anomaly is True,
        "SKILL_SYNTHETIC_RESULT_MISMATCH",
    )
    pack = IndustrialRulePack.model_validate_json(inputs["rulepack"])
    expected_rulepack = RulePackVerificationReceipt(
        pack_id=pack.pack_id,
        pack_version=pack.version,
        source_file_sha256=_sha(inputs["rulepack"]),
        semantic_sha256=_sha(canonical_json_bytes(pack.model_dump(mode="json"))),
        rule_count=len(pack.rules),
        dynamic_trigger_count=len(pack.dynamic_trigger_rules),
        production_release_allowed_by_default=False,
        raw_redistribution_allowed=False,
    )
    observed_rulepack = RulePackVerificationReceipt.model_validate(values["rulepack"])
    _require(observed_rulepack == expected_rulepack, "RULEPACK_RECEIPT_INVALID")
    adapter = values["adapter"]
    _require(
        adapter["receipt_sha256"]
        == _sha(
            canonical_json_bytes(
                {
                    key: value
                    for key, value in adapter.items()
                    if key != "receipt_sha256"
                }
            )
        ),
        "ADAPTER_RECEIPT_INVALID",
    )
    _require(
        adapter["status"] == "PASS"
        and len(adapter["checks"]) == 7
        and all(row["status"] == "PASS" for row in adapter["checks"])
        and type(adapter["actual_model_call_count"]) is int
        and adapter["actual_model_call_count"] == 0
        and adapter["network_probe_performed"] is False
        and adapter["manifest_sha256"] == _sha(inputs["adapter_manifest"])
        and adapter["observation_sha256"] == _sha(inputs["adapter_observation"]),
        "ADAPTER_CONFORMANCE_FAILED",
    )


def _write_new(path, value):
    _no_links(path)
    data = canonical_jcs_bytes(value)
    with path.open("xb") as stream:
        stream.write(data)
    return data


def run_smoke(output_root):
    """Call all three real APIs and publish PASS only after verified readback."""
    try:
        root = _new_root(output_root)
        inputs = _inputs()
        skill = run_example()
        rulepack = verify_rule_pack(INPUTS["rulepack"])
        adapter = verify_adapter_conformance(
            INPUTS["adapter_manifest"], INPUTS["adapter_observation"]
        )
        values = {
            "skill": skill.model_dump(mode="json"),
            "rulepack": rulepack.model_dump(mode="json"),
            "adapter": adapter,
        }
        _validate_components(values, inputs)
        _require(_inputs() == inputs, "INPUT_CHANGED_DURING_SMOKE")
        components = {}
        for name, filename in ARTIFACTS.items():
            data = _write_new(root / filename, values[name])
            components[name] = {
                "artifact": filename,
                "sha256": _sha(data),
                "bytes": len(data),
            }
        readback = {}
        for name, identity in components.items():
            data = _read_bytes(root / identity["artifact"])
            _require(
                _sha(data) == identity["sha256"] and len(data) == identity["bytes"],
                "RECEIPT_COMPONENT_CHANGED_BEFORE_PUBLISH",
            )
            readback[name] = json.loads(data)
        _validate_components(readback, inputs)
        _require(_inputs() == inputs, "INPUT_CHANGED_DURING_SMOKE")
        payload = dict(
            CLAIMS,
            components=components,
            input_sha256={name: _sha(data) for name, data in inputs.items()},
        )
        result = dict(payload, receipt_sha256=_sha(canonical_jcs_bytes(payload)))
        _write_new(root / RECEIPT_NAME, result)
        return result
    except OpenReuseSmokeError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        raise OpenReuseSmokeError("OPEN_REUSE_COMPONENT_OR_STORAGE_INVALID") from None


def verify_receipt(output_root):
    """Recheck saved bytes and component contracts; never rewrite a receipt."""
    try:
        root = _local_absolute(output_root)
        raw = _read_bytes(root / RECEIPT_NAME)
        report = json.loads(raw)
        _require(canonical_jcs_bytes(report) == raw, "RECEIPT_NOT_JCS")
        payload = {
            key: value for key, value in report.items() if key != "receipt_sha256"
        }
        _require(
            report["receipt_sha256"] == _sha(canonical_jcs_bytes(payload)),
            "RECEIPT_AGGREGATE_SHA_MISMATCH",
        )
        _require(
            set(report)
            == set(CLAIMS) | {"components", "input_sha256", "receipt_sha256"}
            and all(
                canonical_jcs_bytes(report[key]) == canonical_jcs_bytes(value)
                for key, value in CLAIMS.items()
            )
            and set(report["components"]) == set(ARTIFACTS),
            "RECEIPT_CLAIM_BOUNDARY_INVALID",
        )
        values = {}
        for name, filename in ARTIFACTS.items():
            identity = report["components"][name]
            _require(identity["artifact"] == filename, "RECEIPT_ARTIFACT_NAME_INVALID")
            data = _read_bytes(root / filename)
            _require(
                _sha(data) == identity["sha256"] and len(data) == identity["bytes"],
                "RECEIPT_COMPONENT_SHA_MISMATCH",
            )
            values[name] = json.loads(data)
        inputs = _inputs()
        _require(
            report["input_sha256"]
            == {name: _sha(data) for name, data in inputs.items()},
            "RECEIPT_INPUT_SHA_MISMATCH",
        )
        _validate_components(values, inputs)
        return report
    except OpenReuseSmokeError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise OpenReuseSmokeError("RECEIPT_INVALID") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_smoke(args.output_root)
    except OpenReuseSmokeError as error:
        print(json.dumps({"status": "HOLD", "error_code": str(error)}))
        return 2
    print(canonical_jcs_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

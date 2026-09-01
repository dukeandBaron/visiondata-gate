"""Strict, hashable contracts for reusable industrial policy rule packs."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import re
from typing import Literal, cast

from pydantic import Field, field_validator, model_validator

from .contracts import QualityThresholds
from .evidence import canonical_json_bytes, sha256_file, write_canonical_json
from .product_models import ProductModel


RuntimeRuleAction = Literal[
    "RECAPTURE",
    "RELABEL",
    "REMOVE_OR_REPARTITION",
    "INVESTIGATE",
]

_RUNTIME_TOOLS = {
    "image_quality",
    "duplicate_leakage",
    "annotation_integrity",
    "coverage_matrix",
    "governance_audit",
}
_RUNTIME_TRIGGER_CONTRACTS = {
    "metadata-count-drift": (
        "metadata_count_delta != 0",
        "industrial-metadata-reconciliation",
    ),
    "native-resolution-groups": (
        "native_resolution_group_count > 1",
        "native-resolution-quality-reconciliation",
    ),
    "cross-tool-action-conflict": (
        "conflicting_action_sample_count > 0",
        "industrial-remediation-conflict-adjudication",
    ),
}
_QUALITY_THRESHOLD_FIELDS = set(QualityThresholds.model_fields)
_RUNTIME_THRESHOLD_FIELDS = {*_QUALITY_THRESHOLD_FIELDS, "min_coverage_per_cell"}


class DynamicTriggerRule(ProductModel):
    trigger_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    observed_condition: str = Field(min_length=3)
    worker_capability: str = Field(min_length=3)
    max_cost_units: int = Field(ge=1, le=8)
    on_unavailable: Literal["DEFER", "INVESTIGATE"]


class IndustrialPolicyRule(ProductModel):
    rule_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]+$")
    finding_codes: list[str] = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"]
    action: Literal[
        "RECAPTURE",
        "REMOVE_OR_REPARTITION",
        "RELABEL",
        "INVESTIGATE",
        "QUARANTINE",
    ]
    human_gate_required: bool = True
    evidence_requirements: list[str] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    safety_boundary: str = Field(min_length=8)

    @field_validator("finding_codes")
    @classmethod
    def validate_finding_codes(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("finding_codes within one rule must be unique")
        for value in values:
            if value != value.strip().upper() or not re.fullmatch(
                r"[A-Z][A-Z0-9_]*", value
            ):
                raise ValueError("finding_codes must use canonical upper snake case")
        return values


class IndustrialRulePack(ProductModel):
    schema_version: Literal["visiondata-gate.rulepack.v1"]
    pack_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    domain: Literal["industrial_visual_data_release"]
    intended_use: Literal["sandbox_experiment_training_pool"]
    required_tools: list[str] = Field(min_length=1)
    thresholds: dict[str, int | float]
    dynamic_trigger_rules: list[DynamicTriggerRule] = Field(min_length=1)
    decision_precedence: list[
        Literal["INVESTIGATE", "RECAPTURE", "DEFER", "RELEASE"]
    ] = Field(min_length=4, max_length=4)
    rules: list[IndustrialPolicyRule] = Field(min_length=1)
    production_release_allowed_by_default: Literal[False]
    raw_redistribution_allowed: Literal[False]
    final_authority: Literal["responsible_human"]
    claim_boundary: str = Field(min_length=20)

    @field_validator("required_tools")
    @classmethod
    def unique_tools(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("required_tools must be unique")
        return value

    @model_validator(mode="after")
    def unique_rules_and_triggers(self) -> "IndustrialRulePack":
        rule_ids = [item.rule_id for item in self.rules]
        trigger_ids = [item.trigger_id for item in self.dynamic_trigger_rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("rule_id values must be unique")
        if len(trigger_ids) != len(set(trigger_ids)):
            raise ValueError("trigger_id values must be unique")
        finding_codes = [code for rule in self.rules for code in rule.finding_codes]
        if len(finding_codes) != len(set(finding_codes)):
            raise ValueError("finding_codes must map to exactly one policy rule")
        if self.decision_precedence != [
            "INVESTIGATE",
            "RECAPTURE",
            "DEFER",
            "RELEASE",
        ]:
            raise ValueError("decision_precedence must preserve fail-closed ordering")
        return self


class RulePackRuntimeBinding(ProductModel):
    """Fail-closed projection of one validated pack into the local runtime.

    Free-form condition strings are never evaluated.  A trigger becomes active
    only when its id, predicate text, and capability all match a locally
    implemented deterministic executor.
    """

    schema_version: Literal["visiondata-gate.rulepack-runtime-binding.v1"] = (
        "visiondata-gate.rulepack-runtime-binding.v1"
    )
    pack_id: str
    pack_version: str
    source_identity: Literal["FILE_BYTES", "CANONICAL_MODEL"]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_by_finding_code: dict[str, RuntimeRuleAction]
    rule_id_by_finding_code: dict[str, str]
    dynamic_trigger_capabilities: dict[str, str]
    dynamic_trigger_max_cost_units: dict[str, int]
    thresholds: dict[str, int | float]
    production_release_allowed_by_default: Literal[False]
    final_authority: Literal["responsible_human"]
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_boundary: str = (
        "This binding proves that one rule pack can be executed by the current "
        "local deterministic runtime. It is not factory calibration, customer "
        "acceptance, a Python sandbox, or production-release authority."
    )

    @model_validator(mode="after")
    def validate_runtime_binding(self) -> "RulePackRuntimeBinding":
        action_codes = set(self.action_by_finding_code)
        rule_codes = set(self.rule_id_by_finding_code)
        if not action_codes or action_codes != rule_codes:
            raise ValueError("runtime action and rule-id finding code sets must match")
        for code in action_codes:
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", code):
                raise ValueError(
                    "runtime finding codes must use canonical upper snake case"
                )
        if set(self.dynamic_trigger_capabilities) != set(
            self.dynamic_trigger_max_cost_units
        ):
            raise ValueError("runtime dynamic trigger capability/cost sets must match")
        payload = self.model_dump(mode="json", exclude={"binding_sha256"})
        observed = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if not hmac.compare_digest(observed, self.binding_sha256):
            raise ValueError("rule pack runtime binding seal mismatch")
        return self


class RulePackVerificationReceipt(ProductModel):
    schema_version: Literal["visiondata-gate.rulepack-verification.v1"] = (
        "visiondata-gate.rulepack-verification.v1"
    )
    status: Literal["PASS"] = "PASS"
    pack_id: str
    pack_version: str
    source_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_count: int = Field(ge=1)
    dynamic_trigger_count: int = Field(ge=1)
    production_release_allowed_by_default: Literal[False]
    raw_redistribution_allowed: Literal[False]
    claim_boundary: str = (
        "PASS proves schema, uniqueness, digest, and fail-closed ordering only. It "
        "does not certify the thresholds for a specific factory or authorize release."
    )


def load_rule_pack(path: str | Path) -> IndustrialRulePack:
    source = Path(path).expanduser().resolve(strict=True)
    return IndustrialRulePack.model_validate_json(source.read_text(encoding="utf-8"))


def build_rule_pack_runtime_binding(
    rule_pack: IndustrialRulePack | str | Path,
) -> RulePackRuntimeBinding:
    """Compile a pack only when every executable surface is locally supported."""

    if isinstance(rule_pack, (str, Path)):
        source = Path(rule_pack).expanduser().resolve(strict=True)
        pack = load_rule_pack(source)
        source_identity: Literal["FILE_BYTES", "CANONICAL_MODEL"] = "FILE_BYTES"
        source_sha256 = sha256_file(source)
    else:
        pack = rule_pack
        source_identity = "CANONICAL_MODEL"
        source_sha256 = hashlib.sha256(
            canonical_json_bytes(pack.model_dump(mode="json"))
        ).hexdigest()
    required_tools = set(pack.required_tools)
    if required_tools != _RUNTIME_TOOLS:
        missing = sorted(_RUNTIME_TOOLS - required_tools)
        unsupported = sorted(required_tools - _RUNTIME_TOOLS)
        raise ValueError(
            "runtime rule pack tool set mismatch: "
            f"missing={missing}; unsupported={unsupported}"
        )
    threshold_fields = set(pack.thresholds)
    if threshold_fields != _RUNTIME_THRESHOLD_FIELDS:
        missing = sorted(_RUNTIME_THRESHOLD_FIELDS - threshold_fields)
        unsupported = sorted(threshold_fields - _RUNTIME_THRESHOLD_FIELDS)
        raise ValueError(
            "runtime rule pack threshold set mismatch: "
            f"missing={missing}; unsupported={unsupported}"
        )
    QualityThresholds.model_validate(
        {key: pack.thresholds[key] for key in _QUALITY_THRESHOLD_FIELDS}
    )
    minimum_coverage = pack.thresholds["min_coverage_per_cell"]
    if (
        isinstance(minimum_coverage, bool)
        or not isinstance(minimum_coverage, int)
        or minimum_coverage < 1
    ):
        raise ValueError("min_coverage_per_cell must be a positive integer")

    action_by_code: dict[str, RuntimeRuleAction] = {}
    rule_id_by_code: dict[str, str] = {}
    supported_actions = {
        "RECAPTURE",
        "RELABEL",
        "REMOVE_OR_REPARTITION",
        "INVESTIGATE",
    }
    for rule in pack.rules:
        if rule.action not in supported_actions:
            raise ValueError(
                f"rule {rule.rule_id} uses non-executable action {rule.action}"
            )
        for code in rule.finding_codes:
            action_by_code[code] = cast(RuntimeRuleAction, rule.action)
            rule_id_by_code[code] = rule.rule_id

    trigger_capabilities: dict[str, str] = {}
    trigger_costs: dict[str, int] = {}
    for trigger in pack.dynamic_trigger_rules:
        expected = _RUNTIME_TRIGGER_CONTRACTS.get(trigger.trigger_id)
        if expected is None:
            raise ValueError(
                f"dynamic trigger {trigger.trigger_id} has no local executor"
            )
        if (trigger.observed_condition, trigger.worker_capability) != expected:
            raise ValueError(
                f"dynamic trigger {trigger.trigger_id} does not match its local "
                "predicate/capability contract"
            )
        trigger_capabilities[trigger.trigger_id] = trigger.worker_capability
        trigger_costs[trigger.trigger_id] = trigger.max_cost_units

    semantic_sha256 = hashlib.sha256(
        canonical_json_bytes(pack.model_dump(mode="json"))
    ).hexdigest()
    stable = {
        "schema_version": "visiondata-gate.rulepack-runtime-binding.v1",
        "pack_id": pack.pack_id,
        "pack_version": pack.version,
        "source_identity": source_identity,
        "source_sha256": source_sha256,
        "semantic_sha256": semantic_sha256,
        "action_by_finding_code": action_by_code,
        "rule_id_by_finding_code": rule_id_by_code,
        "dynamic_trigger_capabilities": trigger_capabilities,
        "dynamic_trigger_max_cost_units": trigger_costs,
        "thresholds": pack.thresholds,
        "production_release_allowed_by_default": False,
        "final_authority": "responsible_human",
        "claim_boundary": RulePackRuntimeBinding.model_fields["claim_boundary"].default,
    }
    return RulePackRuntimeBinding(
        **stable,
        binding_sha256=hashlib.sha256(canonical_json_bytes(stable)).hexdigest(),
    )


def verify_rule_pack_runtime_binding(
    binding: RulePackRuntimeBinding,
) -> RulePackRuntimeBinding:
    """Revalidate a possibly copied or mutated binding before runtime use."""

    try:
        return RulePackRuntimeBinding.model_validate(binding.model_dump(mode="json"))
    except (TypeError, ValueError) as error:
        raise ValueError(
            "rule pack runtime binding failed integrity validation"
        ) from error


def verify_rule_pack(
    path: str | Path, *, output: str | Path | None = None
) -> RulePackVerificationReceipt:
    source = Path(path).expanduser().resolve(strict=True)
    pack = load_rule_pack(source)
    receipt = RulePackVerificationReceipt(
        pack_id=pack.pack_id,
        pack_version=pack.version,
        source_file_sha256=sha256_file(source),
        semantic_sha256=hashlib.sha256(
            canonical_json_bytes(pack.model_dump(mode="json"))
        ).hexdigest(),
        rule_count=len(pack.rules),
        dynamic_trigger_count=len(pack.dynamic_trigger_rules),
        production_release_allowed_by_default=(
            pack.production_release_allowed_by_default
        ),
        raw_redistribution_allowed=pack.raw_redistribution_allowed,
    )
    if output is not None:
        write_canonical_json(Path(output).expanduser().resolve(), receipt)
    return receipt


__all__ = [
    "DynamicTriggerRule",
    "IndustrialPolicyRule",
    "IndustrialRulePack",
    "RulePackRuntimeBinding",
    "RulePackVerificationReceipt",
    "RuntimeRuleAction",
    "build_rule_pack_runtime_binding",
    "load_rule_pack",
    "verify_rule_pack_runtime_binding",
    "verify_rule_pack",
]

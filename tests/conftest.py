from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _explicit_local_api_test_authenticator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep legacy header-scoped tests explicit without weakening runtime defaults."""

    monkeypatch.delenv("VISIONDATA_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("VISIONDATA_DESKTOP_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("VISIONDATA_SESSION_ACTOR_USER_ID", raising=False)
    monkeypatch.setenv("VISIONDATA_INSECURE_TEST_ACTOR_HEADER_BYPASS", "true")


# Every test receives one primary tier.  The default pytest invocation remains
# the repository-wide freeze regression; markers only provide explicit,
# auditable development slices and never silently reduce the full denominator.
_RELEASE_MODULES = frozenset(
    {
        "test_desktop_packaging",
        "test_evidence_package",
        "test_rc3_acceptance",
        "test_release_artifacts",
        "test_release_attestation",
        "test_release_evidence",
        "test_submission_release",
        "test_supply_chain_artifacts",
    }
)

_BENCHMARK_MODULES = frozenset(
    {
        "test_agent_evaluation",
        "test_architecture_benchmark",
        "test_dynamic_benchmark",
        "test_dynamic_benchmark_v2",
        "test_dynamic_benchmark_v3",
        "test_dynamic_benchmark_v4",
        "test_generator_quality",
        "test_geometry_consistency",
        "test_governance_effectiveness",
        "test_governance_effectiveness_v2",
        "test_industrial_incident_benchmark",
        "test_memory_governance_benchmark",
        "test_public_governance_bench",
        "test_public_runtime_benchmark",
        "test_repair_evaluation",
        "test_reviewer_scenario_suite",
        "test_runtime_hardening_evaluation",
        "test_tool_fault_evaluation",
    }
)

_UI_MODULES = frozenset(
    {
        "test_app_source",
        "test_reviewer_server",
        "test_web_source",
        "test_website_data",
    }
)

_INTEGRATION_MODULES = frozenset(
    {
        "test_agent_runtime",
        "test_agentteams_transport",
        "test_agentteams_v122",
        "test_annotation_roundtrip",
        "test_api",
        "test_capa",
        "test_geometry_backends",
        "test_goal3_bridge",
        "test_hosted_agentteams_product",
        "test_incident_interaction_api",
        "test_incident_command_integration",
        "test_incident_model_planner",
        "test_longcat_backend",
        "test_multimodal_advisor",
        "test_network_resilience",
        "test_omni_adapter",
        "test_operator_snapshot_source",
        "test_operator_workspace",
        "test_pipeline_cli",
        "test_product_lifecycle_stub",
        "test_product_run_cli",
        "test_product_service",
        "test_product_service_omni",
        "test_product_service_real",
        "test_reviewer_audit",
        "test_semifinal_demo",
        "test_task_store",
        "test_tools",
    }
)

_SLOW_MODULES = frozenset(
    {
        "test_agent_runtime",
        "test_agentteams_transport",
        "test_agentteams_v122",
        "test_annotation_roundtrip",
        "test_api",
        "test_app_source",
        "test_architecture_benchmark",
        "test_capa",
        "test_incident_command_integration",
        "test_pipeline_cli",
        "test_operator_snapshot_source",
        "test_product_service",
        "test_product_service_omni",
        "test_product_service_real",
        "test_release_attestation",
        "test_reviewer_audit",
        "test_reviewer_scenario_suite",
        "test_semifinal_demo",
        "test_tool_fault_evaluation",
        "test_tools",
    }
)

_PRIMARY_TIER_MODULES = {
    "tier_release": _RELEASE_MODULES,
    "tier_benchmark": _BENCHMARK_MODULES,
    "tier_ui": _UI_MODULES,
    "tier_integration": _INTEGRATION_MODULES,
}
_PRIMARY_TIER_MARKERS = frozenset({"tier_core", *_PRIMARY_TIER_MODULES})

_assigned_modules = [
    module for modules in _PRIMARY_TIER_MODULES.values() for module in modules
]
if len(_assigned_modules) != len(set(_assigned_modules)):
    raise RuntimeError("a test module is assigned to more than one primary tier")


def _primary_tier_names(item: pytest.Item) -> set[str]:
    return {
        marker.name
        for marker in item.iter_markers()
        if marker.name in _PRIMARY_TIER_MARKERS
    }


def _module_primary_tier(module_name: str) -> str:
    for marker_name, modules in _PRIMARY_TIER_MODULES.items():
        if module_name in modules:
            return marker_name
    return "tier_core"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Attach deterministic test tiers without changing the full run default."""

    for item in items:
        module_name = Path(str(item.path)).stem
        explicit_primary_tiers = _primary_tier_names(item)
        if len(explicit_primary_tiers) > 1:
            raise pytest.UsageError(
                f"{item.nodeid} has multiple explicit primary tiers: "
                f"{sorted(explicit_primary_tiers)}"
            )
        if explicit_primary_tiers:
            primary_tier = next(iter(explicit_primary_tiers))
        else:
            primary_tier = _module_primary_tier(module_name)
            item.add_marker(getattr(pytest.mark, primary_tier))

        observed_primary_tiers = _primary_tier_names(item)
        if observed_primary_tiers != {primary_tier}:
            raise pytest.UsageError(
                f"{item.nodeid} must have exactly one primary tier; "
                f"observed {sorted(observed_primary_tiers)}"
            )
        if module_name in _SLOW_MODULES:
            item.add_marker(pytest.mark.slow)

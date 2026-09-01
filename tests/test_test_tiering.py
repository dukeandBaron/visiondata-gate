from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest as tiering


class _FakeItem:
    def __init__(self, module_name: str, *marker_names: str) -> None:
        self.path = Path("tests") / f"{module_name}.py"
        self.nodeid = f"tests/{module_name}.py::test_fixture"
        self._markers = [SimpleNamespace(name=name) for name in marker_names]

    def iter_markers(self):
        return iter(self._markers)

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        self._markers.append(SimpleNamespace(name=marker.name))


def test_tiering_respects_one_explicit_primary_tier() -> None:
    item = _FakeItem("test_dynamic_benchmark_v3", "tier_benchmark")

    tiering.pytest_collection_modifyitems([item])

    assert tiering._primary_tier_names(item) == {"tier_benchmark"}


def test_tiering_infers_module_or_core_when_no_explicit_tier_exists() -> None:
    integration = _FakeItem("test_agent_runtime")
    interaction_api = _FakeItem("test_incident_interaction_api")
    benchmark = _FakeItem("test_public_runtime_benchmark")
    release = _FakeItem("test_release_evidence")
    core = _FakeItem("test_test_tiering")

    tiering.pytest_collection_modifyitems(
        [integration, interaction_api, benchmark, release, core]
    )

    assert tiering._primary_tier_names(integration) == {"tier_integration"}
    assert tiering._primary_tier_names(interaction_api) == {"tier_integration"}
    assert tiering._primary_tier_names(benchmark) == {"tier_benchmark"}
    assert tiering._primary_tier_names(release) == {"tier_release"}
    assert tiering._primary_tier_names(core) == {"tier_core"}


def test_heavy_end_to_end_modules_are_slow_integrations() -> None:
    operator_snapshot = _FakeItem("test_operator_snapshot_source")
    agentteams = _FakeItem("test_agentteams_v122")

    tiering.pytest_collection_modifyitems([operator_snapshot, agentteams])

    assert tiering._primary_tier_names(operator_snapshot) == {"tier_integration"}
    assert tiering._primary_tier_names(agentteams) == {"tier_integration"}
    assert {marker.name for marker in operator_snapshot.iter_markers()} >= {
        "tier_integration",
        "slow",
    }
    assert {marker.name for marker in agentteams.iter_markers()} >= {
        "tier_integration",
        "slow",
    }


def test_tiering_inventory_classifies_named_benchmarks_and_release_checks() -> None:
    test_modules = {path.stem for path in Path(__file__).parent.glob("test_*.py")}
    benchmark_named = {
        module
        for module in test_modules
        if "benchmark" in module
        or module.endswith("_evaluation")
        or module.startswith("test_governance_effectiveness")
        or module == "test_public_governance_bench"
    }
    release_named = {
        module for module in test_modules if module.startswith("test_release_")
    }

    assert benchmark_named <= tiering._BENCHMARK_MODULES
    assert release_named <= tiering._RELEASE_MODULES


def test_tiering_rejects_multiple_explicit_primary_tiers() -> None:
    item = _FakeItem(
        "test_governance_effectiveness",
        "tier_core",
        "tier_integration",
    )

    with pytest.raises(pytest.UsageError, match="multiple explicit primary tiers"):
        tiering.pytest_collection_modifyitems([item])

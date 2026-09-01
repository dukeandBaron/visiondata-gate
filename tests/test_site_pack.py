from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from visiondata_gate.site_pack import (
    build_site_pack_validation_receipt,
    load_factory_site_pack,
    load_sample_record,
    map_source_record,
    run_site_portability_check,
    verify_canonical_mapping_result,
    verify_factory_site_pack,
)

SITE_PACK_ROOT = Path(__file__).parents[1] / "examples" / "site_packs"


def test_two_site_packs_map_different_fields_with_one_core() -> None:
    site_a = SITE_PACK_ROOT / "factory_a_line_01"
    site_b = SITE_PACK_ROOT / "factory_b_cell_07"

    pack_a = load_factory_site_pack(site_a)
    pack_b = load_factory_site_pack(site_b)
    verify_factory_site_pack(pack_a)
    verify_factory_site_pack(pack_b)
    mapping_a = map_source_record(
        pack_a, load_sample_record(site_a / "sample_record.json")
    )
    mapping_b = map_source_record(
        pack_b, load_sample_record(site_b / "sample_record.json")
    )
    verify_canonical_mapping_result(mapping_a)
    verify_canonical_mapping_result(mapping_b)

    assert mapping_a.status == "PASS"
    assert mapping_b.status == "PASS"
    assert set(mapping_a.canonical_entities) == set(mapping_b.canonical_entities)
    assert mapping_a.canonical_entities["Product"] == "METAL-PART-A"
    assert mapping_b.canonical_entities["Product"] == "POLYMER-HOUSING-B"

    report = run_site_portability_check(
        [
            (site_a, load_sample_record(site_a / "sample_record.json")),
            (site_b, load_sample_record(site_b / "sample_record.json")),
        ]
    )
    assert report.status == "PASS"
    assert report.site_count == 2
    assert report.core_code_change_count == 0
    assert report.distinct_core_implementation_count == 1
    assert report.site_pack_validation_rate == 1.0
    assert report.canonical_field_mapping_coverage == 1.0
    assert report.replay_consistency == 1.0
    assert report.time_to_onboard_new_site == "NOT_MEASURED"


def test_site_pack_validation_is_offline_and_does_not_claim_factory_connection() -> (
    None
):
    pack = load_factory_site_pack(SITE_PACK_ROOT / "factory_a_line_01")
    receipt = build_site_pack_validation_receipt(pack)

    assert receipt.status == "PASS"
    assert receipt.canonical_schema_coverage == 1.0
    assert receipt.live_connection_probe_performed is False
    assert pack.manifest.production_site_claimed is False
    assert all(
        connector.read_only
        and not connector.credentials_included
        and not connector.live_connection_claimed
        for connector in pack.connector_profiles.connectors.values()
    )


def test_missing_required_source_field_fails_mapping_without_inventing_value() -> None:
    pack = load_factory_site_pack(SITE_PACK_ROOT / "factory_b_cell_07")
    record = load_sample_record(
        SITE_PACK_ROOT / "factory_b_cell_07" / "sample_record.json"
    )
    record.pop("batch_ref")

    result = map_source_record(pack, record)

    assert result.status == "FAIL_MISSING_REQUIRED_FIELDS"
    assert result.missing_entities == ["Batch"]
    assert "Batch" not in result.canonical_entities
    assert result.raw_source_record_retained is False


def test_site_pack_rejects_path_traversal(tmp_path: Path) -> None:
    source = SITE_PACK_ROOT / "factory_a_line_01"
    target = tmp_path / "unsafe-pack"
    target.mkdir()
    for path in source.iterdir():
        if path.is_file():
            (target / path.name).write_bytes(path.read_bytes())
    connector_path = target / "connector_profiles.yaml"
    document = yaml.safe_load(connector_path.read_text(encoding="utf-8"))
    document["connectors"]["image_source"]["relative_path"] = "../outside"
    connector_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="relative and traversal-free"):
        load_factory_site_pack(target)

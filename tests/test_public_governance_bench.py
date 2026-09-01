from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path

import pytest

from visiondata_gate.public_governance_bench import (
    CreateProgrammaticGovernanceCase,
    OFFICIAL_VISA_1CLS_HEADER,
    SourceSchemaDeferredError,
    build_programmatic_governance_manifest,
    build_programmatic_truth_receipt,
    build_public_source_binding,
    build_visa_source_index,
    canonical_public_bench_json_bytes,
    governance_truth_binding_from_public_receipt,
    official_visa_1cls_column_mapping,
    verify_programmatic_governance_manifest,
    verify_programmatic_truth_receipt,
    verify_visa_source_assets,
    visa_csv_header_sha256,
)


NOW = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
VISA_HEADER = list(OFFICIAL_VISA_1CLS_HEADER)
VISA_MAPPING = official_visa_1cls_column_mapping()


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _source_binding():
    return build_public_source_binding(
        dataset_version="1.0-local-authorized",
        source_homepage_url="https://github.com/amazon-science/spot-diff",
        source_archive_sha256=_digest("visa-source-archive"),
        license_text_sha256=_digest("cc-by-4.0-license-text"),
        attribution_text_sha256=_digest("visa-attribution"),
        bound_at=NOW,
    )


def _visa_fixture(tmp_path: Path):
    root = tmp_path / "visa"
    (root / "pcb1" / "images").mkdir(parents=True)
    (root / "pcb1" / "masks").mkdir(parents=True)
    (root / "split_csv").mkdir(parents=True)
    (root / "pcb1" / "images" / "normal.png").write_bytes(b"normal-image")
    (root / "pcb1" / "images" / "anomaly.png").write_bytes(b"anomaly-image")
    (root / "pcb1" / "masks" / "anomaly.png").write_bytes(b"anomaly-mask")
    csv_path = root / "split_csv" / "1cls.csv"
    csv_path.write_text(
        "object,split,label,image,mask\n"
        "pcb1,train,normal,pcb1/images/normal.png,\n"
        "pcb1,test,anomaly,pcb1/images/anomaly.png,pcb1/masks/anomaly.png\n",
        encoding="utf-8",
    )
    binding = _source_binding()
    index = build_visa_source_index(
        root,
        source_binding=binding,
        split_csv_relative_path="split_csv/1cls.csv",
        expected_csv_header_sha256=visa_csv_header_sha256(VISA_HEADER),
        column_mapping=VISA_MAPPING,
    )
    return root, binding, index


def test_visa_index_is_header_driven_and_binds_relative_source_assets(
    tmp_path: Path,
) -> None:
    root, binding, index = _visa_fixture(tmp_path)

    assert index.source_binding_sha256 == binding.binding_sha256
    assert index.sample_count == 2
    assert index.csv_header == VISA_HEADER
    assert index.csv_header_sha256 == visa_csv_header_sha256(VISA_HEADER)
    assert index.source_assets_copied is False
    assert index.product_labels_used_as_governance_truth is False
    assert all(":" not in item.image_relative_path for item in index.samples)
    assert all("\\" not in item.image_relative_path for item in index.samples)
    assert all(
        item.product_label_governance_authority == "none" for item in index.samples
    )
    assert canonical_public_bench_json_bytes(index)
    verify_visa_source_assets(index, dataset_root=root)

    (root / index.samples[0].image_relative_path).write_bytes(b"drifted-image")
    with pytest.raises(ValueError, match="image asset drifted"):
        verify_visa_source_assets(index, dataset_root=root)


def test_visa_index_defers_header_drift_and_rejects_path_traversal(
    tmp_path: Path,
) -> None:
    root, binding, _ = _visa_fixture(tmp_path)

    with pytest.raises(SourceSchemaDeferredError, match="approved header digest"):
        build_visa_source_index(
            root,
            source_binding=binding,
            split_csv_relative_path="split_csv/1cls.csv",
            expected_csv_header_sha256=_digest("unknown-header"),
            column_mapping=VISA_MAPPING,
        )

    (root / "split_csv" / "traversal.csv").write_text(
        "object,split,label,image,mask\n"
        "pcb1,test,anomaly,../outside.png,pcb1/masks/anomaly.png\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="escaped the dataset root"):
        build_visa_source_index(
            root,
            source_binding=binding,
            split_csv_relative_path="split_csv/traversal.csv",
            expected_csv_header_sha256=visa_csv_header_sha256(VISA_HEADER),
            column_mapping=VISA_MAPPING,
        )


def test_detached_programmatic_truth_separates_release_block_and_pending(
    tmp_path: Path,
) -> None:
    root, binding, index = _visa_fixture(tmp_path)
    normal, anomaly = index.samples
    manifest = build_programmatic_governance_manifest(
        index,
        source_binding=binding,
        dataset_root=root,
        deterministic_seed=20260829,
        created_at=NOW,
        cases=[
            CreateProgrammaticGovernanceCase(
                unit_id="public-control-001",
                source_sample_id=normal.source_sample_id,
                case_type="CLEAN_CONTROL",
                parameters_sha256=_digest("no-mutation"),
            ),
            CreateProgrammaticGovernanceCase(
                unit_id="public-block-001",
                source_sample_id=anomaly.source_sample_id,
                case_type="ANOMALY_MASK_MISSING",
                parameters_sha256=_digest("remove-mask-reference"),
                derived_artifact_relative_paths=[
                    "derived/public-block-001/manifest.csv"
                ],
            ),
            CreateProgrammaticGovernanceCase(
                unit_id="public-pending-001",
                source_sample_id=normal.source_sample_id,
                case_type="BLUR_THRESHOLD",
                parameters_sha256=_digest("gaussian-blur-boundary"),
                derived_artifact_relative_paths=[
                    "derived/public-pending-001/image.png"
                ],
            ),
        ],
    )
    receipt = build_programmatic_truth_receipt(manifest)

    assert manifest.evaluation_scope == (
        "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH"
    )
    assert manifest.source_dataset_mutated is False
    assert manifest.product_labels_used_as_governance_truth is False
    assert receipt.release_allowed_count == 1
    assert receipt.block_required_count == 1
    assert receipt.pending_adjudication_count == 1
    assert receipt.actual_factory_truth is False
    assert receipt.public_proxy_only is True

    release = governance_truth_binding_from_public_receipt(
        receipt, unit_id="public-control-001"
    )
    block = governance_truth_binding_from_public_receipt(
        receipt, unit_id="public-block-001"
    )
    pending = governance_truth_binding_from_public_receipt(
        receipt, unit_id="public-pending-001"
    )
    assert release.disposition == "RELEASE_ALLOWED"
    assert block.disposition == "BLOCK_REQUIRED"
    assert release.adjudication_receipt_sha256 == receipt.receipt_sha256
    assert block.adjudication_receipt_sha256 == receipt.receipt_sha256
    assert pending.status == "PENDING_ADJUDICATION"
    assert pending.disposition is None

    forged_case = manifest.cases[1].model_copy(
        update={"truth_disposition": "RELEASE_ALLOWED"}
    )
    forged_manifest = manifest.model_copy(
        update={"cases": [manifest.cases[0], forged_case, manifest.cases[2]]}
    )
    with pytest.raises(ValueError, match="case failed SHA-256"):
        verify_programmatic_governance_manifest(
            forged_manifest,
            source_index=index,
            source_binding=binding,
        )

    incomplete_receipt = receipt.model_copy(
        update={
            "unit_count": 2,
            "pending_adjudication_count": 0,
            "units": receipt.units[:2],
        }
    )
    with pytest.raises(ValueError, match="full manifest"):
        verify_programmatic_truth_receipt(
            incomplete_receipt,
            manifest=manifest,
        )

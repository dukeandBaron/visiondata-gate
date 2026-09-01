from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from visiondata_gate.evaluation_contracts import (
    EvaluationDenominatorV1,
    build_image_batch_case_episode_contract,
    build_omni_product_pilot_evaluation_contract,
    verify_image_batch_case_episode_contract,
)


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _write_product_pilot_receipt(path: Path) -> str:
    payload = {
        "schema_version": "visiondata-gate.authorized-product-pilot.v2",
        "execution_status": "COMPLETED",
        "final_decision": "RECAPTURE",
        "source_profile_sha256": _sha("omni-source-profile"),
        "source_image_count": 4464,
        "selected_image_count": 180,
        "source_path_serialized": False,
        "source_assets_copied_into_product": False,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pending(unit_kind: str) -> EvaluationDenominatorV1:
    return EvaluationDenominatorV1(
        unit_kind=unit_kind,
        status="NOT_MEASURED_PENDING_ADJUDICATION",
        count=0,
        definition="independently adjudicated evaluation units",
        pending_reason="no independently adjudicated truth manifest is bound",
    )


def test_omni_pilot_keeps_image_batch_case_episode_denominators_separate(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "authorized_product_pilot_receipt.json"
    receipt_sha256 = _write_product_pilot_receipt(receipt_path)

    contract = build_omni_product_pilot_evaluation_contract(
        receipt_path,
        expected_receipt_sha256=receipt_sha256,
    )

    assert contract.source_profile_image_count == 4464
    assert contract.digest_contract == "RFC8785_JCS_SHA256_LENGTH_PREFIX_DOMAIN_V1"
    assert (contract.image.status, contract.image.count) == ("MEASURED", 180)
    assert (contract.batch.status, contract.batch.count) == ("MEASURED", 1)
    assert contract.case.status == "NOT_MEASURED_PENDING_ADJUDICATION"
    assert contract.case.count == 0
    assert contract.episode.status == "NOT_MEASURED_PENDING_ADJUDICATION"
    assert contract.episode.count == 0
    assert contract.kpi_denominator_units["false_release_rate"] == "CASE"
    assert contract.kpi_denominator_units["false_block_rate"] == "CASE"
    assert contract.kpi_denominator_units["dynamic_vs_fixed_comparison"] == "EPISODE"
    assert contract.false_release_rate_denominator.status == (
        "NOT_MEASURED_PENDING_ADJUDICATION"
    )
    assert contract.false_release_rate_denominator.count == 0
    assert contract.false_block_rate_denominator.status == (
        "NOT_MEASURED_PENDING_ADJUDICATION"
    )
    assert contract.false_block_rate_denominator.count == 0
    assert contract.image_count_may_be_used_as_case_count is False
    assert contract.production_release_allowed is False
    verify_image_batch_case_episode_contract(contract)


def test_evaluation_contract_is_hash_bound_and_receipt_sha_is_fail_closed(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "authorized_product_pilot_receipt.json"
    receipt_sha256 = _write_product_pilot_receipt(receipt_path)
    contract = build_omni_product_pilot_evaluation_contract(
        receipt_path,
        expected_receipt_sha256=receipt_sha256,
    )

    tampered_image = contract.image.model_copy(update={"count": 181})
    tampered_contract = contract.model_copy(update={"image": tampered_image})
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_image_batch_case_episode_contract(tampered_contract)

    with pytest.raises(ValueError, match="receipt SHA-256 mismatch"):
        build_omni_product_pilot_evaluation_contract(
            receipt_path,
            expected_receipt_sha256=_sha("wrong-receipt"),
        )


def test_evaluation_contract_rejects_unit_swaps_and_image_count_overreach() -> None:
    evidence_sha = _sha("evidence")
    image_as_batch = EvaluationDenominatorV1(
        unit_kind="BATCH",
        status="MEASURED",
        count=1,
        evidence_binding_sha256=evidence_sha,
        definition="incorrectly assigned image denominator",
    )
    batch_as_image = EvaluationDenominatorV1(
        unit_kind="IMAGE",
        status="MEASURED",
        count=1,
        evidence_binding_sha256=evidence_sha,
        definition="incorrectly assigned batch denominator",
    )

    with pytest.raises(ValidationError, match="image denominator must use the IMAGE"):
        build_image_batch_case_episode_contract(
            evaluation_id="unit-swap-test",
            source_scope="SYNTHETIC_FIXED_FIXTURE",
            dataset_identity_sha256=_sha("dataset"),
            source_profile_image_count=1,
            image=image_as_batch,
            batch=batch_as_image,
            case=_pending("CASE"),
            episode=_pending("EPISODE"),
            false_release_rate_denominator=_pending("CASE"),
            false_block_rate_denominator=_pending("CASE"),
        )

    measured_images = EvaluationDenominatorV1(
        unit_kind="IMAGE",
        status="MEASURED",
        count=2,
        evidence_binding_sha256=evidence_sha,
        definition="two measured images from one-image source",
    )
    measured_batch = EvaluationDenominatorV1(
        unit_kind="BATCH",
        status="MEASURED",
        count=1,
        evidence_binding_sha256=evidence_sha,
        definition="one measured batch for overreach test",
    )
    with pytest.raises(ValidationError, match="cannot exceed"):
        build_image_batch_case_episode_contract(
            evaluation_id="image-overreach-test",
            source_scope="SYNTHETIC_FIXED_FIXTURE",
            dataset_identity_sha256=_sha("dataset"),
            source_profile_image_count=1,
            image=measured_images,
            batch=measured_batch,
            case=_pending("CASE"),
            episode=_pending("EPISODE"),
            false_release_rate_denominator=_pending("CASE"),
            false_block_rate_denominator=_pending("CASE"),
        )


def test_measured_case_count_does_not_imply_measured_false_rate_denominators() -> None:
    evidence_sha = _sha("adjudicated-cases")
    contract = build_image_batch_case_episode_contract(
        evaluation_id="case-without-rate-subsets",
        source_scope="PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH",
        dataset_identity_sha256=_sha("public-proxy-dataset"),
        source_profile_image_count=4,
        image=EvaluationDenominatorV1(
            unit_kind="IMAGE",
            status="MEASURED",
            count=4,
            evidence_binding_sha256=evidence_sha,
            definition="four images bound to two adjudicated governance cases",
        ),
        batch=EvaluationDenominatorV1(
            unit_kind="BATCH",
            status="MEASURED",
            count=1,
            evidence_binding_sha256=evidence_sha,
            definition="one batch bound to the adjudicated case manifest",
        ),
        case=EvaluationDenominatorV1(
            unit_kind="CASE",
            status="MEASURED",
            count=2,
            evidence_binding_sha256=evidence_sha,
            definition="two independently adjudicated governance cases",
        ),
        episode=_pending("EPISODE"),
        false_release_rate_denominator=_pending("CASE"),
        false_block_rate_denominator=_pending("CASE"),
    )

    assert contract.case.status == "MEASURED"
    assert contract.false_release_rate_denominator.status == (
        "NOT_MEASURED_PENDING_ADJUDICATION"
    )
    assert contract.false_block_rate_denominator.status == (
        "NOT_MEASURED_PENDING_ADJUDICATION"
    )
    verify_image_batch_case_episode_contract(contract)


def test_evaluation_denominator_rejects_boolean_count() -> None:
    with pytest.raises(ValidationError):
        EvaluationDenominatorV1(
            unit_kind="IMAGE",
            status="MEASURED",
            count=True,
            evidence_binding_sha256=_sha("evidence"),
            definition="boolean values are not valid denominator counts",
        )


def test_omni_contract_rejects_invalid_json_and_incomplete_execution(
    tmp_path: Path,
) -> None:
    invalid_utf8 = tmp_path / "invalid_utf8.json"
    invalid_utf8.write_bytes(b'{"schema_version":\xff}')
    with pytest.raises(ValueError, match="invalid JSON"):
        build_omni_product_pilot_evaluation_contract(
            invalid_utf8,
            expected_receipt_sha256=hashlib.sha256(
                invalid_utf8.read_bytes()
            ).hexdigest(),
        )

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"selected_image_count":180,"selected_image_count":181}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid JSON"):
        build_omni_product_pilot_evaluation_contract(
            duplicate,
            expected_receipt_sha256=hashlib.sha256(duplicate.read_bytes()).hexdigest(),
        )

    incomplete = tmp_path / "incomplete.json"
    _write_product_pilot_receipt(incomplete)
    payload = json.loads(incomplete.read_text(encoding="utf-8"))
    payload["execution_status"] = "RUNNING"
    incomplete.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="boundary checks"):
        build_omni_product_pilot_evaluation_contract(
            incomplete,
            expected_receipt_sha256=hashlib.sha256(incomplete.read_bytes()).hexdigest(),
        )

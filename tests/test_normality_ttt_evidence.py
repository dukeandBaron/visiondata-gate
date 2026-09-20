"""Frozen proxy evidence is a bounded engineering result, not a factory metric."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_real_proxy_summary_keeps_positive_negative_and_current_engine_identity():
    evidence = json.loads(
        (ROOT / "benchmarks/NORMALITY_TTT_LOCAL_20260919.json").read_text(encoding="utf-8")
    )
    implementation = hashlib.sha256(
        (ROOT / "src/visiondata_gate/normality_ttt.py").read_bytes()
    ).hexdigest()
    positive, negative = evidence["positive"], evidence["negative"]
    assert positive["implementation_sha256"] == negative["implementation_sha256"] == implementation
    assert positive["status"] == "ACCEPTED_EPISODIC"
    assert positive["steps_completed"] == 3
    assert positive["objective_after"] < positive["objective_before"]
    assert positive["parameter_sha256_before"] != positive["parameter_sha256_after"]
    assert positive["guard_before"] == positive["guard_after"]
    assert sum(positive["guard_before"].values()) == 16
    assert positive["guard_before"]["fn"] == 3 and positive["guard_before"]["fp"] == 2
    assert negative["status"] == "ROLLED_BACK"
    assert negative["rollback_reason"] == "TTT_GUARD_BASELINE_UNQUALIFIED"
    assert negative["steps_completed"] == 0
    assert negative["objective_before"] is None and negative["objective_after"] is None
    assert sum(negative["guard_before"].values()) == 2
    assert negative["guard_before"]["fn"] == 1
    for result in (positive, negative):
        assert result["backbone_sha256_before"] == result["backbone_sha256_after"]
        assert result["parent_pack_unchanged"] and result["thresholds_unchanged"]
        assert not result["persistent_learning"]
    assert not any(evidence["limits"].values())
    assert evidence["followup"]["work_order_status"] == "OPEN"
    assert "NOT defect truth" in evidence["followup"]["annotation_provenance"]


def test_current_docs_no_longer_call_connected_normality_interfaces_unimplemented():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme == (ROOT / "docs/PUBLIC_REPOSITORY_README.md").read_text(encoding="utf-8")
    assert "单次自监督适应" in readme and "尚未证明检测质量提升" in readme
    for path in ("README.md", "docs/LIVE_REPRODUCTION.md", "docs/CAPABILITY_STATUS.md"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "热图目前只展示工件摘要" not in text
        assert "反馈持久化尚未连接" not in text

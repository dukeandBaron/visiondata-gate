"""Public packaging inputs remain exact synthetic assets, not internal reports."""

from pathlib import Path

import pytest

from tools import check_public_repository as checker
from tools import export_public_repository as exporter


def test_reviewed_synthetic_resources_are_exact_and_shared():
    assert checker.REVIEWED_SYNTHETIC_SHA256 == exporter.REVIEWED_SYNTHETIC_SHA256
    assert len(checker.REVIEWED_SYNTHETIC_SHA256) == 2
    root = Path(__file__).resolve().parents[1]
    for relative in checker.REVIEWED_SYNTHETIC_SHA256:
        assert exporter._selected(relative)
        assert checker._path_violations([relative]) == []
        data = (root / relative).read_bytes()
        assert checker._content_violations(data, path=relative) == []
        assert any(
            v["rule"] == "reviewed-synthetic-resource-drift"
            for v in checker._content_violations(data + b" ", path=relative)
        )


@pytest.mark.parametrize(
    "relative",
    [
        "10_reports/private.json",
        "10_reports/nested/report.json",
        "gateway/target/private.jar",
        "gateway/runtime/java.exe",
        "output/SOURCE_MANIFEST.json",
        ".env.local",
    ],
)
def test_public_delivery_still_rejects_internal_data(relative):
    assert not exporter._selected(relative)
    assert checker._path_violations([relative])


def test_java_and_citation_are_text_not_unreviewed_binary():
    assert {".java", ".cff"} <= checker.PUBLIC_TEXT_SUFFIXES
    assert exporter._selected("gateway/pom.xml")
    assert exporter._selected("gateway/src/main/java/example/Test.java")


def test_export_rejects_changed_synthetic_resource(tmp_path, monkeypatch):
    relative = next(iter(exporter.REVIEWED_SYNTHETIC_SHA256))
    source = tmp_path / "source"
    target = source / relative
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(exporter, "PROJECT_ROOT", source)
    with pytest.raises(exporter.PublicExportError, match="digest changed"):
        exporter._copy_files(tmp_path / "destination", [relative])

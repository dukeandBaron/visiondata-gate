"""Public source must not contain a workstation-specific browser module path."""

import json
from pathlib import Path
import re

import pytest

from tools.check_public_repository import (
    _content_violations,
    _report_path_and_findings,
)


ROOT = Path(__file__).resolve().parents[1]
BROWSER_FILES = (
    "web_control_surfaces.browser.mjs",
    "web_data_pool.browser.mjs",
    "web_identity.browser.mjs",
    "web_identity_live.browser.mjs",
    "web_learning_loop.browser.mjs",
    "web_provider_center.browser.mjs",
    "web_start_surfaces.browser.mjs",
    "web_vision_model_workbench.browser.mjs",
)


@pytest.mark.parametrize("drive", ("C", "D", "F", "d"))
@pytest.mark.parametrize("separator", ("/", "\\", "\\\\"))
def test_mjs_rejects_private_users_paths_on_every_drive(drive, separator):
    # Assemble synthetic identities; do not introduce private-looking literals
    # into the repository merely to test the publication boundary.
    private = drive + ":" + separator + "Users" + separator + "case-operator"
    private += separator + ".npm-cache" + separator + "module.mjs"
    content = ("const modulePath = " + json.dumps(private) + ";").encode()
    findings = _content_violations(content, path="tests/fixture.browser.mjs")
    assert {"rule": "private-windows-path", "path": "tests/fixture.browser.mjs"} in findings
    assert "case-operator" not in json.dumps(findings)


@pytest.mark.parametrize("drive", ("C", "D", "F"))
def test_legitimate_source_program_files_and_synthetic_fixtures_stay_allowed(drive):
    for tail in ("/Program Files/Browser/browser.exe", "/synthetic-private/python.exe"):
        content = ("const fixture = " + json.dumps(drive + ":" + tail) + ";").encode()
        assert _content_violations(content, path="tests/fixture.browser.mjs") == []
    placeholder = ("root=" + drive + ":/authorized-data/images").encode()
    assert _content_violations(placeholder, path="docs/example.md") == []


@pytest.mark.parametrize("drive", ("C", "D", "F"))
@pytest.mark.parametrize("user", ("example-user", "operator-name", "placeholder"))
def test_users_root_is_not_exempted_by_placeholder_markers(drive, user):
    private = drive + ":" + "/Users/" + user + "/module.mjs"
    findings = _content_violations(private.encode(), path="tests/fixture.browser.mjs")
    assert any(row["rule"] == "private-windows-path" for row in findings)


@pytest.mark.parametrize("drive", ("C", "D", "F"))
def test_private_path_in_report_location_is_redacted(drive):
    private = drive + ":" + "/Users/" + "case-operator/module.mjs"
    report_path, findings = _report_path_and_findings(private, label="tracked-path")
    assert report_path == "tracked-path"
    assert findings
    assert "case-operator" not in json.dumps(findings)


@pytest.mark.parametrize("drive", ("C", "D", "F"))
@pytest.mark.parametrize("user", ("合成人员", "---"))
def test_private_user_root_does_not_depend_on_ascii_word_boundary(drive, user):
    private = drive + ":" + "/Users/" + user
    for text in (private, "const root = " + json.dumps(private, ensure_ascii=False) + ";"):
        findings = _content_violations(text.encode(), path="tests/fixture.browser.mjs")
        assert any(row["rule"] == "private-windows-path" for row in findings)


def test_users_directory_without_a_user_identity_is_not_a_private_source_path():
    parent = "D:" + "/Users/"
    assert _content_violations(
        ("const root = " + json.dumps(parent) + ";").encode(),
        path="tests/fixture.browser.mjs",
    ) == []


@pytest.mark.parametrize("filename", BROWSER_FILES)
def test_browser_module_resolution_is_explicit_or_project_local(filename):
    source = (ROOT / "tests" / filename).read_text(encoding="utf-8")
    if re.search(r"(?i)\b[A-Z]:[\\/]+Users[\\/]", source) or ".npm-cache" in source:
        pytest.fail("browser module resolution embeds a private user path", pytrace=False)
    if not re.search(
        r"process\.env\.VDG_PLAYWRIGHT_MODULE\s*\|\|\s*"
        r"(?:require|requireWeb)\.resolve\(['\"]playwright['\"]\)",
        source,
    ):
        pytest.fail("browser module must use explicit or project-local resolution", pytrace=False)

"""Deterministic submission packaging and hostile-archive auditing."""

from __future__ import annotations

import io
import json
import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .evidence import canonical_json_bytes, sha256_bytes, sha256_file
from .release import (
    DEFAULT_RELEASE_RELATIVE_DIR,
    RELEASE_MANIFEST_FILENAME,
    ReleaseValidationError,
    validate_submission_release_members,
)


ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o644
MANIFEST_NAME = "submission_manifest.json"
MANIFEST_SCHEMA = "visiondata-gate.submission-manifest.v1"
DEFAULT_MAX_FILE_SIZE = 128 * 1024 * 1024
DEFAULT_MAX_TOTAL_SIZE = 256 * 1024 * 1024

DEFAULT_EXCLUDED_PARTS = frozenset(
    {
        ".eggs",
        ".git",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".playwright-cli",
        ".ruff_cache",
        ".tox",
        ".venv",
        ".vscode",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
        "output",
        "playwright-report",
        "release",
        "temp",
        "test-results",
        "tmp",
    }
)
DEFAULT_EXCLUDED_SUFFIXES = frozenset(
    {
        ".db",
        ".log",
        ".pyc",
        ".pyo",
        ".sqlite",
        ".sqlite3",
        ".tmp",
        ".tsbuildinfo",
        ".zip",
    }
)

# Curated final materials are package inputs; superseded media, rendered slide
# previews, browser evidence, and local QA harnesses remain available in the
# workspace but must not silently enter a submission candidate.
SUBMISSION_DELIVERABLE_ALLOWLIST = frozenset(
    {
        "deliverables/GOAI_VisionDataGate_Semifinal_RC3_20260831.pptx",
        "deliverables/GOAI_VisionDataGate_Semifinal_RC3_20260831.pdf",
        "deliverables/VisionDataGate_GOAI_Semifinal_RC3_20260831.mp4",
        "deliverables/_qa/semifinal_rc3_video_contact_sheet_20260831.png",
        "deliverables/_qa/semifinal_rc3_video_qa_20260831.json",
    }
)
SUBMISSION_REPORT_ALLOWLIST = frozenset(
    {
        "10_reports/DYNAMICBENCH_V2_WORKER_SELECTION_20260828.json",
        "10_reports/DYNAMICBENCH_V3_REPLANNING_20260829.json",
        "10_reports/DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json",
        "10_reports/dynamic_vs_fixed_exhaustive_paired_comparison.json",
        "10_reports/dynamic_vs_fixed_rule_paired_comparison.json",
    }
)
SUBMISSION_DOC_EXCLUDELIST = frozenset(
    {
        "docs/AGENT_EVALUATION_TOOLS_20260823.md",
        "docs/GOAI_live_alignment_20260810.md",
        "docs/GOAI_material_alignment_20260812.md",
        "docs/GOAI_REVIEWER_FEEDBACK_AUDIT_20260812.md",
        "docs/LONGCAT_AGENT_RESEARCH.md",
        "docs/RC3_RUNTIME_PERFORMANCE_AUDIT_20260828.md",
    }
)
SUBMISSION_HISTORICAL_PREFIXES = (
    ".streamlit/",
    "07_results/",
    "evidence/submission/vdg-20260816-rc1/",
    "reviewer_workbench/",
    "web/src-tauri/gen/",
    "website/",
)
SUBMISSION_HISTORICAL_EXACT_PATHS = frozenset(
    {
        "app.py",
        "docs/00_OVERVIEW.md",
        "docs/OMNI_CAPA_RC3_RESULT.md",
        "docs/WORKTREE_EVIDENCE_NAMESPACE_20260825.md",
        "docs/assets/reviewer-mode.png",
        "docs/demo_script_2m50s.md",
        "run_app.ps1",
        "run_demo.ps1",
        "src/visiondata_gate/reviewer_server.py",
        "tests/test_app_source.py",
        "tests/test_release_artifacts.py",
        "tests/test_reviewer_scenario_suite.py",
        "tests/test_reviewer_server.py",
        "tests/test_submission_release.py",
        "tests/test_website_data.py",
        "tools/build_reviewer_scenario_suite.py",
        "tools/build_submission_release.py",
        "tools/check_release_assets.py",
        "tools/check_release_consistency.py",
        "tools/check_website_data.py",
    }
)
CURRENT_GOAL3_PUBLIC_EVIDENCE_PATHS = (
    "evidence/submission/vdg-20260831-rc3/goal3/goal3_acceptance_summary.json",
    "evidence/submission/vdg-20260831-rc3/goal3/worker_selection_receipt.json",
    "evidence/submission/vdg-20260831-rc3/goal3/incident_interaction_receipt.json",
    "evidence/submission/vdg-20260831-rc3/goal3/semifinal_demo_manifest.json",
    "evidence/submission/vdg-20260831-rc3/goal3/review_projection_negative_ui_summary.json",
    "evidence/submission/vdg-20260831-rc3/goal3/screenshots/01-review-main.png",
    "evidence/submission/vdg-20260831-rc3/goal3/screenshots/02-authority-case.png",
    "evidence/submission/vdg-20260831-rc3/goal3/screenshots/03-missing-reason-codes.png",
    "evidence/submission/vdg-20260831-rc3/goal3/screenshots/04-bad-agent-behavior-sha.png",
    "evidence/submission/vdg-20260831-rc3/goal3/screenshots/05-bad-strong-etag.png",
    "evidence/submission/vdg-20260831-rc3/goal3/screenshots/06-network-interruption.png",
    "evidence/submission/vdg-20260831-rc3/goal3/screenshots/07-stale-retention.png",
)

SUBMISSION_RC3_EVIDENCE_ALLOWLIST = frozenset(
    {
        "evidence/submission/vdg-20260831-rc3/README.md",
        "evidence/submission/vdg-20260831-rc3/evidence_index.json",
        *CURRENT_GOAL3_PUBLIC_EVIDENCE_PATHS,
    }
)

CURRENT_WEB_WORKBENCH_REQUIRED_PATHS = (
    "web/.env.example",
    "web/index.html",
    "web/package-lock.json",
    "web/package.json",
    "web/public/favicon.svg",
    "web/README.md",
    "web/src-tauri/build.rs",
    "web/src-tauri/capabilities/default.json",
    "web/src-tauri/Cargo.lock",
    "web/src-tauri/Cargo.toml",
    "web/src-tauri/icons/128x128.png",
    "web/src-tauri/icons/128x128@2x.png",
    "web/src-tauri/icons/32x32.png",
    "web/src-tauri/icons/64x64.png",
    "web/src-tauri/icons/icon.ico",
    "web/src-tauri/icons/icon.png",
    "web/src-tauri/icons/Square107x107Logo.png",
    "web/src-tauri/icons/Square142x142Logo.png",
    "web/src-tauri/icons/Square150x150Logo.png",
    "web/src-tauri/icons/Square284x284Logo.png",
    "web/src-tauri/icons/Square30x30Logo.png",
    "web/src-tauri/icons/Square310x310Logo.png",
    "web/src-tauri/icons/Square44x44Logo.png",
    "web/src-tauri/icons/Square71x71Logo.png",
    "web/src-tauri/icons/Square89x89Logo.png",
    "web/src-tauri/icons/StoreLogo.png",
    "web/src-tauri/src/lib.rs",
    "web/src-tauri/src/main.rs",
    "web/src-tauri/tauri.conf.json",
    "web/src/agentDomain.ts",
    "web/src/App.tsx",
    "web/src/capaDomain.ts",
    "web/src/components/AppShell.tsx",
    "web/src/components/BrandMark.tsx",
    "web/src/components/CausalReplay.tsx",
    "web/src/components/ControlledCapaWorkbench.tsx",
    "web/src/components/DatasetImportDialog.tsx",
    "web/src/components/EvaluationEvidencePanel.tsx",
    "web/src/components/IncidentInteractionTimeline.tsx",
    "web/src/components/IncidentReviewProjectionPanel.tsx",
    "web/src/components/InteractiveImageCanvas.tsx",
    "web/src/components/LiveIncidentWorkbench.tsx",
    "web/src/components/OperatorAgentPanel.tsx",
    "web/src/components/OperatorWorkspaceTour.tsx",
    "web/src/components/ProviderCenter.tsx",
    "web/src/components/ReviewInteractionBridge.tsx",
    "web/src/components/ReviewSyntheticAssetProof.tsx",
    "web/src/components/SemifinalManifestEvidence.tsx",
    "web/src/components/TaskVisualEvidencePanel.tsx",
    "web/src/components/ui.tsx",
    "web/src/components/visuals.tsx",
    "web/src/data/api.ts",
    "web/src/data/capaApi.ts",
    "web/src/data/capaIntegrity.ts",
    "web/src/data/evaluationEvidenceApi.ts",
    "web/src/data/fixtures.ts",
    "web/src/data/integrationCatalog.ts",
    "web/src/data/jcs.ts",
    "web/src/data/semifinalManifestApi.ts",
    "web/src/datasetImport.ts",
    "web/src/domain.ts",
    "web/src/evaluationEvidenceDomain.ts",
    "web/src/governanceDomain.ts",
    "web/src/interfacePreferences.ts",
    "web/src/localProfile.ts",
    "web/src/main.tsx",
    "web/src/operatorDomain.ts",
    "web/src/pages/AccountPage.tsx",
    "web/src/pages/CapaPage.tsx",
    "web/src/pages/CasesPage.tsx",
    "web/src/pages/CaseWorkbenchPage.tsx",
    "web/src/pages/CommandCenterPage.tsx",
    "web/src/pages/EvidencePage.tsx",
    "web/src/pages/GovernancePage.tsx",
    "web/src/pages/HomePage.tsx",
    "web/src/pages/ImageWorkspacePage.tsx",
    "web/src/pages/IntegrationsPage.tsx",
    "web/src/pages/LineagePage.tsx",
    "web/src/pages/NotFoundPage.tsx",
    "web/src/pages/ReviewPage.tsx",
    "web/src/pages/RunsPage.tsx",
    "web/src/pages/SettingsPage.tsx",
    "web/src/platform/bridge.ts",
    "web/src/ProductContext.tsx",
    "web/src/semifinalManifestDomain.ts",
    "web/src/styles/capa-delivery.css",
    "web/src/styles/evaluation-evidence.css",
    "web/src/styles/hosted-agentteams.css",
    "web/src/styles/incident-interaction.css",
    "web/src/styles/incident-review-projection.css",
    "web/src/styles/index.css",
    "web/src/styles/semifinal-manifest.css",
    "web/src/styles/tokens.css",
    "web/src/visualEvidenceDomain.ts",
    "web/src/vite-env.d.ts",
    "web/tsconfig.app.json",
    "web/tsconfig.json",
    "web/tsconfig.node.json",
    "web/vite.config.ts",
)

CURRENT_DESKTOP_AND_SAMPLE_REQUIRED_PATHS = (
    ".env.example",
    "build_windows_installer.ps1",
    "desktop/backend_main.py",
    "desktop/visiondata_gate_backend.spec",
    "run_guided_demo.ps1",
    "run_web.ps1",
    "run_workbench.ps1",
    "sample_data/README.md",
    "sample_data/SHA256SUMS.txt",
    "sample_data/clear/clean-test-bearing.png",
    "sample_data/clear/clean-val-bearing.png",
    "sample_data/clear/clean-val-gear.png",
    "sample_data/quality_anomalies/q-blur.png",
    "sample_data/quality_anomalies/q-overexposed.png",
    "sample_data/quality_anomalies/q-underexposed.png",
    "src/visiondata_gate/desktop_backend.py",
    "src/visiondata_gate/semifinal_manifest.py",
    "tests/test_desktop_packaging.py",
    "tests/test_goal1_review_projection_ui.py",
    "tests/test_operator_snapshot_source.py",
    "tests/test_operator_workspace.py",
    "tests/test_provider_profiles.py",
    "tests/test_semifinal_demo.py",
    "tests/test_semifinal_manifest_projection.py",
    "tools/check_semifinal_review_ui.mjs",
    "tools/import_local_env.ps1",
    "tools/prepare_semifinal_demo.py",
    "tools/smoke_windows_sidecar.py",
    "tools/verify_semifinal_demo_manifest.py",
)

CURRENT_RC3_MATERIAL_REQUIRED_PATHS = (
    "10_reports/DYNAMICBENCH_V2_WORKER_SELECTION_20260828.json",
    "10_reports/DYNAMICBENCH_V3_REPLANNING_20260829.json",
    "10_reports/DYNAMICBENCH_V4_PRODUCT_RUNTIME_20260829.json",
    "10_reports/dynamic_vs_fixed_exhaustive_paired_comparison.json",
    "10_reports/dynamic_vs_fixed_rule_paired_comparison.json",
    "deliverables/GOAI_VisionDataGate_Semifinal_RC3_20260831.pdf",
    "deliverables/GOAI_VisionDataGate_Semifinal_RC3_20260831.pptx",
    "deliverables/VisionDataGate_GOAI_Semifinal_RC3_20260831.mp4",
    "deliverables/_qa/semifinal_rc3_video_contact_sheet_20260831.png",
    "deliverables/_qa/semifinal_rc3_video_qa_20260831.json",
    "docs/DEMO_90S_SCRIPT_RC3.md",
    "docs/GOAI_SEMIFINAL_OFFICIAL_FEEDBACK_CLOSURE_20260831.md",
    "evidence/submission/vdg-20260831-rc3/README.md",
    "evidence/submission/vdg-20260831-rc3/evidence_index.json",
    *CURRENT_GOAL3_PUBLIC_EVIDENCE_PATHS,
)

DEFAULT_SUBMISSION_REQUIRED_PATHS = (
    "LICENSE",
    "NOTICE",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    *CURRENT_WEB_WORKBENCH_REQUIRED_PATHS,
    *CURRENT_DESKTOP_AND_SAMPLE_REQUIRED_PATHS,
    *CURRENT_RC3_MATERIAL_REQUIRED_PATHS,
    "01_planner/PROJECT_SPEC.md",
    "src/visiondata_gate/contracts.py",
    "src/visiondata_gate/agentteams_contract.py",
    "src/visiondata_gate/agentteams_v122.py",
    "src/visiondata_gate/runtime_models.py",
    "src/visiondata_gate/knowledge.py",
    "src/visiondata_gate/agent_core.py",
    "src/visiondata_gate/agent_runtime.py",
    "src/visiondata_gate/runtime_canvas.py",
    "src/visiondata_gate/product_models.py",
    "src/visiondata_gate/task_store.py",
    "src/visiondata_gate/product_runs.py",
    "src/visiondata_gate/product_service.py",
    "src/visiondata_gate/omni_adapter.py",
    "src/visiondata_gate/api.py",
    "src/visiondata_gate/proof.py",
    "src/visiondata_gate/evidence.py",
    "src/visiondata_gate/evidence_state_contracts.py",
    "src/visiondata_gate/evidence_state.py",
    "src/visiondata_gate/evaluation_contracts.py",
    "src/visiondata_gate/reporting.py",
    "src/visiondata_gate/release.py",
    "src/visiondata_gate/release_attestation.py",
    "src/visiondata_gate/release_evidence.py",
    "src/visiondata_gate/reviewer_canvas.py",
    "src/visiondata_gate/package.py",
    "src/visiondata_gate/goal3_public_evidence.py",
    "src/visiondata_gate/demo_fixtures.py",
    "src/visiondata_gate/dynamic_benchmark_v3.py",
    "src/visiondata_gate/runtime_safety.py",
    "src/visiondata_gate/capa.py",
    "src/visiondata_gate/incident_interaction.py",
    "src/visiondata_gate/governance_effectiveness_v2.py",
    "src/visiondata_gate/benchmarks/__init__.py",
    "src/visiondata_gate/benchmarks/dynamic_benchmark_v4.py",
    "src/visiondata_gate/industrial_incident.py",
    "src/visiondata_gate/industrial_incident_benchmark.py",
    "src/visiondata_gate/incident_commands.py",
    "src/visiondata_gate/incident_control_plane.py",
    "src/visiondata_gate/incident_model_planner.py",
    "src/visiondata_gate/network_resilience.py",
    "src/visiondata_gate/site_pack.py",
    "src/visiondata_gate/governed_context.py",
    "src/visiondata_gate/multimodal_advisor.py",
    "src/visiondata_gate/approved_experience.py",
    "src/visiondata_gate/incident_decision_packet.py",
    "src/visiondata_gate/worker_selection.py",
    "src/visiondata_gate/rc3_acceptance.py",
    "tests/test_evidence_package.py",
    "tests/test_agent_core.py",
    "tests/test_evidence_state.py",
    "tests/test_evaluation_contracts.py",
    "tests/test_worker_selection.py",
    "tests/test_task_store.py",
    "tests/test_product_service.py",
    "tests/test_product_service_real.py",
    "tests/test_api.py",
    "tests/test_industrial_incident.py",
    "tests/test_industrial_incident_benchmark.py",
    "tests/test_dynamic_benchmark_v3.py",
    "tests/test_runtime_safety.py",
    "tests/test_capa.py",
    "tests/test_incident_interaction.py",
    "tests/test_governance_effectiveness_v2.py",
    "tests/test_dynamic_benchmark_v4.py",
    "tests/test_incident_commands.py",
    "tests/test_incident_control_plane.py",
    "tests/test_incident_model_planner.py",
    "tests/test_incident_command_integration.py",
    "tests/test_site_pack.py",
    "tests/test_governed_context.py",
    "tests/test_multimodal_advisor.py",
    "tests/test_approved_experience.py",
    "tests/test_incident_decision_packet.py",
    "tests/test_rc3_acceptance.py",
    "tests/test_release_attestation.py",
    "tests/test_release_evidence.py",
    "tests/test_supply_chain_artifacts.py",
    "tests/test_proof.py",
    "tools/build_submission_package.py",
    "tools/build_release_attestation.py",
    "tools/build_rc3_candidate.py",
    "tools/build_rc3_release_evidence.py",
    "tools/verify_release_attestation.py",
    "tools/audit_submission_package.py",
    "tools/generate_supply_chain_artifacts.py",
    "tools/agentteams_v122_bridge.py",
    "tools/api_smoke.py",
    "tools/run_rc3_acceptance.py",
    "tools/run_dynamic_benchmark_v3.py",
    "tools/run_dynamic_benchmark_v4.py",
    "run_api.ps1",
    "setup_env.ps1",
    "docs/PROJECT_STATUS.md",
    "docs/EVIDENCE_AND_BENCHMARKS.md",
    "docs/DYNAMICBENCH_V3.md",
    "docs/DYNAMICBENCH_V4.md",
    "docs/GOVERNED_AUDIT_ENVELOPE.md",
    "docs/RELEASE_ATTESTATION_V1.md",
    "docs/GOAI_COMPETITION_EVALUATION.md",
    "docs/COMPETITOR_PRODUCT_PATTERNS.md",
    "docs/DEMO_AND_PRESENTATION_STRATEGY.md",
    "docs/OPEN_REUSE_CONTRACTS.md",
    "docs/INDUSTRY_SCENARIO_VALUE.md",
    "docs/submission_form_copy.md",
    "docs/one_pager.md",
    "docs/BOUNDLESS_AGENTS_TECHNICAL_ROUTE.md",
    "docs/CLAIM_SCOPE.md",
    "docs/RUNNING.md",
    "docs/API_QUICKSTART.md",
    "docs/RC3_DELIVERY_CONTRACT.md",
    "docs/SUBMISSION_CHECKLIST.md",
    "docs/data_privacy_license_boundaries.md",
    "docs/GOAI_requirements_matrix.md",
    "docs/AGENTTEAMS_ALIGNMENT.md",
    "docs/AGENTTEAMS_V122_RUNBOOK.md",
    "docs/REVIEWER_SCENARIO_MATRIX.md",
    "docs/REVIEWER_READINESS_MATRIX.md",
    "docs/TOOLS_AND_MCP_CONTRACT.md",
    "agentteams/team.yaml",
    "agentteams/identities.yaml",
    "agentteams/run.yaml",
    "agentteams/runtime_receipt.template.json",
    "tools/tool_lock.json",
    "skills/manifest.json",
    "skills/contract-intake/SKILL.md",
    "skills/parallel-evidence-audit/SKILL.md",
    "skills/evidence-grounded-council/SKILL.md",
    "skills/fail-closed-policy/SKILL.md",
    "skills/reserve-repair-recheck/SKILL.md",
    "src/visiondata_gate/reviewer_audit.py",
    "tests/test_reviewer_audit.py",
    "tests/test_agentteams_v122.py",
    "examples/site_packs/factory_a_line_01/site_manifest.yaml",
    "examples/site_packs/factory_a_line_01/source_mapping.yaml",
    "examples/site_packs/factory_a_line_01/connector_profiles.yaml",
    "examples/site_packs/factory_a_line_01/policy_extensions.yaml",
    "examples/site_packs/factory_a_line_01/output_profile.yaml",
    "examples/site_packs/factory_a_line_01/approved_memory.jsonl",
    "examples/site_packs/factory_a_line_01/sample_record.json",
    "examples/site_packs/factory_b_cell_07/site_manifest.yaml",
    "examples/site_packs/factory_b_cell_07/source_mapping.yaml",
    "examples/site_packs/factory_b_cell_07/connector_profiles.yaml",
    "examples/site_packs/factory_b_cell_07/policy_extensions.yaml",
    "examples/site_packs/factory_b_cell_07/output_profile.yaml",
    "examples/site_packs/factory_b_cell_07/approved_memory.jsonl",
    "examples/site_packs/factory_b_cell_07/sample_record.json",
    "docs/TOOL_REPLAY_AND_MIGRATION.md",
    "docs/SBOM.cdx.json",
    "docs/THIRD_PARTY_LICENSE_INVENTORY.generated.md",
    "docs/THIRD_PARTY_NOTICES.md",
)

_STALE_SUBMISSION_TEXT = (
    "103 tests",
    "103 test",
    "143 passed",
    "Omni 尚未读取",
    "Omni/海康数据尚未读取",
    "赛道：`Agent Infra`",
    "参赛定位：GOAI Agent Infra",
    "当前作品应优先提交 **Agent Infra",
)

_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

_CREDENTIAL_PATTERNS = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
            re.IGNORECASE,
        ),
    ),
    (
        "openai_like_key",
        re.compile(r"(?<![A-Za-z0-9])(?:sk-|sk_|gsk_)[A-Za-z0-9][A-Za-z0-9_-]{19,}"),
    ),
    (
        "aws_access_key",
        re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    ),
    (
        "github_token",
        re.compile(
            r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"
        ),
    ),
    ("google_api_key", re.compile(r"(?<![A-Za-z0-9])AIza[A-Za-z0-9_-]{35}")),
    (
        "generic_secret_assignment",
        re.compile(
            r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password)\b"
            r"\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{20,}",
            re.IGNORECASE,
        ),
    ),
)

# Public candidates may contain a small number of explicit synthetic path
# placeholders. Every other absolute drive, UNC, WSL, home, or private mount
# path is treated as topology disclosure and fails closed.
_PRIVATE_PATH_PATTERNS = (
    (
        "windows_user_home",
        re.compile(
            r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]+Users[\\/]+"
            r"[^\\/\s`'\"<>]+(?:[\\/]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "posix_user_home",
        re.compile(
            r"(?:^|[\s`'\"(])/(?:home|Users)/[^/\s`'\"<>]+(?:/|$)",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "generic_windows_absolute_path",
        re.compile(
            r"(?<![A-Za-z0-9+.-])[A-Za-z]:[\\/]+"
            r"[^\r\n`'\"<>|?*]+",
            re.IGNORECASE,
        ),
    ),
    (
        "unc_path",
        re.compile(
            r"(?<![\\])\\\\[^\\/\s`'\"<>]+[\\/]+"
            r"[^\r\n`'\"<>|?*]+",
            re.IGNORECASE,
        ),
    ),
    (
        "wsl_mount_path",
        re.compile(
            r"(?:^|[\s`'\"(])/(?:mnt/[a-z]|run/desktop/mnt/host/[a-z])"
            r"(?:/[^\r\n\s`'\"<>]+)+",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "private_service_mount",
        re.compile(
            r"(?:^|[\s`'\"(])/(?:srv|data|opt|var/lib)/"
            r"[^\r\n\s`'\"<>]+(?:/[^\r\n\s`'\"<>]+)*",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
)

_SYNTHETIC_PATH_MARKERS = (
    "authorized-data",
    "absolute\\path",
    "absolute/path",
    "example-path",
    "placeholder-path",
    "<absolute-path>",
    "${data_root}",
)
_GENERIC_PRIVATE_PATH_LABELS = {
    "generic_windows_absolute_path",
    "unc_path",
    "wsl_mount_path",
    "private_service_mount",
}
_GENERIC_PRIVATE_PATH_SCANNED_SUFFIXES = {
    ".cfg",
    ".conf",
    ".csv",
    ".env",
    ".html",
    ".ini",
    ".json",
    ".jsonl",
    ".md",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class AuditIssue:
    code: str
    path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "detail": self.detail}


@dataclass(frozen=True)
class PackageFile:
    path: str
    size: int
    sha256: str

    def to_dict(self) -> dict[str, str | int]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class PackageBuildResult:
    zip_path: str
    zip_sha256: str
    entry_count: int
    files: tuple[PackageFile, ...]
    manifest: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "zip_path": self.zip_path,
            "zip_sha256": self.zip_sha256,
            "entry_count": self.entry_count,
            "files": [item.to_dict() for item in self.files],
            "manifest": self.manifest,
        }


@dataclass(frozen=True)
class PackageAuditResult:
    ok: bool
    zip_path: str
    zip_sha256: str | None
    entry_count: int
    verified_file_count: int
    clean_extract_verified: bool
    required_paths: tuple[str, ...]
    issues: tuple[AuditIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "zip_path": self.zip_path,
            "zip_sha256": self.zip_sha256,
            "entry_count": self.entry_count,
            "verified_file_count": self.verified_file_count,
            "clean_extract_verified": self.clean_extract_verified,
            "required_paths": list(self.required_paths),
            "issues": [issue.to_dict() for issue in self.issues],
        }


class PackageSecurityError(ValueError):
    """Raised when source material would create an unsafe submission package."""

    def __init__(self, issues: list[AuditIssue] | tuple[AuditIssue, ...]):
        self.issues = tuple(issues)
        summary = "; ".join(f"{issue.code}:{issue.path}" for issue in self.issues)
        super().__init__(f"submission packaging blocked: {summary}")


def validate_archive_path(name: str) -> str:
    """Return a normalized POSIX member path or raise on unsafe names."""

    if not name or "\x00" in name:
        raise ValueError("archive paths must be non-empty and contain no NUL")
    if "\\" in name:
        raise ValueError("archive paths must use forward slashes")
    if name.startswith(("/", "//")) or re.match(r"^[A-Za-z]:", name):
        raise ValueError("absolute and drive-qualified archive paths are forbidden")

    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("empty, dot, and parent path segments are forbidden")
    for part in parts:
        if any(ord(character) < 32 or character in '<>:"|?*' for character in part):
            raise ValueError(
                "archive path segments may not contain Windows-invalid characters"
            )
        if part.endswith((" ", ".")):
            raise ValueError("archive path segments may not end in spaces or dots")
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED_NAMES:
            raise ValueError("Windows reserved device names are forbidden")

    normalized = PurePosixPath(*parts).as_posix()
    if normalized != name:
        raise ValueError("archive path is not in canonical POSIX form")
    return normalized


def scan_bytes_for_credentials(path: str, data: bytes) -> list[AuditIssue]:
    """Find credential-like text without returning the suspected secret value."""

    if b"\x00" in data[:8192]:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []

    issues: list[AuditIssue] = []
    for label, pattern in _CREDENTIAL_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            issues.append(
                AuditIssue(
                    code="credential_pattern",
                    path=path,
                    detail=f"possible {label} at line {line}; matched value redacted",
                )
            )
    return issues


def scan_bytes_for_private_paths(path: str, data: bytes) -> list[AuditIssue]:
    """Find privacy-bearing local paths without returning the matched value."""

    if b"\x00" in data[:8192]:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []

    suffix = PurePosixPath(path).suffix.casefold()
    text_segments: list[tuple[str, int | None]] = [(text, None)]
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            text_segments = [(item, None) for item in _iter_json_strings(payload)]
    elif suffix == ".jsonl":
        decoded_lines: list[tuple[str, int | None]] = []
        structured = True
        for line_number, source_line in enumerate(text.splitlines(), start=1):
            if not source_line.strip():
                continue
            try:
                payload = json.loads(source_line)
            except json.JSONDecodeError:
                structured = False
                break
            decoded_lines.extend(
                (item, line_number) for item in _iter_json_strings(payload)
            )
        if structured:
            text_segments = decoded_lines

    issues: list[AuditIssue] = []
    for label, pattern in _PRIVATE_PATH_PATTERNS:
        if (
            label in _GENERIC_PRIVATE_PATH_LABELS
            and suffix not in _GENERIC_PRIVATE_PATH_SCANNED_SUFFIXES
        ):
            continue
        for segment, structured_line in text_segments:
            for match in pattern.finditer(segment):
                line = structured_line or segment.count("\n", 0, match.start()) + 1
                if label in _GENERIC_PRIVATE_PATH_LABELS:
                    line_start = segment.rfind("\n", 0, match.start()) + 1
                    line_end = segment.find("\n", match.end())
                    if line_end < 0:
                        line_end = len(segment)
                    source_line = segment[line_start:line_end].casefold()
                    if any(marker in source_line for marker in _SYNTHETIC_PATH_MARKERS):
                        continue
                issues.append(
                    AuditIssue(
                        code="private_path_pattern",
                        path=path,
                        detail=(
                            f"possible {label} at line {line}; matched value redacted"
                        ),
                    )
                )
    return issues


def _iter_json_strings(value: Any):
    """Yield decoded JSON keys and values for semantic privacy scanning."""

    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_json_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_strings(item)


def _should_exclude(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    normalized = path.as_posix()
    folded_parts = tuple(part.casefold() for part in path.parts)
    if folded_parts[:3] == ("web", "src-tauri", "target"):
        return True
    historical_exact = {item.casefold() for item in SUBMISSION_HISTORICAL_EXACT_PATHS}
    if normalized.casefold() in historical_exact:
        return True
    if any(
        normalized.casefold() == prefix.rstrip("/").casefold()
        or normalized.casefold().startswith(prefix.casefold())
        for prefix in SUBMISSION_HISTORICAL_PREFIXES
    ):
        return True
    if folded_parts[:3] == ("evidence", "submission", "vdg-20260831-rc3"):
        evidence_allowlist = {
            item.casefold() for item in SUBMISSION_RC3_EVIDENCE_ALLOWLIST
        }
        folded = normalized.casefold()
        if folded not in evidence_allowlist and not any(
            item.startswith(folded.rstrip("/") + "/") for item in evidence_allowlist
        ):
            return True
    if any(
        part in DEFAULT_EXCLUDED_PARTS or part.endswith(".egg-info")
        for part in folded_parts
    ):
        return True
    folded_name = path.name.casefold()
    if folded_name == MANIFEST_NAME.casefold():
        return True
    if folded_name.endswith(".inspect.ndjson"):
        return True
    if folded_name.endswith(".receipt.json"):
        return True
    if folded_name.endswith((".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm")):
        return True
    if folded_name == ".env" or folded_name.startswith(".env."):
        env_template_allowlist = {".env.example", "web/.env.example"}
        if normalized.casefold() not in env_template_allowlist:
            return True
    if folded_parts and folded_parts[0] == "deliverables":
        allowlist = {item.casefold() for item in SUBMISSION_DELIVERABLE_ALLOWLIST}
        allowed_prefixes = {
            item.casefold() + "/" for item in SUBMISSION_DELIVERABLE_ALLOWLIST
        }
        folded = normalized.casefold()
        if folded not in allowlist and not any(
            prefix.startswith(folded.rstrip("/") + "/") for prefix in allowed_prefixes
        ):
            return True
    if folded_parts and folded_parts[0] == "10_reports":
        allowlist = {item.casefold() for item in SUBMISSION_REPORT_ALLOWLIST}
        folded = normalized.casefold()
        if folded not in allowlist and not any(
            item.startswith(folded.rstrip("/") + "/") for item in allowlist
        ):
            return True
    if folded_parts and folded_parts[0] == "docs":
        exclude = {item.casefold() for item in SUBMISSION_DOC_EXCLUDELIST}
        if normalized.casefold() in exclude:
            return True
    # Browser screenshots frozen before the current product workspace/API
    # redesign remain useful locally for historical audit, but would create a
    # conflicting UI version inside the submission candidate. Current visual
    # proof is carried by the curated video and its technical QA pair.
    if (
        len(path.parts) >= 2
        and path.parts[0].casefold() == "09_assets"
        and path.parts[1].casefold().startswith("ui_qa_frozen_")
    ):
        return True
    # The unversioned reviewer suite is intentionally retained locally as the
    # audit sample that exposed a run-ID collision.  Submission candidates use
    # only the current ``_v3`` suite and must not package superseded evidence.
    if (
        len(path.parts) >= 2
        and path.parts[0].casefold() == "07_results"
        and path.parts[1].casefold()
        in {
            "reviewer_scenario_suite_20260812",
            "reviewer_scenario_suite_20260812_v2",
        }
    ):
        return True
    # QA runs are immutable receipts for local diagnosis, not submission
    # inputs.  Keep the stable video QA artifacts below ``deliverables/_qa``
    # while excluding timestamped run logs/manifests and browser traces.
    if (
        len(path.parts) >= 3
        and path.parts[0].casefold() == "deliverables"
        and path.parts[1].casefold() == "_qa"
        and path.parts[2].casefold().startswith("run_")
    ):
        return True
    return path.suffix.lower() in DEFAULT_EXCLUDED_SUFFIXES


def _is_symlink_or_junction(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(is_junction and is_junction(path))


def _source_files(
    source_dir: Path,
    output_zip: Path,
    *,
    max_file_size: int,
    max_total_size: int,
) -> dict[str, bytes]:
    root = source_dir.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    output_resolved = output_zip.resolve(strict=False)

    files: dict[str, bytes] = {}
    casefold_names: set[str] = set()
    total_size = 0
    source_issues: list[AuditIssue] = []

    candidates: list[Path] = []

    def raise_walk_error(error: OSError) -> None:
        raise error

    for current_text, dirnames, filenames in os.walk(
        root,
        topdown=True,
        onerror=raise_walk_error,
        followlinks=False,
    ):
        current = Path(current_text)
        kept_directories: list[str] = []
        for dirname in sorted(dirnames):
            directory = current / dirname
            relative = directory.relative_to(root).as_posix()
            if _should_exclude(relative):
                continue
            if _is_symlink_or_junction(directory):
                raise PackageSecurityError(
                    [
                        AuditIssue(
                            "symlink_source",
                            directory.as_posix(),
                            "symlinks and junctions are not packaged",
                        )
                    ]
                )
            kept_directories.append(dirname)
        dirnames[:] = kept_directories

        for filename in sorted(filenames):
            candidate = current / filename
            relative = candidate.relative_to(root).as_posix()
            if not _should_exclude(relative):
                candidates.append(candidate)

    for candidate in sorted(
        candidates,
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        if _is_symlink_or_junction(candidate):
            raise PackageSecurityError(
                [
                    AuditIssue(
                        "symlink_source",
                        candidate.as_posix(),
                        "symlinks and junctions are not packaged",
                    )
                ]
            )
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise PackageSecurityError(
                [
                    AuditIssue(
                        "source_escape",
                        candidate.as_posix(),
                        "resolved path escapes source",
                    )
                ]
            ) from exc
        if resolved == output_resolved or _should_exclude(relative):
            continue
        validate_archive_path(relative)
        folded = relative.casefold()
        if folded in casefold_names:
            raise PackageSecurityError(
                [
                    AuditIssue(
                        "casefold_collision",
                        relative,
                        "case-insensitive path collision",
                    )
                ]
            )
        casefold_names.add(folded)

        size = candidate.stat().st_size
        if size > max_file_size:
            raise PackageSecurityError(
                [
                    AuditIssue(
                        "file_too_large",
                        relative,
                        f"file exceeds {max_file_size} bytes",
                    )
                ]
            )
        total_size += size
        if total_size > max_total_size:
            raise PackageSecurityError(
                [
                    AuditIssue(
                        "package_too_large",
                        relative,
                        f"total exceeds {max_total_size} bytes",
                    )
                ]
            )
        data = candidate.read_bytes()
        source_issues.extend(scan_bytes_for_credentials(relative, data))
        source_issues.extend(scan_bytes_for_private_paths(relative, data))
        files[relative] = data

    if source_issues:
        raise PackageSecurityError(source_issues)
    if not files:
        raise ValueError("submission source contains no packageable files")
    return files


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=name, date_time=ZIP_EPOCH)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (stat.S_IFREG | FILE_MODE) << 16
    info.internal_attr = 0
    info.extra = b""
    info.comment = b""
    return info


def build_deterministic_zip(
    source_dir: str | Path,
    output_zip: str | Path,
    *,
    overwrite: bool = False,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    max_total_size: int = DEFAULT_MAX_TOTAL_SIZE,
) -> PackageBuildResult:
    """Build a byte-reproducible, uncompressed ZIP with an in-memory manifest."""

    source = Path(source_dir)
    output = Path(output_zip)
    if output.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing package: {output}")

    file_bytes = _source_files(
        source,
        output,
        max_file_size=max_file_size,
        max_total_size=max_total_size,
    )
    package_files = tuple(
        PackageFile(path=name, size=len(data), sha256=sha256_bytes(data))
        for name, data in sorted(file_bytes.items())
    )
    manifest: dict[str, Any] = {
        "algorithm": "SHA-256",
        "archive_format": {
            "compression": "stored",
            "file_mode": "0644",
            "timestamp": "1980-01-01T00:00:00",
        },
        "files": [item.to_dict() for item in package_files],
        "schema_version": MANIFEST_SCHEMA,
    }
    manifest_bytes = canonical_json_bytes(manifest)

    entries = dict(file_bytes)
    entries[MANIFEST_NAME] = manifest_bytes

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
        archive.comment = b""
        for name in sorted(entries):
            archive.writestr(_zip_info(name), entries[name])
    zip_bytes = buffer.getvalue()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(zip_bytes)
    return PackageBuildResult(
        zip_path=str(output.resolve()),
        zip_sha256=sha256_bytes(zip_bytes),
        entry_count=len(entries),
        files=package_files,
        manifest=manifest,
    )


def _append_issue(issues: list[AuditIssue], code: str, path: str, detail: str) -> None:
    issues.append(AuditIssue(code=code, path=path, detail=detail))


def _safe_required_paths(
    required_paths: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    normalized = [validate_archive_path(path) for path in required_paths]
    if len({path.casefold() for path in normalized}) != len(normalized):
        raise ValueError("required paths contain case-insensitive duplicates")
    return tuple(sorted(normalized))


def audit_submission_zip(
    zip_path: str | Path,
    *,
    required_paths: tuple[str, ...] | list[str] = (),
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    max_total_size: int = DEFAULT_MAX_TOTAL_SIZE,
) -> PackageAuditResult:
    """Audit structure, credentials, manifest, hashes, and a clean extraction."""

    archive_path = Path(zip_path)
    issues: list[AuditIssue] = []
    try:
        required = _safe_required_paths(required_paths)
    except ValueError as exc:
        required = ()
        _append_issue(issues, "invalid_required_path", "<arguments>", str(exc))

    if not archive_path.is_file():
        _append_issue(
            issues, "missing_zip", str(archive_path), "ZIP file does not exist"
        )
        return PackageAuditResult(
            ok=False,
            zip_path=str(archive_path.resolve(strict=False)),
            zip_sha256=None,
            entry_count=0,
            verified_file_count=0,
            clean_extract_verified=False,
            required_paths=required,
            issues=tuple(issues),
        )

    zip_digest = sha256_file(archive_path)
    entry_count = 0
    verified_count = 0
    clean_extract_verified = False
    member_data: dict[str, bytes] = {}
    infos_by_name: dict[str, zipfile.ZipInfo] = {}

    try:
        with zipfile.ZipFile(archive_path, mode="r") as archive:
            infos = archive.infolist()
            entry_count = len(infos)
            names = [info.filename for info in infos]
            if names != sorted(names):
                _append_issue(
                    issues, "entry_order", "<archive>", "entries are not sorted"
                )

            total_size = 0
            seen_casefold: set[str] = set()
            for info in infos:
                name = info.filename
                try:
                    validate_archive_path(name)
                except ValueError as exc:
                    _append_issue(issues, "unsafe_path", name, str(exc))
                    continue
                folded = name.casefold()
                if folded in seen_casefold:
                    _append_issue(
                        issues,
                        "duplicate_path",
                        name,
                        "duplicate or case-insensitive colliding member",
                    )
                    continue
                seen_casefold.add(folded)
                infos_by_name[name] = info

                if info.is_dir():
                    _append_issue(
                        issues, "directory_entry", name, "directories are not stored"
                    )
                    continue
                if info.flag_bits & 0x1:
                    _append_issue(
                        issues,
                        "encrypted_entry",
                        name,
                        "encrypted ZIP members are forbidden",
                    )
                if info.file_size > max_file_size:
                    _append_issue(
                        issues,
                        "file_too_large",
                        name,
                        f"uncompressed file exceeds {max_file_size} bytes",
                    )
                total_size += info.file_size
                if total_size > max_total_size:
                    _append_issue(
                        issues,
                        "package_too_large",
                        name,
                        f"uncompressed total exceeds {max_total_size} bytes",
                    )
                if info.compress_type != zipfile.ZIP_STORED:
                    _append_issue(
                        issues,
                        "compression_method",
                        name,
                        "deterministic submission entries must use stored compression",
                    )
                if info.date_time != ZIP_EPOCH:
                    _append_issue(
                        issues, "timestamp", name, "ZIP timestamp is not frozen"
                    )
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(mode) == stat.S_IFLNK:
                    _append_issue(
                        issues, "symlink_entry", name, "symlink entries are forbidden"
                    )
                if stat.S_IMODE(mode) != FILE_MODE:
                    _append_issue(issues, "file_mode", name, "ZIP mode must be 0644")

                if info.file_size <= max_file_size and total_size <= max_total_size:
                    try:
                        data = archive.read(info)
                    except (RuntimeError, zipfile.BadZipFile) as exc:
                        _append_issue(issues, "read_error", name, type(exc).__name__)
                        continue
                    member_data[name] = data
                    issues.extend(scan_bytes_for_credentials(name, data))
                    issues.extend(scan_bytes_for_private_paths(name, data))
    except (OSError, zipfile.BadZipFile, NotImplementedError) as exc:
        _append_issue(issues, "invalid_zip", str(archive_path), type(exc).__name__)

    manifest_data = member_data.get(MANIFEST_NAME)
    manifest: dict[str, Any] | None = None
    if manifest_data is None:
        _append_issue(issues, "missing_manifest", MANIFEST_NAME, "manifest is required")
    else:
        try:
            parsed = json.loads(manifest_data.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("manifest root must be an object")
            manifest = parsed
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            _append_issue(issues, "invalid_manifest", MANIFEST_NAME, str(exc))
        if manifest is not None and canonical_json_bytes(manifest) != manifest_data:
            _append_issue(
                issues,
                "noncanonical_manifest",
                MANIFEST_NAME,
                "manifest bytes are not canonical JSON",
            )

    if manifest is not None:
        if manifest.get("schema_version") != MANIFEST_SCHEMA:
            _append_issue(
                issues, "manifest_schema", MANIFEST_NAME, "unexpected schema version"
            )
        if manifest.get("algorithm") != "SHA-256":
            _append_issue(
                issues, "manifest_algorithm", MANIFEST_NAME, "algorithm must be SHA-256"
            )
        file_records = manifest.get("files")
        declared: dict[str, tuple[int, str]] = {}
        if not isinstance(file_records, list):
            _append_issue(
                issues, "manifest_files", MANIFEST_NAME, "files must be a list"
            )
        else:
            for index, record in enumerate(file_records):
                if not isinstance(record, dict):
                    _append_issue(
                        issues,
                        "manifest_record",
                        MANIFEST_NAME,
                        f"record {index} is not an object",
                    )
                    continue
                name = record.get("path")
                size = record.get("size")
                digest = record.get("sha256")
                if (
                    not isinstance(name, str)
                    or not isinstance(size, int)
                    or isinstance(size, bool)
                    or size < 0
                    or not isinstance(digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)
                ):
                    _append_issue(
                        issues,
                        "manifest_record",
                        MANIFEST_NAME,
                        f"record {index} has invalid fields",
                    )
                    continue
                try:
                    validate_archive_path(name)
                except ValueError as exc:
                    _append_issue(issues, "manifest_path", name, str(exc))
                    continue
                if name == MANIFEST_NAME or name.casefold() in {
                    item.casefold() for item in declared
                }:
                    _append_issue(
                        issues, "manifest_duplicate", name, "duplicate manifest path"
                    )
                    continue
                declared[name] = (size, digest)

        actual_names = set(member_data) - {MANIFEST_NAME}
        declared_names = set(declared)
        for name in sorted(actual_names - declared_names):
            _append_issue(
                issues, "unmanifested_file", name, "file is absent from manifest"
            )
        for name in sorted(declared_names - actual_names):
            _append_issue(
                issues, "manifest_missing_file", name, "declared file is absent"
            )
        for name in sorted(actual_names & declared_names):
            expected_size, expected_digest = declared[name]
            data = member_data[name]
            if len(data) != expected_size:
                _append_issue(
                    issues, "size_mismatch", name, "size differs from manifest"
                )
                continue
            if sha256_bytes(data) != expected_digest:
                _append_issue(
                    issues, "hash_mismatch", name, "SHA-256 differs from manifest"
                )
                continue
            verified_count += 1

    available_names = set(member_data)
    for path in required:
        if path not in available_names:
            _append_issue(
                issues, "missing_required_file", path, "required file is absent"
            )

    release_manifest_member = (
        f"{DEFAULT_RELEASE_RELATIVE_DIR}/{RELEASE_MANIFEST_FILENAME}"
    )
    release_requested = release_manifest_member in available_names or any(
        path.startswith(DEFAULT_RELEASE_RELATIVE_DIR + "/") for path in required
    )
    if release_requested:
        try:
            validate_submission_release_members(
                member_data,
                release_root=DEFAULT_RELEASE_RELATIVE_DIR,
            )
        except ReleaseValidationError as exc:
            _append_issue(
                issues,
                "release_consistency",
                release_manifest_member,
                str(exc),
            )

    for name, data in sorted(member_data.items()):
        if name != "README.md" and not name.startswith(("docs/", "10_reports/")):
            continue
        if b"\x00" in data[:8192]:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for stale in _STALE_SUBMISSION_TEXT:
            if stale in text:
                _append_issue(
                    issues,
                    "stale_submission_claim",
                    name,
                    f"obsolete phrase is forbidden: {stale}",
                )

    # Only structurally clean packages are extracted. This avoids writing any
    # hostile archive member before every path and hash has been validated.
    if not issues and manifest is not None:
        with tempfile.TemporaryDirectory(prefix="visiondata-gate-audit-") as temp_dir:
            extract_root = Path(temp_dir).resolve()
            for name in sorted(member_data):
                destination = extract_root.joinpath(*PurePosixPath(name).parts)
                resolved = destination.resolve(strict=False)
                try:
                    resolved.relative_to(extract_root)
                except ValueError as exc:  # defensive; names were already validated
                    raise RuntimeError(
                        "validated archive path escaped extraction root"
                    ) from exc
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_bytes(member_data[name])

            extract_ok = True
            for record in manifest.get("files", []):
                extracted = extract_root.joinpath(*PurePosixPath(record["path"]).parts)
                if (
                    not extracted.is_file()
                    or sha256_file(extracted) != record["sha256"]
                ):
                    extract_ok = False
                    _append_issue(
                        issues,
                        "clean_extract_hash",
                        record["path"],
                        "clean extraction re-hash failed",
                    )
            for path in required:
                extracted = extract_root.joinpath(*PurePosixPath(path).parts)
                if not extracted.is_file():
                    extract_ok = False
                    _append_issue(
                        issues,
                        "clean_extract_required",
                        path,
                        "required file missing after clean extraction",
                    )
            clean_extract_verified = extract_ok

    issues.sort(key=lambda issue: (issue.code, issue.path, issue.detail))
    return PackageAuditResult(
        ok=not issues and clean_extract_verified,
        zip_path=str(archive_path.resolve()),
        zip_sha256=zip_digest,
        entry_count=entry_count,
        verified_file_count=verified_count,
        clean_extract_verified=clean_extract_verified,
        required_paths=required,
        issues=tuple(issues),
    )


__all__ = [
    "AuditIssue",
    "CURRENT_GOAL3_PUBLIC_EVIDENCE_PATHS",
    "DEFAULT_SUBMISSION_REQUIRED_PATHS",
    "FILE_MODE",
    "MANIFEST_NAME",
    "MANIFEST_SCHEMA",
    "PackageAuditResult",
    "PackageBuildResult",
    "PackageFile",
    "PackageSecurityError",
    "ZIP_EPOCH",
    "audit_submission_zip",
    "build_deterministic_zip",
    "scan_bytes_for_credentials",
    "scan_bytes_for_private_paths",
    "validate_archive_path",
]

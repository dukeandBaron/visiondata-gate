# External review: verification and implementation response

The supplied review was dated 2026-09-11 and inspected the public repository,
not the full local development tree. This response verifies its claims instead
of treating every suggested command, metric or publication action as established.
Scope: engineering safeguards, reproducibility and adoption; this is not a full
security audit or proof of industrial performance.

## Baseline checked before changes

- Public repository: `dukeandBaron/visiondata-gate`, `public`, default `main`.
- Observed public main commit: `88f77881f6ac3165b781535efb8957219df4dfcb`.
- Public CI blob: `b84203c6f04dcaa40b7fd9e13fc03f58443f3fb9` (Ubuntu-only Python).
- Public project metadata blob: `6c629f68451159169a89ee358ce06ffbcbf4c93f`.
- Local authority branch: `codex/facade-rc4`, dirty user/team work preserved.
  Its existing CI already checked Ubuntu and Windows with Python 3.12.
- Read-only GitHub API showed prereleases `v0.3.0-goai-rc3` (2026-09-01) and
  `v0.4.0-goai-semifinal-rc4` (2026-09-03), and existing repository topics.
- PyPI lookup returned HTTP 404 for `visiondata-gate`. No package was published
  or claimed available as a result of this review.

These observations bind the baseline, not a claim that uncommitted improvements
have reached GitHub. Popularity counters are not software-quality evidence.

## Point-by-point disposition

| Review item | Verified assessment | Implementation / boundary |
| --- | --- | --- |
| 1. Missing Python type check | Confirmed in the inspected public metadata/CI. Existing annotations do not prove full typing. | Add measured, explicit type-check scope and gate; do not advertise full-project strictness from a small subset. |
| 2. Ubuntu-only CI | Confirmed for public main; partly stale for authority CI, which already has Windows. Python-version coverage was still incomplete. | Align public/authority platform and Python 3.12/3.13 checks. Configuration is not proof those hosted jobs have run. |
| 3. No coverage gate | Confirmed. A 95% threshold is a proposed target, not existing evidence. | Measure real line/branch coverage and gate declared scope; broader unmeasured modules remain outside that claim. |
| 4. Missing security scanners | Confirmed for the inspected public workflow. Functional injection defenses are not a dependency/SAST scanner. | Add dependency/static/security automation with explicit failures and scope; no blanket security certification. |
| 5. Implicit Ruff defaults / no pre-commit | Confirmed. Enabling every suggested rule at once would produce unrelated churn. | Explicit configuration and contributor hooks, with tested incremental rules; preserve unrelated dirty code. |
| 6. No PyPI package | Confirmed by registry 404. | Prepare honest source/packaging instructions and publication checklist. Actual PyPI publication remains an explicit external step. |
| 7. PowerShell-only quickstart | Main adoption path was Windows-centric; the suggested `serve` command is not real. | Portable source launcher and tested CLI commands in [Quickstart](CROSS_PLATFORM_QUICKSTART.md). No authentication bypass. |
| 8. No changelog / releases / topics | Changelog missing; no-releases/no-topics claims are stale. Two prereleases and topics already exist. | Add [CHANGELOG](../CHANGELOG.md), retain historical artifact boundaries, do not create duplicate releases or inflate popularity. |
| 9. Flat package / versioned modules | Layout debt exists. Numbered benchmark/kernel modules often preserve different frozen protocols, not merely obsolete duplicates. | Document the supported API and compatibility surface. Do not mass-move modules or declare all older protocols deprecated. |
| 10. Four UIs | Overstated: Tauri hosts React and reviewer_server is a support service. Entry-point ambiguity is real. | [React is primary](INTERFACE_SUPPORT.md); mark Streamlit compatibility scope and distinguish wrappers/services/replay. |
| 11. Benchmark reproducibility / weak baseline | Self-authored benchmark bias is real. DynamicBench-v3 and the private VisA protocol are different experiments and cannot be conflated. | Provide a bounded public reproducible route and raw results with limitations; do not invent ReAct/LangGraph results or claim factory generalization. |
| 12. Injection metrics absent from README | Public-facing discoverability needs improvement; available evidence must be checked before adding numbers. | Publish only reproducible numerator/denominator and scope; attack rejection alone is not benign-input false-positive performance. |
| Root PowerShell scripts | Organization preference, not a correctness defect. Existing users and frozen scripts reference these paths. | Preserve compatibility entry points; add a portable alternative rather than move/delete them in this round. |
| NumPy upper bound | Tight pin is real; loosening it without compatibility/reproducibility tests is unsafe. | Explain the tested-version constraint; a later version expansion needs its own lock and regression evidence. |
| Audit timestamps / whole-chain rewrite | Valid concern. README already excludes signatures/trusted timestamps, but a focused threat explanation is useful. | Clarify digest integrity versus independent trusted anchors. Do not claim RFC 3161 or externally anchored history exists. |
| Documentation site | Useful later, not necessary to validate the current implementation. | Improve linked source documentation first; no additional hosting stack or public deployment is created here. |
| CITATION.cff | Missing metadata, straightforward to address. | Add [CITATION.cff](../CITATION.cff) with project contributors and repository URL; no invented DOI, affiliations or release version. |

## Verification and responsibility

Implemented quality commands, measured scopes and unresolved diagnostics are in
[Engineering quality implementation](ENGINEERING_QUALITY_IMPLEMENTATION.md).
The initial quality gaps now have executable workflows and local evidence;
the full-tree 95% target, broader type correctness and Bandit triage are not
claimed complete. Existing tests and benchmark denominators were not weakened.

Goal 1 owns adoption/UI-entry documentation, portable source startup and the
consolidated review. Goal 2 owns quality/CI/dependency tooling. Goal 3 owns
benchmark reproducibility, API boundaries and audit-trust documentation.
All work uses the existing contracts and native task coordination, not a new
agent runtime or shared orchestration framework.

The delivered test results and any remaining tool/platform HOLD belong in the
matching local delivery report. New configuration alone is not a test pass.
Public release gates, current-source tests, installed GUI, real industrial
effectiveness, CANN scheduling and production authority remain independent.

See [Release preparation](RELEASE_PREPARATION.md) before publishing source or
artifacts. No review recommendation authorizes exposing private history, samples,
tokens or local working records.

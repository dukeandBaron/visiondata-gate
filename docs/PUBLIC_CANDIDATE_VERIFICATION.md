# Public platform candidate verification — 2026-09-13

Status: **DRAFT_SOURCE_CANDIDATE / RELEASE_HOLD**. These results do not certify
an installed application, a customer workflow, model improvement or production.

| Check | Local result | Scope |
| --- | --- | --- |
| Backend platform contracts | 467 passed, 1 skipped | 21 modules, 468 unique cases; candidate package imports verified; no real model execution |
| Frontend contract tests | 92 passed | Node tests, including a real Python data-pool DTO roundtrip |
| Publication and adoption tests | 52 passed, 1 skipped | Allowlist, exact synthetic resource hashes, documentation and privacy controls |
| Web typecheck and local production build | PASS | 1916 transformed modules; not installed Tauri GUI |
| Public-static build and artifact privacy | PASS | 1843 transformed modules; 0 source maps, 0 privacy matches, 0 backend authority surfaces |
| Python correctness lint | PASS | Existing Ruff correctness rules, not a security certification |
| Markdown local links | PASS | Regenerated public manifest scope |
| Python formatting | **HOLD** | Nine frozen runtime files retain formatting debt |

The two skipped cases require symlink creation permission unavailable on the
local Windows test account. Separate Windows junction rejection checks passed.
Hosted Linux/Windows jobs are independently reported by GitHub; this document
does not declare hosted CI success before it runs.

The backend count is deduplicated: an initial run observed concurrent formatting
of six test files, so those six modules were rerun with stable before/after
hashes. It combines 328 passes and 1 skip from the unchanged 15 modules with
139 stable passes from the rerun. No production module changed during testing.

## Preserved frozen-source formatting debt

The independent formatting CI job remains blocking and reports its actual
nonzero result; it is not disabled, ignored or converted into a pass. The API
job can still report its own result. Files requiring a later coordinated
formatting/freeze cycle are:

- `src/visiondata_gate/api.py`
- `src/visiondata_gate/data_pool.py`
- `src/visiondata_gate/data_pool_api.py`
- `src/visiondata_gate/learning_evaluation.py`
- `src/visiondata_gate/learning_operations.py`
- `src/visiondata_gate/learning_service.py`
- `src/visiondata_gate/learning_yolo_backend.py`
- `src/visiondata_gate/local_workbench.py`
- `src/visiondata_gate/product_service.py`

## Installer source binding, not installer certification

[The source binding](INSTALLER_SOURCE_BINDING.json) lists 335 of 336 frozen
inputs for `windows-platform-rebuild-20260913-03`. Only the internal README is
replaced with the public project explanation. UTF-8 text permits Git LF newline
normalization; binary files use exact bytes. Original frozen SHA-256 and public
normalized SHA-256 are separate fields, not interchangeable claims.

The earlier `-02` native source compiled but NSIS packaging timed out while
trying to download a tool from an incorrectly resolved isolated cache path.
The `-03` source corrects that cache path and was sent to a fresh build. This
candidate is **not** evidence of successful NSIS packaging, installed GUI,
same-version upgrade, clean-machine execution, a code signature or a complete
Java/JRE supply-chain inventory. It does not upload a new release binary.

Detailed boundaries are in [Publication boundary](PUBLICATION_BOUNDARY.md) and
[Platform delivery](PLATFORM_DELIVERY_20260913.md). Raw local test logs, temporary
databases and private source manifests are not part of the public repository.

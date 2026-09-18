# Technical bundle subprocess review

Scope: `tools/build_finals_technical_bundle.py`; Bandit 1.9.4. The baseline remains Low-only and blocks every new unmatched Low/Medium/High finding. No `nosec`, scan-root exclusion, or workflow bypass is introduced.

The frozen baseline preserves previously reviewed records and adds only the two rows below. It is an incremental review inventory, not a replacement for the current full scanner report retained by CI.

| Rule | Disposition | Evidence and boundary |
| --- | --- | --- |
| B607 partial executable path | Hardened; not accepted into baseline | Resolve Git only from absolute external PATH directories. Reject relative/current/input-repository directories and repository-contained resolved executables. Pass an absolute executable to the process API. Missing trusted Git raises a closed failure. |
| B404 subprocess import | Reviewed Low baseline | Importing the standard module is not execution. The sole process helper is inspected below; this is not a remote service route. |
| B603 subprocess invocation | Reviewed Low baseline | Fixed internal read-only Git commands; input root is a separate `-C` argv value, not a shell fragment. `shell=False`, fsmonitor disabled, timeout 60 seconds. No data-derived command construction or automatic retry. |

Supported surface: explicit operator-run source packaging from a reviewed local checkout and trusted Git configuration. The external toolchain/PATH and Git configuration remain trusted operator inputs; this tool is not a sandbox for hostile Git configuration or an adversarial interpreter installation. Service APIs do not expose the process helper. This assessment does not certify all subprocess usage in the repository.

Regression evidence: `test_git_uses_external_absolute_executable_not_repository_or_cwd` and `test_git_refuses_only_repository_and_relative_search_paths`; the existing real Git snapshot, dirty-tree, SHA inventory, ZIP tamper and extraction tests remain the legitimate controls. The two remaining Low findings retain code-sensitive fingerprints in `bandit-baseline.json`; changed snippets or additional findings still fail CI.

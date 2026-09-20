# TTT reproduction tool subprocess review

Scope: `tools/run_normality_ttt_synthetic.py`, Bandit 1.9.4, 2026-09-19.
The previous 228 reviewed Low fingerprints are retained. Exactly two new
code-sensitive Low fingerprints are admitted; Medium/High and unmatched Low
findings still fail the gate. No suppression or scanner exclusion is introduced.

| Rule | Decision | Evidence |
| --- | --- | --- |
| B101 (11 occurrences) | Fixed, not baselined | Evidence checks now use explicit controlled failures, including under `python -O`; a missing acceptance, wrong guard result or changed parent cannot produce a successful receipt. Sixteen regression cases cover ordinary and optimized execution. |
| B404 | Reviewed Low | Standard subprocess import in an explicitly operator-run synthetic tool, not a service execution endpoint. |
| B603 | Reviewed Low | Same trusted `sys.executable`, fixed standalone entrypoint and argument vector, no shell, private temporary directory, allowlisted worker environment, 30-second timeout. No input-derived command string, network target or automatic retry. |

Admitted fingerprints:

```text
B404 9020d1289c2fadcc610b977603811352595d3c8a3c0530ad88c32477663ee880
B603 63675c05f4c54741b6dda7d57c0c1b34bcb4138967879117e95b7b8bc31e3471
```

Both ordinary and optimized Python executed the actual CPU synthetic experiment
with equal results apart from timing. The selected interpreter remains a trusted
operator input; this review does not claim an OS sandbox against hostile native
libraries or certify other subprocesses in the repository.

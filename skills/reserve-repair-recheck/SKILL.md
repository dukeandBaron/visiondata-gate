---
name: reserve-repair-recheck
description: Apply bounded reserve repairs, preserve originals and rerun the same contract for verification.
version: 1.0.0
owner: operator.repair
---

# Reserve Repair and Recheck

Execute only allowlisted work orders on a reserve copy, preserve the original
batch, then rerun the same contract and package the verification evidence.

## Input / output

Input: work orders, reserve manifest and original contract. Output: repaired
manifest, verification GateResult and evidence package.

## Failure and safety

Investigate-only orders, mismatched replacements or failed rechecks keep the
original batch untouched and remain pending human review. Production actions
are never executed by this Skill.

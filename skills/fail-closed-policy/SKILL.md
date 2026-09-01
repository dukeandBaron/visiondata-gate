---
name: fail-closed-policy
description: Apply frozen rules and emit the sole fail-closed GateDecision, RuleChecks and WorkOrders.
version: 1.0.0
owner: judge.policy
---

# Fail-Closed Policy Judge

Apply the frozen rule package, scenario governance thresholds and counterfactual
stability checks to typed findings and traces.

## Input / output

Input: findings, tool traces, council advisory trace and scenario profile.
Output: exactly one `GateDecision`, rule checks and bounded work orders.

## Failure and safety

Missing evidence, skipped required tools, tool drift or authorization gaps map
to `DEFER`, `RECAPTURE` or `BLOCKED`. Only this identity may write the release
decision; model text cannot replace a rule check.

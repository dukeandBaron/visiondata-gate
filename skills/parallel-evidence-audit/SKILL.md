---
name: parallel-evidence-audit
description: Dispatch bounded evidence Workers and return typed ToolTrace, Finding and metric artifacts.
version: 1.0.0
owner: leader.release-gate
---

# Parallel Evidence Audit

Dispatch independent workers through the allowlisted Tool Gateway and collect
typed `ToolTrace`, `Finding[]` and metrics under a bounded budget.

## Input / output

Input: validated context, tool lock and worker budget. Output: ordered tool
traces, finding IDs, evidence references and metric summary.

## Failure and safety

Tool error, permission denial, timeout or budget exhaustion produces `error` or
`skipped` trace and is passed to the fail-closed Policy Judge. Workers cannot
write decisions, contracts, arbitrary files or production systems.

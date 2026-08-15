---
name: contract-intake
description: Validate the release goal, manifest, contract, paths and scope before any Agent trusts the batch.
version: 1.0.0
owner: manager.gate
---

# Contract Intake

Validate the goal, `BatchManifest`, `BatchContract`, relative paths, input
digest and release scope before handing context to the Team Leader.

## Input

`goal`, `BatchManifest`, `BatchContract`, `scenario_profile`.

## Output

`input_sha256`, validated context, or a typed `DEFER` reason.

## Failure and safety

Schema errors, path traversal, missing files and production scope are fail
closed. This Skill is read-only and never grants production authorization.

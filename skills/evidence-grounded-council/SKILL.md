---
name: evidence-grounded-council
description: Produce citation-bound advisory interpretations and cross-examination without release authority.
version: 1.0.0
owner: reviewer.ai-council
---

# Evidence-Grounded Council Review

Produce role-scoped interpretations and cross-examination that cite executed
tool evidence. The shared backend disclosure is part of the output.

## Input / output

Input: findings, tool traces, bounded knowledge hits. Output: advisory
opinions, evidence references, limitations and unresolved objections.

## Failure and safety

Unreferenced claims, invalid model output or timeout trigger deterministic
fallback. Council output is advisory and cannot override measurements,
contracts or Policy Judge decisions.

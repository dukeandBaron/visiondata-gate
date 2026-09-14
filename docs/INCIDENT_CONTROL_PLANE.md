# Industrial Incident Control Plane v1

## Purpose

The control plane is an immutable sidecar for one
`visiondata-gate.industrial-incident-case.v3` record. It makes three questions
machine-verifiable without changing the existing case hash:

1. Which typed control-flow nodes and Workers actually participated?
2. Did a Worker still have publication authority when its receipt was accepted?
3. Why is the current disposition selected, why are unsafe alternatives rejected,
   and what evidence could change the decision?

The artifact is created for both root and resumed child cases at:

```text
<task-output>/industrial_incidents/<case-id>/control_plane.json
```

It is available through:

```http
GET /v1/tasks/{task_id}/industrial-incidents/{case_id}/control-plane
X-Actor-User-Id: <workspace member>
```

## 1. Typed plan tree

`TypedIncidentPlanTree` supports:

- `SEQUENCE`
- `PARALLEL`
- `FALLBACK`
- `GUARD`
- `INTERRUPT`
- `REVALIDATE`
- `WORKER`

Every Worker leaf binds the actual `invocation_id`, role, trigger reason codes and
receipt SHA-256. The tree also reconciles the frozen Worker budget. Its explicit
execution semantics are `OBSERVED_CASE_PROJECTION_V1`: it is an auditable view of
the execution that occurred, not a claim that the legacy runtime has already been
replaced by a tree scheduler.

## 2. Authority epoch and delayed receipts

Each case version receives a monotonically increasing pair of authority epochs:

```text
root case v1:  ACTIVE 1 -> INTERRUPTED 2
child case v2: ACTIVE 3 -> INTERRUPTED 4
```

Before publication, a Worker receipt can be checked against a capability grant
bound to:

- case ID and case SHA-256;
- authority epoch and issuing-state SHA-256;
- Worker role and invocation ID;
- read-only effects only.

Once the named-human interrupt advances the epoch, a receipt carrying the older
grant is rejected as `STALE_AUTHORITY_EPOCH`. No capability permits equipment
write, CAPA approval or production release.

The current deterministic Workers return synchronously. The delayed-receipt test
therefore validates the publication contract under a simulated late return; it
does not claim that a distributed Worker service or live factory endpoint is
connected.

## 3. Contrastive decision packet

`ContrastiveIncidentDecisionPacket` presents:

- current status, recommendation and observable facts;
- blocking issue codes and all six hypothesis states;
- Workers selected with their receipt hashes;
- why the current recommendation is selected;
- why production release, root-cause closure and ownerless CAPA are rejected;
- missing evidence and conditions that could change the decision;
- the maximum causal claim level allowed by current evidence.

Even when a CAPA child run improves, the packet keeps
`root_cause_status=NOT_ESTABLISHED` and
`production_release_allowed=false`.

## Integrity and persistence

Nodes, tree, authority states, grants, authority checks, ledger, decision packet
and the aggregate bundle each have independent canonical SHA-256 seals. Product
creation writes the case, phase-event chain and control-plane sidecar before the
idempotent command receives a `COMPLETED` terminal receipt. A failure after the
first immutable write remains `UNCERTAIN` and is not automatically replayed.

## Verification

Run the bounded checks:

```powershell
conda run -n base python -m pytest `
  tests/test_incident_control_plane.py `
  tests/test_incident_command_integration.py `
  tests/test_industrial_incident_benchmark.py -q
```

IndustrialIncidentBench keeps its 12-scenario fixed denominator and now verifies
the control plane for every generated case. Its added safety metric is:

```text
unsafe_stale_receipt_acceptance_rate
```

## Claim boundary

This implementation is local engineering evidence. It does not establish a live
OPC UA or VisionMaster connection, asynchronous distributed Worker deployment,
customer acceptance, factory production use, root cause, equipment-control
authority or production release.

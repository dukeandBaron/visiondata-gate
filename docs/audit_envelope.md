# Governed Audit Envelope

VisionData Gate uses a sidecar audit protocol to make Case and outcome lineage deterministically verifiable across implementations.

## Protocol

```text
protocol_id      visiondata-gate.governed-audit-envelope.v1
digest           SHA-256
canonicalization RFC 8785 JCS
framing          visiondata-gate-domain-frame-v1
```

Each digest preimage is unambiguous:

```text
magic
|| uint16be(domain_utf8_length)
|| domain_utf8
|| uint64be(jcs_payload_length)
|| rfc8785_jcs_payload
```

Fixed domains keep identical JSON bytes in different business objects from sharing the same digest context.

## Bound artifacts

The Case envelope binds:

- Case identity and legacy Case digest;
- strictly ordered phase events;
- Worker Receipts and ToolTrace references;
- runtime profile, rulepack, site pack, and governed context;
- source authorization epoch and control-plane bundle;
- Parent Case and named Human Decision for a Child Run;
- current disposition, open responsibility, and production boundaries.

The Governed Outcome envelope extends that chain across Parent Gate, Incident, Human Decision, CAPA selection/approval, private Derived Version, CAPA execution, Child Gate, recovery state, and final responsibility queue.

## Verification

The persisted Case sidecar is:

```text
<case-directory>/audit/governed_audit_envelope.json
```

An offline checkout can verify a Case without starting the API:

```powershell
visiondata-gate incident-audit-verify --case-dir <absolute-case-directory>
```

A successful result includes component checks and the final `audit_root_sha256`. A mismatch returns a non-zero exit code and a machine-readable failure. The API also exposes verified envelopes from the Incident resource and binds projections to strong ETags plus `X-Content-SHA256`.

## Failure behavior

- Missing sidecars are never reconstructed and presented as historical facts.
- Duplicate JSON members, non-finite numbers, ordering drift, digest drift, or broken Parent/Human/Child bindings fail closed.
- Changing a conclusion and recomputing only the top-level hash does not pass cross-artifact verification.
- Stale ETags or authorization epochs prevent a write from silently overwriting current state.

## Security boundary

Accurate descriptions:

```text
tamper-evident
deterministic lineage verification
RFC 8785 canonicalized, domain-separated SHA-256 audit root
```

Claims that are not supported by the current implementation:

```text
tamper-proof
digital signature
trusted timestamp
PKI/KMS signer identity
Merkle inclusion proof
legal ownership or authorization proof
physical causality proof
```

An actor with write access to every local artifact can rewrite the set and recompute unkeyed hashes. Stronger issuer and time guarantees require a protected signing key, rotation policy, trusted timestamp, and an independently controlled anchor.

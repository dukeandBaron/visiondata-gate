# Compliance and Data Boundaries

VisionData Gate is designed for controlled industrial data preparation. This document describes product safeguards and current limitations; it is not legal advice, a certification, or proof that a particular dataset may be used.

## Data classes

| Source kind | Intended use | Public redistribution |
|---|---|---|
| `synthetic_demo` | Reproducible examples and static replay | Allowed only for repository-owned fixtures |
| `local_authorized_directory` | Operator-authorized, server-local processing | Disabled by default |
| `external_residency_reference` | Contract placeholder for externally hosted data | Not connected |

The public repository contains synthetic samples and compact, non-image benchmark receipts. It excludes customer data, private industrial images, model weights, databases, credentials, absolute local paths, and operator receipts.

## Authorization before processing

A local source is accepted only when all of the following are true:

1. its resolved directory is inside a narrow server-side allowlist;
2. the operator supplies a purpose and rights basis;
3. the operator attests authorized, read-only use;
4. raw redistribution is explicitly disabled;
5. a source profile and authorization event are SHA-bound;
6. workspace, project, actor, and task scopes agree.

Authorization events form an append-only hash chain. Revocation blocks future reads and invalidates stale CAPA approvals, but it does not claim to delete bytes owned outside the product root.

## Data minimization and residency

- Raw pixels stay in the configured local product/source root unless a named human approves a private derived version.
- Public evidence uses opaque sample IDs, measurements, counts, rule results, and digests.
- Source filenames, class names, absolute paths, and user profile names are excluded from public artifacts.
- Provider keys remain server-side and are never returned to the browser.
- Public GitHub Pages runs without a backend and cannot upload, mutate, or call a model provider.

## Human authority

The runtime fixes the following boundaries:

```text
raw_images_transmitted=false
machine_write_permitted=false
production_decision_authority=human_only
production_release_allowed=false
```

The Agent may measure, plan, reconcile evidence, recommend a disposition, and prepare CAPA. It does not write to PLC/MES/cameras and does not replace a qualified engineer, quality organization, customer, regulator, or other responsible authority.

## Evidence tracks must stay separate

- **Synthetic fixtures** prove reproducible contract behavior only.
- **Public industrial proxy receipts** prove the stated programmatic governance protocol, not natural-defect accuracy or factory prevalence.
- **Private offline pilot summaries** show that local bytes traversed a bounded workflow; they are not customer acceptance, online shadow testing, or production ROI.

False-release rate, false-block rate, and remediation pass rate require a declared denominator and independently adjudicated truth. When that truth is absent, the value remains `NOT_MEASURED_PENDING_ADJUDICATION`.

## Cryptographic boundary

SHA-256 and RFC 8785 JCS make content and lineage drift detectable. They do not prove signer identity, ownership, authorization, physical causality, or time. Digital signatures, trusted timestamps, and external transparency anchoring are `NOT_CONFIGURED` unless a deployment adds and verifies them.

## External systems

Adapter or Provider code means **contract available**, not **service connected**. MES, OPC UA, PLC, VisionMaster, hosted AgentTeams, and customer IAM remain not connected until a deployment has explicit credentials, endpoint authorization, probe receipts, and an approved operating boundary.

## Reporting a security issue

Do not open a public issue containing a customer sample, private path, log, database, API key, or access token. Follow [SECURITY.md](../SECURITY.md) for private reporting guidance.

Third-party software is documented in [SBOM.cdx.json](SBOM.cdx.json), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and [THIRD_PARTY_LICENSE_INVENTORY.generated.md](THIRD_PARTY_LICENSE_INVENTORY.generated.md). Apache-2.0 applies to project-owned code, not to external data, weights, or customer assets.

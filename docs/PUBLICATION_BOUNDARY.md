# Public source and publication boundary

This document describes what may be published from this source candidate. It is not a release approval, a factory qualification, a GitHub deployment receipt, or evidence of a successful Windows installation.

## Three separate products of the repository

| Surface | What it contains | Authority |
|---|---|---|
| Local source workbench | React, FastAPI, local identity, governed data/workflow state, optional vision-training adapters | Local user Bearer and actual workspace/source permissions; explicit approvals still required |
| Public static build | Public synthetic replay and browser-local inspection of user-selected images | No backend upload, persistent server project, local account API, model API, training, or production write |
| Windows candidate | Tauri, local Spring gateway and FastAPI packaging source | Build identity and artifact-specific verification; source tests do not authorize an installer release |

A public source repository can include backend APIs without deploying those APIs to Pages. In a static build, reading a local image in the browser does not mean uploading it to a service. `PUBLIC_SYNTHETIC_REPLAY`, `REPLAY` and `OFFLINE_EXPORT` remain distinct from local API `LIVE`; none establishes a live factory connection.

The repository entry is [dukeandBaron/visiondata-gate](https://github.com/dukeandBaron/visiondata-gate). A new Pages or Release URL must be checked against the actual published artifact before it is advertised. A source push, PR, merged commit, Pages deployment and Release attachment are separate events.

## Allowlist only

Public candidates are assembled from reviewed, explicit files. A file being untracked, under `docs/`, or needed by a local experiment does not make it publishable.

Eligible material includes reviewed application/build source, public schemas and rules, portable tests, synthetic sample data, selected public benchmark reports, licenses and public documentation. Public text must not depend on unpublished absolute paths, operator receipts or private datasets.

Excluded unless separately cleared:

- Credentials, session tokens, environment files, account stores, customer/project databases and DPAPI state.
- Personal or customer paths, machine identifiers, raw execution logs, internal manifests and raw test receipts that reveal them.
- Private industrial datasets, raw images/masks, source authorizations, or dataset material licensed only for another purpose.
- Model weights, external Python/Torch/Ultralytics environments and training caches.
- Internal commercial drafts, conversation exports, and the bulk contents of `output/`, `10_reports/`, `release/` or `evidence/`.

Two exact frozen synthetic DynamicBench JSON resources may be retained when required by the evaluation projection and independently reviewed. Their inclusion does **not** authorize exporting the rest of their parent directory. Synthetic fixtures and their aggregate metrics must keep their original denominators and `NOT_EVALUATED` industrial-effectiveness boundary.

## Source alignment with the Windows candidate

This source update is being aligned against:

```text
package_version = 0.1.0
build_id = windows-platform-rebuild-20260913-03
frozen_source_content_sha256 =
  41ebaac83ea726ad192a9850108cc4da422bdacf73a535a555c70d4a9f639f1d
```

The frozen digest identifies the build's declared source set, not this public Git tree, a signed artifact or a proof that every public file is identical. Alignment requires per-file checks of the runtime/build inputs. Public README, boundary documentation and publication tooling can differ where necessary and must be listed as such.

This document records the intended alignment; the publication lane must provide its own actual comparison and CI result. Do not identify a dirty source snapshot by its Git HEAD alone.

## Package and third-party boundaries

At the time this candidate documentation was prepared, the new installer was building. Package generation, extracted-package runtime checks, installed GUI, same-version upgrade, clean-machine validation, signing and full component inventory require separate receipts. Existing version `0.1.0` is retained; a unique build ID is not a semantic version upgrade.

Core workbench packaging and optional visual training are different dependency scopes. Torch/Ultralytics, external Python and weights are not bundled merely because registration/training APIs exist. Ultralytics AGPL-3.0 / Enterprise obligations must be reviewed for the intended distribution; using a subprocess is not an exemption. Apache-2.0 applies to the project code, not all external software, weights or data.

A model hash establishes byte identity, not safe deserialization. Loading `.pt` requires trusted origin and explicit authorization. Do not distribute an unknown checkpoint or represent a license declaration as legal verification.

The current Python/npm/Cargo material does not establish a complete Maven/JRE/Windows-runtime SBOM. Do not claim complete supply-chain coverage or code signing from hashes alone.

## Unchanged authority

```text
production_release_allowed=false
production_decision_authority=human_only
machine_write_permitted=false
industrial_effectiveness_status=NOT_EVALUATED
compute_handoff=PREPARED_NOT_SUBMITTED
factory_metrics=NOT_MEASURED_PENDING_ADJUDICATION
```

These labels are not upgraded by publishing code. Local account access is not enterprise SSO/MFA certification; local execution is not customer adoption; a training candidate is not accuracy improvement; a job description is not CANN/NPU scheduling.

See [Current platform delivery](PLATFORM_DELIVERY_20260913.md), [Claim scope](CLAIM_SCOPE.md), [Windows packaging](WINDOWS_INSTALLER.md), [Compliance](compliance.md), and [Security](../SECURITY.md).

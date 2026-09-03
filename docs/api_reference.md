# API Reference

VisionData Gate exposes a loopback FastAPI service for the local workbench and automation clients. The generated OpenAPI document at `/openapi.json` is the source of truth for request and response schemas.

## Start the API

The recommended entry point starts the API and Web client with one ephemeral session:

```powershell
.\run_workbench.ps1 -Install
```

To start only the API, provide a 32-character-or-longer local session token:

```powershell
$env:VISIONDATA_SESSION_TOKEN = "replace-with-a-local-random-token-at-least-32-characters"
.\run_api.ps1 -Port 8787
```

The service listens on `127.0.0.1`. This session mechanism is a local capability boundary, not production IAM.

## Headers

| Header | Use |
|---|---|
| `X-Actor-User-Id` | Selects a local workspace member; it does not authenticate a real person. |
| `X-VisionData-Session-Token` | Carries the local session capability configured on the API process. |
| `Idempotency-Key` | Makes create/execute operations safe to retry. |

Responses that project persisted facts expose `ETag` and `X-Content-SHA256`. Clients should verify both before displaying a LIVE result.

## Health and schema

```http
GET /v1/health
GET /docs
GET /openapi.json
```

## Operator workspace

```http
GET  /v1/operator-workspaces/{workspace_id}/assets
POST /v1/operator-workspaces/{workspace_id}/assets
GET  /v1/operator-workspaces/{workspace_id}/assets/{asset_id}/content
GET  /v1/operator-workspaces/{workspace_id}/assets/{asset_id}/preview
GET  /v1/operator-workspaces/{workspace_id}/assets/{asset_id}/annotations
PUT  /v1/operator-workspaces/{workspace_id}/assets/{asset_id}/annotations
GET  /v1/operator-workspaces/{workspace_id}/work-orders
POST /v1/operator-workspaces/{workspace_id}/assets/{asset_id}/work-orders
PUT  /v1/operator-workspaces/{workspace_id}/work-orders/{work_order_id}
GET  /v1/operator-workspaces/{workspace_id}/work-orders/{work_order_id}/crop
```

Uploads accept JPEG, PNG, BMP, TIFF, and WebP. The server validates decode, format, file size, and pixel count before storing bytes. Annotation and work-order writes are revision checked; a stale revision returns HTTP `409`.

## Data-source authorization

```http
POST /v1/data-sources/local-authorizations
GET  /v1/data-sources?workspace_id={workspace_id}
GET  /v1/data-sources/{source_id}
GET  /v1/data-sources/{source_id}/authorization-events
POST /v1/data-sources/{source_id}/revocations
```

Local sources must be inside `VISIONDATA_LOCAL_SOURCE_ALLOW_ROOTS`. Registration requires the operator to provide the purpose and rights basis and to affirm read-only use with raw redistribution disabled. Responses contain a source ID, profile, and digests instead of the source path.

## Task lifecycle

```http
POST /v1/tasks
GET  /v1/tasks/{task_id}
GET  /v1/tasks/{task_id}/plan
GET  /v1/tasks/{task_id}/preflight
POST /v1/tasks/{task_id}/interventions
GET  /v1/tasks/{task_id}/interventions
GET  /v1/tasks/{task_id}/trace
GET  /v1/tasks/{task_id}/evidence
GET  /v1/tasks/{task_id}/industrial-delivery
GET  /v1/tasks/{task_id}/release-readiness
POST /v1/tasks/{task_id}/reverifications
```

Execution and policy disposition are separate:

```text
execution_status: CREATED -> PLANNED -> RUNNING -> VERIFYING -> COMPLETED | FAILED
final_decision:   PASS | RECAPTURE | QUARANTINE | DEFER
```

`COMPLETED + DEFER` means the execution finished and correctly refused to decide with insufficient evidence.

## Incident review and CAPA

The OpenAPI schema exposes the full Incident, review projection, human decision, CAPA, Child Run, and governed outcome routes. Their contract follows four rules:

1. a projection is built from persisted facts only;
2. its SHA-256 and strong ETag must match;
3. CAPA cannot execute without a named human decision and current evidence;
4. a Child Run never overwrites the Parent result.

Clients must surface missing, stale, and network states as HOLD/retryable states. They must not retain a stale positive status as if it were current.

## Provider Profiles

Provider Profile management is workspace-scoped and loopback-only by default. The API accepts a provider endpoint, model name, and key for server-side storage; it never returns the secret. A task can reference a profile only when its runtime model profile is `workspace-byok`.

Supported planner modes remain `off`, `shadow`, `gated`, and `replay`. A successful connection probe demonstrates endpoint reachability and contract compatibility only; it does not grant production authority.

## Error semantics

| Condition | Expected behavior |
|---|---|
| Missing session or membership | `401` / `403` |
| Stale revision or ETag | `409` |
| Invalid state transition | `409` |
| Source outside allowlist or source drift | fail closed; no task execution |
| Missing artifact or digest mismatch | explicit unavailable/HOLD projection |
| Provider unavailable | deterministic fallback or DEFER within the selected runtime mode |

See [Compliance](compliance.md) before connecting non-public data or an external model.

# Local identity API v1

Goal 2 owns the backend contract; Goal 1 owns the React identity gate and memory-only Bearer transport. This is local account access, not enterprise SSO or production IAM certification. No installer is rebuilt in this implementation turn.

## States and authentication

- `GET /v1/identity/status` is public and returns exactly `setup_required`, `identity_required`, `registration_policy: "ADMIN_APPROVAL"`, `authentication_mode: "SETUP_REQUIRED" | "USER_SESSION"`, `startup_capability_required: true`.
- `identity_required` is exactly `!setup_required`. `startup_capability_required` describes first setup and the native lifecycle exception, not a requirement to send two tokens on every business request. Public identity writes still pass the host Origin/Fetch-Site guard and peer-based throttles. The service remains a loopback deployment; remote/proxy exposure needs a separate reviewed deployment policy.
- First `POST /v1/identity/setup` requires the configured startup capability in `X-VisionData-Session-Token` or `X-VisionData-Desktop-Token`, an actual loopback client, and no forwarded-client headers. It binds the existing server-configured session actor; the request cannot choose an actor or role. SQLite admits only one setup transaction.
- Before setup, existing business routes retain the explicit startup-session/test compatibility path. The frontend must show setup rather than mistake this compatibility identity for an account login.
- After setup, every private `/v1/` request requires `Authorization: Bearer <access_token>`, including routes without an Actor dependency. A supplied actor header must match that user; it never selects identity. Startup capability and test-bypass do not authorize business access.
- Public exceptions: health, identity status/setup/register/login, and the secret-proof desktop readiness endpoint. Desktop shutdown retains a separate loopback startup-capability lifecycle check only; it does not authorize business access.
- Tokens are generated randomly, stored as SHA-256 plus expiry/revocation, and returned only on setup/login. The UI stores them in memory, never WebStorage or query parameters. Switch identity by remounting ProductProvider and clearing previous user state.

## DTOs

`AccountInput`: `{login_name, display_name, password, email?}`. Login name is 3–64 ASCII letters/digits/underscore/dot/hyphen, starts alphanumeric, is trimmed and stored lowercase. Display name is trimmed, 1–120 chars. New passwords (setup, registration, password replacement) remain unchanged, 12–256 chars and at most 1024 UTF-8 bytes; no automatic trimming. Supplied login/current-password credentials allow 1–256 chars so short incorrect credentials still receive the same 401 as other incorrect passwords. Email is optional and unverified.

`PublicUser`: `{user_id, login_name, display_name, email: string|null, platform_role: "ADMIN"|"USER", status: "PENDING"|"ACTIVE"|"DISABLED", created_at}`. No salt/hash/session digest or internal credential version is returned.

`TokenResponse`: `{user: PublicUser, access_token, token_type: "Bearer", expires_at}`. The token has an 8-hour absolute expiry; there is no implicit refresh cookie.

| Method and path, relative to `/v1/identity` | Request | Response |
|---|---|---|
| POST `/setup` | AccountInput | 201 TokenResponse, first admin |
| POST `/register` | AccountInput | 201 PublicUser, always PENDING/USER, no session and no membership |
| POST `/login` | `{login_name,password}` | 200 TokenResponse, ACTIVE accounts only |
| GET `/me` | Bearer | 200 PublicUser, not a `{user}` wrapper |
| POST `/logout` | Bearer | 204; revoke current session |
| POST `/password` | `{current_password,new_password}` | 204; revoke all sessions, including caller |
| GET `/sessions` | Bearer | `{sessions:[{session_id,created_at,expires_at,revoked_at,is_current}]}` |
| DELETE `/sessions/{session_id}` | Bearer | 204; only own session |
| GET `/admin/users` | ADMIN Bearer | `{users:[PublicUser]}` |
| POST `/admin/users/{user_id}/approve` | ADMIN Bearer | PublicUser; PENDING to ACTIVE |
| PUT `/admin/users/{user_id}/status` | `{status:"ACTIVE"|"DISABLED"}` | PublicUser; PENDING must use approve |
| PUT `/admin/users/{user_id}/role` | `{platform_role:"ADMIN"|"USER"}` | PublicUser; only ACTIVE targets |
| GET `/workspaces/{workspace_id}/members` | workspace-owner Bearer | `{members:[{user_id,display_name,role:"owner"|"member"}]}` |
| PUT `/workspaces/{workspace_id}/members/{user_id}` | `{role:"member"}` | same member list; target must be ACTIVE |
| DELETE `/workspaces/{workspace_id}/members/{user_id}` | workspace-owner Bearer | 204; owner cannot be removed |

Member management is authorized by actual workspace ownership, not platform ADMIN alone. Approval does not auto-join any workspace. Existing `users` columns and positional inserts remain unchanged; credentials/sessions live in new tables. Last active ADMIN cannot be disabled or demoted. Disabled accounts' sessions are revoked; reactivation does not revive them.

An ACTIVE user can explicitly create a new, isolated workspace through the existing
`POST /v1/workspaces` with `{name, owner_user_id}`. `owner_user_id` must equal the
actual Bearer identity; another owner is rejected. The response remains
`{workspace_id, name, owner_user_id, role, created_at}`. The INSERT transaction
rechecks ACTIVE and creates only that workspace's owner membership. This is not
automatic registration/approval membership and never joins existing workspaces.
Before identity setup, this operation stays unavailable (404) unless the existing
explicit account-bootstrap compatibility flag is enabled. OpenAPI visibility is
not authorization.

## Errors and execution boundaries

- 401 `identity_authentication_failed`: wrong password, unknown login, unavailable account or invalid/expired/revoked session. Do not disclose which check failed.
- 403 `identity_forbidden`: authenticated identity lacks required authority, or invalid startup scope/capability.
- 409 `identity_conflict`: setup already complete, last-admin protection, invalid transition or incompatible registration.
- Missing/inactive management targets are a 409 conflict, not a 401 for the caller; this prevents an invalid target from logging the current user out.
- 429 `identity_rate_limited`, with Retry-After. Malformed request bodies receive the existing safe 422 without input echo.
- Responses use `Cache-Control: private, no-store`; credentials are never copied into logs or response error text.
- Password/session revocation prevents future API access. It does not silently cancel an already approved background task; explicit cancellation and current account/source authority checks govern that task's execution and publication.
- Account DISABLED is different from session rotation: before execution it records FAILED without starting the runner; during execution it prevents publication. The final COMPLETED transaction rechecks the creator's current ACTIVE authority. FAILED/CANCELLED cleanup is not blocked by that check. Already sealed historical artifacts remain immutable.
- Route installers for data-pool and vision-model modules receive `(app, actor_dependency, product_dependency)` and reuse those dependencies. They must not trust actor headers independently.

## Implementation and validation scope

The service and 16 identity routes are implemented in `identity_service.py` and
`identity_api.py` and installed by `api.py`. The host also installs learning,
data-pool, and vision-model routes using the same authenticated actor dependency.
Credential operations are synchronous worker-thread handlers; the async global
guard performs its SQLite checks off the event loop. Password storage uses the
standard-library PBKDF2-HMAC-SHA256 implementation with 600,000 iterations,
independent 32-byte salts, and bounded KDF concurrency. Random 256-bit session
tokens are persisted only as SHA-256 digests with expiry and revocation.

Verification is separated into real-service HTTP tests (`test_identity_api.py`),
DTO/router tests (`test_identity_router.py`), storage and concurrency tests
(`test_identity_service.py`, `test_identity_review_regressions.py`), and task
lifecycle publication tests (`test_identity_background.py`). Lifecycle tests use
the existing sealed runner fixture; they are not industrial model-accuracy tests.
The latest local verification report records the actual run and its limits.

This source change does not upgrade an existing installation automatically. No
installer rebuild, installed GUI signoff, customer data migration, remote service
exposure, enterprise SSO/MFA, or production IAM certification is claimed here.

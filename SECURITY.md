# Security Policy

## Supported scope

Security fixes target the current `main` branch. Historical competition tags remain immutable evidence snapshots and may not receive feature backports.

## Reporting a vulnerability

Use the repository's **Security → Report a vulnerability** private advisory flow. Do not place secrets, customer data, private image samples, exploit payloads, local paths, or personal information in a public issue.

If private vulnerability reporting is unavailable, open a public issue containing only a non-sensitive request for a maintainer to enable a private channel. Do not include technical exploit details there.

## Trust boundaries

- The public Pages site is a read-only synthetic replay without a Python backend, account system, API-key input, factory connection, or device write path.
- Local BYOK secrets remain server-side; public builds must not contain `.env`, token files, DPAPI material, databases, logs, or private receipts.
- Agent output is advisory. `production_release_allowed=false`, `machine_write_permitted=false`, and human approval remain hard boundaries.
- A passing hash or CI job proves integrity only for the named artifact and commit; it does not prove customer acceptance or production safety.

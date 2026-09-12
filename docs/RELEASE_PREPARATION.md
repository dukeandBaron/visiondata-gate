# Preparing a public release

Release preparation is not authorization to publish. Existing GitHub prereleases
are listed in [CHANGELOG](../CHANGELOG.md); PyPI installation is not advertised
until an actual package publication has been verified.

## Source and identity

1. Select an exact public source commit or a clean reviewed allowlist candidate.
   Do not publish the dirty authority tree or its private history.
2. Record the package version, source commit, lockfiles, toolchain, intended
   platform and verification scope. Competition artifact tags and Python package
   versions are separate identifiers.
3. Run quality/contract/privacy checks and inspect source/wheel contents for
   customer files, local logs, credentials and unintended package data.
4. Build source and wheel artifacts in a fresh candidate directory. Validate
   metadata and installation in a new environment; exercise the actual CLI.
   A CLI entry in `pyproject.toml` does not prove `uvx` usability.
5. Review license/SBOM consistency against any changed lockfile before producing
   new detached hashes or release attestations. Never silently inherit old hashes.

## Publication decisions

- PyPI publishing requires confirmed ownership/availability of the project name,
  a chosen version, reviewed distribution contents and a configured trusted
  publishing identity. Prefer short-lived OIDC credentials; do not put tokens in
  repository variables, examples or command output.
- TestPyPI is also an external publication, not an implicit local smoke test.
- GitHub Releases and topics already exist; do not manufacture another release
  simply to satisfy a stale review. Attach only artifacts matching the new source.
- A configured CI workflow or signed artifact is not proof of runtime safety,
  customer effectiveness or clean-machine installation.

The current task prepares source changes and verification material. Actual PyPI
uploads, GitHub pushes/releases, signing, Pages deployment and native installers
remain explicit, separately verified publication steps.

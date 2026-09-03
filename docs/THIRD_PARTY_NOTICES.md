# Third-party notices

VisionData Gate is licensed under Apache-2.0. Its source distribution does
not vendor the Python distributions listed below, model weights, or external
datasets. The packages are resolved by `uv.lock` and installed separately by
the user's package manager. Each installed distribution remains governed by
its own license and carries its authoritative license files.

This notice records the 63 locked third-party packages in the current environment.
The machine-readable inventory is `docs/SBOM.cdx.json`; metadata provenance,
manual-resolution evidence, and exact versions are recorded in
`docs/THIRD_PARTY_LICENSE_INVENTORY.generated.md`.

A desktop build created with PyInstaller can embed the PyInstaller bootloader,
runtime hooks, and Python dependencies; distributors of that build must retain
the applicable license notices and satisfy the file-scoped terms recorded
below.

## Apache-2.0

- pyarrow 24.0.0
- pydeck 0.9.3
- python-multipart 0.0.32
- rfc8785 0.1.4
- requests 2.34.2
- streamlit 1.61.1
- tenacity 9.1.4
- tzdata 2026.3
- watchdog 6.0.0

## Apache-2.0 OR BSD-2-Clause

- packaging 26.3

## Apache-2.0 OR BSD-3-Clause

- python-dateutil 2.9.0.post0

## BSD-2-Clause

- pygments 2.20.0

## BSD-3-Clause

- altair 6.2.2
- click 8.4.2
- colorama 0.4.6
- httpcore 1.0.9
- httpx 0.28.1
- idna 3.18
- itsdangerous 2.2.0
- jinja2 3.1.6
- markupsafe 3.0.3
- numpy 2.2.6
- pandas 2.3.3
- protobuf 7.35.1
- pywin32-ctypes 0.2.3
- starlette 1.3.1
- uvicorn 0.52.1
- websockets 16.1.1

## MIT

- altgraph 0.17.5
- annotated-doc 0.0.5
- annotated-types 0.8.0
- anyio 4.14.2
- attrs 26.1.0
- blinker 1.9.0
- charset-normalizer 3.4.9
- fastapi 0.141.1
- h11 0.16.0
- httptools 0.8.0
- iniconfig 2.3.0
- jsonschema 4.26.0
- jsonschema-specifications 2025.9.1
- macholib 1.16.4
- narwhals 2.24.0
- pefile 2024.8.26
- pluggy 1.6.0
- pydantic 2.13.4
- pydantic-core 2.46.4
- pytest 9.1.1
- pyyaml 6.0.3
- pytz 2026.3.post1
- referencing 0.37.0
- rpds-py 2026.6.3
- ruff 0.15.22
- setuptools 84.0.0
- six 1.17.0
- toml 0.10.2
- typing-inspection 0.4.2
- urllib3 2.7.0

## Mixed, file-scoped licenses

| Package | Component-level SPDX expression | Distribution scope |
|---|---|---|
| pyinstaller 6.22.2 | `(GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0 AND (GPL-2.0-or-later OR MIT)` | Main source and bootloader: GPL-2.0-or-later with Bootloader exception; runtime hooks: Apache-2.0; `PyInstaller.isolated`: GPL-2.0-or-later or MIT. |
| pyinstaller-hooks-contrib 2026.7 | `GPL-2.0-or-later AND Apache-2.0` | Standard hooks: GPL-2.0-or-later; runtime hooks: Apache-2.0. |

## MIT-CMU

- pillow 12.3.0

## MPL-2.0

- certifi 2026.7.22

## PSF-2.0

- typing-extensions 4.16.0

## Exact-version manual resolutions

Thirteen dependency records did not expose a single unambiguous SPDX expression
through cross-platform Core Metadata. Their wheel license files were reviewed
for the locked version; an upgrade deliberately returns the component to
`REVIEW_REQUIRED` until the new distribution is checked.

| Package | Resolved expression | Distribution license-file SHA-256 |
|---|---|---|
| altair 6.2.2 | BSD-3-Clause | `648332da6631555f71f18305b96e9a2c409e73d73613b6c96587cdc0a449e054` |
| colorama 0.4.6 | BSD-3-Clause | `cac35c02686e5d04a5a7140bfb3b36e73aed496656e891102e428886d7930318` |
| itsdangerous 2.2.0 | BSD-3-Clause | `63af09891b6be8ad1a4252ed43af0f4efba7fc948e228367bed7f3c5ae0b09d7` |
| jinja2 3.1.6 | BSD-3-Clause | `3b49dcee4105eb37bac10faf1be260408fe85d252b8e9df2e0979fc1e094437b` |
| macholib 1.16.4 | MIT | `47082ab2bc0184123ec9f10fdf80c70723ee68f07d44382e17615c2a6ba70b09` |
| numpy 2.2.6 | BSD-3-Clause | `14256cc3a2c9d32ac284da96b937feb44f72dd90bee2317ac3020166846ad99d` |
| pandas 2.3.3 | BSD-3-Clause | `533eb6d0b98e5be3ddd12dce97be35dd11282f5c47cdf8d08c81756fd5d70a26` |
| pefile 2024.8.26 | MIT | `b44409c067c6da52bfb54bb6624fb11a7b52157c3a13ae1400232f8196e86ad3` |
| pyinstaller 6.22.2 | `(GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0 AND (GPL-2.0-or-later OR MIT)` | `dcf75fdb959db1e3b41c0f8505069d2ece781b5ec6b3d0a4d30975cfc6580245` |
| pyinstaller-hooks-contrib 2026.7 | `GPL-2.0-or-later AND Apache-2.0` | `91d0baaff00773038e72c0a1fc9d5d2d38706b7a2b9c04f34296608f931b9cd0` |
| pywin32-ctypes 0.2.3 | BSD-3-Clause | `dfa83b3e2709adfcdb838d9ad55823ca674abb780e60563d9dd9544ccbf785e9` |
| python-dateutil 2.9.0.post0 | Apache-2.0 OR BSD-3-Clause | `ba00f51a0d92823b5a1cde27d8b5b9d2321e67ed8da9bc163eff96d5e17e577e` |
| watchdog 6.0.0 | Apache-2.0 | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |

The NumPy wheel license file includes its bundled binary notices. VisionData
Gate does not redistribute that wheel; users receiving it through a package
index should retain the license files shipped with that distribution.

This engineering inventory is not legal advice. If the dependency set,
distribution channel, or vendoring policy changes, regenerate the SBOM and
repeat the license review before release.

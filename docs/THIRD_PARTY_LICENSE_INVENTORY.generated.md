# 第三方许可证元数据清单（自动生成）

> 本文件由 `uv.lock`、`web/package-lock.json`、`web/src-tauri/Cargo.lock`、`docs/CARGO_LICENSES.locked.json`、项目 `.venv` 中已安装的 `METADATA` 与精确版本许可证人工复核表离线生成；它是可审计的工程清单，不构成法律意见。项目授权见顶层 `LICENSE` / `NOTICE`，依赖说明见 `docs/THIRD_PARTY_NOTICES.md`。

- 锁定组件总数（含内部根项目）：`415`
- `REVIEW_REQUIRED`：`0`
- 数据范围：枚举 `uv.lock`、`package-lock.json` 的全部组件，以及 `Cargo.lock` 中 Windows `x86_64-pc-windows-msvc` 目标可达组件；`.venv` 中不在 `uv.lock` 内的分发包不会进入本表。
- Rust 许可边界：`Cargo.lock` 不携带 SPDX 许可字段；许可证据来自与该锁文件 SHA-256 绑定、剥离作者与路径的 Cargo metadata 投影。未绑定条目保持 `REVIEW_REQUIRED`。
- 条件依赖：仅通过 marker 入边引用的组件不读取当前平台安装 METADATA，避免跨平台借用许可证据。
- 重建方式：`python tools/generate_supply_chain_artifacts.py`；不需要联网。

| 关系 | 名称 | 版本 | PURL | 许可表达式 / classifiers | 元数据来源 | 复核状态 |
|---|---|---|---|---|---|---|
| internal-root | visiondata-gate | 0.1.0 | pkg:pypi/visiondata-gate@0.1.0 | License-Expression: Apache-2.0 | uv.lock; .venv/site-packages/visiondata_gate-0.1.0.dist-info/METADATA | OK |
| transitive | altair | 6.2.2 | pkg:pypi/altair@6.2.2 | wheel LICENSE SHA-256 648332da6631555f71f18305b96e9a2c409e73d73613b6c96587cdc0a449e054 | uv.lock; manual-audit:altair-6.2.2.dist-info/licenses/LICENSE | OK |
| transitive | altgraph | 0.17.5 | pkg:pypi/altgraph@0.17.5 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/altgraph-0.17.5.dist-info/METADATA | OK |
| transitive | annotated-doc | 0.0.5 | pkg:pypi/annotated-doc@0.0.5 | License-Expression: MIT | uv.lock; .venv/site-packages/annotated_doc-0.0.5.dist-info/METADATA | OK |
| transitive | annotated-types | 0.8.0 | pkg:pypi/annotated-types@0.8.0 | License-Expression: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/annotated_types-0.8.0.dist-info/METADATA | OK |
| transitive | anyio | 4.14.2 | pkg:pypi/anyio@4.14.2 | License-Expression: MIT | uv.lock; .venv/site-packages/anyio-4.14.2.dist-info/METADATA | OK |
| transitive | attrs | 26.1.0 | pkg:pypi/attrs@26.1.0 | License-Expression: MIT | uv.lock; .venv/site-packages/attrs-26.1.0.dist-info/METADATA | OK |
| transitive | blinker | 1.9.0 | pkg:pypi/blinker@1.9.0 | Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/blinker-1.9.0.dist-info/METADATA | OK |
| transitive | certifi | 2026.7.22 | pkg:pypi/certifi@2026.7.22 | License: MPL-2.0; Classifier: License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0) | uv.lock; .venv/site-packages/certifi-2026.7.22.dist-info/METADATA | OK |
| transitive | charset-normalizer | 3.4.9 | pkg:pypi/charset-normalizer@3.4.9 | License: MIT | uv.lock; .venv/site-packages/charset_normalizer-3.4.9.dist-info/METADATA | OK |
| transitive | click | 8.4.2 | pkg:pypi/click@8.4.2 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/click-8.4.2.dist-info/METADATA | OK |
| transitive | colorama | 0.4.6 | pkg:pypi/colorama@0.4.6 | wheel LICENSE SHA-256 cac35c02686e5d04a5a7140bfb3b36e73aed496656e891102e428886d7930318 | uv.lock; manual-audit:colorama-0.4.6.dist-info/licenses/LICENSE.txt | OK |
| direct | fastapi | 0.141.1 | pkg:pypi/fastapi@0.141.1 | License-Expression: MIT | uv.lock; .venv/site-packages/fastapi-0.141.1.dist-info/METADATA | OK |
| transitive | h11 | 0.16.0 | pkg:pypi/h11@0.16.0 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/h11-0.16.0.dist-info/METADATA | OK |
| transitive | httpcore | 1.0.9 | pkg:pypi/httpcore@1.0.9 | License-Expression: BSD-3-Clause; Classifier: License :: OSI Approved :: BSD License | uv.lock; .venv/site-packages/httpcore-1.0.9.dist-info/METADATA | OK |
| transitive | httptools | 0.8.0 | pkg:pypi/httptools@0.8.0 | License-Expression: MIT | uv.lock; .venv/site-packages/httptools-0.8.0.dist-info/METADATA | OK |
| direct | httpx | 0.28.1 | pkg:pypi/httpx@0.28.1 | License: BSD-3-Clause; Classifier: License :: OSI Approved :: BSD License | uv.lock; .venv/site-packages/httpx-0.28.1.dist-info/METADATA | OK |
| transitive | idna | 3.18 | pkg:pypi/idna@3.18 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/idna-3.18.dist-info/METADATA | OK |
| transitive | iniconfig | 2.3.0 | pkg:pypi/iniconfig@2.3.0 | License-Expression: MIT | uv.lock; .venv/site-packages/iniconfig-2.3.0.dist-info/METADATA | OK |
| transitive | itsdangerous | 2.2.0 | pkg:pypi/itsdangerous@2.2.0 | wheel LICENSE SHA-256 63af09891b6be8ad1a4252ed43af0f4efba7fc948e228367bed7f3c5ae0b09d7 | uv.lock; manual-audit:itsdangerous-2.2.0.dist-info/LICENSE.txt | OK |
| transitive | jinja2 | 3.1.6 | pkg:pypi/jinja2@3.1.6 | wheel LICENSE SHA-256 3b49dcee4105eb37bac10faf1be260408fe85d252b8e9df2e0979fc1e094437b | uv.lock; manual-audit:jinja2-3.1.6.dist-info/licenses/LICENSE.txt | OK |
| transitive | jsonschema | 4.26.0 | pkg:pypi/jsonschema@4.26.0 | License-Expression: MIT | uv.lock; .venv/site-packages/jsonschema-4.26.0.dist-info/METADATA | OK |
| transitive | jsonschema-specifications | 2025.9.1 | pkg:pypi/jsonschema-specifications@2025.9.1 | License-Expression: MIT | uv.lock; .venv/site-packages/jsonschema_specifications-2025.9.1.dist-info/METADATA | OK |
| transitive | macholib | 1.16.4 | pkg:pypi/macholib@1.16.4 | wheel LICENSE SHA-256 47082ab2bc0184123ec9f10fdf80c70723ee68f07d44382e17615c2a6ba70b09 | uv.lock; manual-audit:macholib-1.16.4.dist-info/LICENSE | OK |
| transitive | markupsafe | 3.0.3 | pkg:pypi/markupsafe@3.0.3 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/markupsafe-3.0.3.dist-info/METADATA | OK |
| transitive | narwhals | 2.24.0 | pkg:pypi/narwhals@2.24.0 | License-Expression: MIT | uv.lock; .venv/site-packages/narwhals-2.24.0.dist-info/METADATA | OK |
| direct | numpy | 2.2.6 | pkg:pypi/numpy@2.2.6 | wheel LICENSE and bundled notices SHA-256 14256cc3a2c9d32ac284da96b937feb44f72dd90bee2317ac3020166846ad99d | uv.lock; manual-audit:numpy-2.2.6.dist-info/LICENSE.txt | OK |
| transitive | packaging | 26.3 | pkg:pypi/packaging@26.3 | License-Expression: Apache-2.0 OR BSD-2-Clause | uv.lock; .venv/site-packages/packaging-26.3.dist-info/METADATA | OK |
| direct | pandas | 2.3.3 | pkg:pypi/pandas@2.3.3 | wheel LICENSE SHA-256 533eb6d0b98e5be3ddd12dce97be35dd11282f5c47cdf8d08c81756fd5d70a26 | uv.lock; manual-audit:pandas-2.3.3.dist-info/LICENSE | OK |
| transitive | pefile | 2024.8.26 | pkg:pypi/pefile@2024.8.26 | wheel LICENSE SHA-256 b44409c067c6da52bfb54bb6624fb11a7b52157c3a13ae1400232f8196e86ad3 | uv.lock; manual-audit:pefile-2024.8.26.dist-info/LICENSE | OK |
| direct | pillow | 12.3.0 | pkg:pypi/pillow@12.3.0 | License-Expression: MIT-CMU | uv.lock; .venv/site-packages/pillow-12.3.0.dist-info/METADATA | OK |
| transitive | pluggy | 1.6.0 | pkg:pypi/pluggy@1.6.0 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/pluggy-1.6.0.dist-info/METADATA | OK |
| transitive | protobuf | 7.35.1 | pkg:pypi/protobuf@7.35.1 | License: 3-Clause BSD License | uv.lock; .venv/site-packages/protobuf-7.35.1.dist-info/METADATA | OK |
| transitive | pyarrow | 24.0.0 | pkg:pypi/pyarrow@24.0.0 | License-Expression: Apache-2.0 | uv.lock; .venv/site-packages/pyarrow-24.0.0.dist-info/METADATA | OK |
| direct | pydantic | 2.13.4 | pkg:pypi/pydantic@2.13.4 | License-Expression: MIT | uv.lock; .venv/site-packages/pydantic-2.13.4.dist-info/METADATA | OK |
| transitive | pydantic-core | 2.46.4 | pkg:pypi/pydantic-core@2.46.4 | License-Expression: MIT | uv.lock; .venv/site-packages/pydantic_core-2.46.4.dist-info/METADATA | OK |
| transitive | pydeck | 0.9.3 | pkg:pypi/pydeck@0.9.3 | License: Apache License 2.0 | uv.lock; .venv/site-packages/pydeck-0.9.3.dist-info/METADATA | OK |
| transitive | pygments | 2.20.0 | pkg:pypi/pygments@2.20.0 | License-Expression: BSD-2-Clause | uv.lock; .venv/site-packages/pygments-2.20.0.dist-info/METADATA | OK |
| direct | pyinstaller | 6.22.2 | pkg:pypi/pyinstaller@6.22.2 | wheel COPYING.txt SHA-256 dcf75fdb959db1e3b41c0f8505069d2ece781b5ec6b3d0a4d30975cfc6580245 | uv.lock; manual-audit:pyinstaller-6.22.2.dist-info/licenses/COPYING.txt | OK |
| transitive | pyinstaller-hooks-contrib | 2026.7 | pkg:pypi/pyinstaller-hooks-contrib@2026.7 | wheel LICENSE SHA-256 91d0baaff00773038e72c0a1fc9d5d2d38706b7a2b9c04f34296608f931b9cd0 | uv.lock; manual-audit:pyinstaller_hooks_contrib-2026.7.dist-info/licenses/LICENSE | OK |
| direct | pytest | 9.1.1 | pkg:pypi/pytest@9.1.1 | License-Expression: MIT | uv.lock; .venv/site-packages/pytest-9.1.1.dist-info/METADATA | OK |
| transitive | python-dateutil | 2.9.0.post0 | pkg:pypi/python-dateutil@2.9.0.post0 | wheel dual-license file SHA-256 ba00f51a0d92823b5a1cde27d8b5b9d2321e67ed8da9bc163eff96d5e17e577e | uv.lock; manual-audit:python_dateutil-2.9.0.post0.dist-info/LICENSE | OK |
| direct | python-multipart | 0.0.32 | pkg:pypi/python-multipart@0.0.32 | License-Expression: Apache-2.0; Classifier: License :: OSI Approved :: Apache Software License | uv.lock; .venv/site-packages/python_multipart-0.0.32.dist-info/METADATA | OK |
| transitive | pytz | 2026.3.post1 | pkg:pypi/pytz@2026.3.post1 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/pytz-2026.3.post1.dist-info/METADATA | OK |
| transitive | pywin32-ctypes | 0.2.3 | pkg:pypi/pywin32-ctypes@0.2.3 | wheel LICENSE.txt SHA-256 dfa83b3e2709adfcdb838d9ad55823ca674abb780e60563d9dd9544ccbf785e9 | uv.lock; manual-audit:pywin32_ctypes-0.2.3.dist-info/LICENSE.txt | OK |
| direct | pyyaml | 6.0.3 | pkg:pypi/pyyaml@6.0.3 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/pyyaml-6.0.3.dist-info/METADATA | OK |
| transitive | referencing | 0.37.0 | pkg:pypi/referencing@0.37.0 | License-Expression: MIT | uv.lock; .venv/site-packages/referencing-0.37.0.dist-info/METADATA | OK |
| transitive | requests | 2.34.2 | pkg:pypi/requests@2.34.2 | License: Apache-2.0; Classifier: License :: OSI Approved :: Apache Software License | uv.lock; .venv/site-packages/requests-2.34.2.dist-info/METADATA | OK |
| direct | rfc8785 | 0.1.4 | pkg:pypi/rfc8785@0.1.4 | Classifier: License :: OSI Approved :: Apache Software License | uv.lock; .venv/site-packages/rfc8785-0.1.4.dist-info/METADATA | OK |
| transitive | rpds-py | 2026.6.3 | pkg:pypi/rpds-py@2026.6.3 | License-Expression: MIT | uv.lock; .venv/site-packages/rpds_py-2026.6.3.dist-info/METADATA | OK |
| direct | ruff | 0.15.22 | pkg:pypi/ruff@0.15.22 | License-Expression: MIT | uv.lock; .venv/site-packages/ruff-0.15.22.dist-info/METADATA | OK |
| transitive | setuptools | 84.0.0 | pkg:pypi/setuptools@84.0.0 | License-Expression: MIT | uv.lock; .venv/site-packages/setuptools-84.0.0.dist-info/METADATA | OK |
| transitive | six | 1.17.0 | pkg:pypi/six@1.17.0 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/six-1.17.0.dist-info/METADATA | OK |
| transitive | starlette | 1.3.1 | pkg:pypi/starlette@1.3.1 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/starlette-1.3.1.dist-info/METADATA | OK |
| direct | streamlit | 1.61.1 | pkg:pypi/streamlit@1.61.1 | License-Expression: Apache-2.0 | uv.lock; .venv/site-packages/streamlit-1.61.1.dist-info/METADATA | OK |
| transitive | tenacity | 9.1.4 | pkg:pypi/tenacity@9.1.4 | License: Apache 2.0; Classifier: License :: OSI Approved :: Apache Software License | uv.lock; .venv/site-packages/tenacity-9.1.4.dist-info/METADATA | OK |
| transitive | toml | 0.10.2 | pkg:pypi/toml@0.10.2 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/toml-0.10.2.dist-info/METADATA | OK |
| transitive | typing-extensions | 4.16.0 | pkg:pypi/typing-extensions@4.16.0 | License-Expression: PSF-2.0 | uv.lock; .venv/site-packages/typing_extensions-4.16.0.dist-info/METADATA | OK |
| transitive | typing-inspection | 0.4.2 | pkg:pypi/typing-inspection@0.4.2 | License-Expression: MIT | uv.lock; .venv/site-packages/typing_inspection-0.4.2.dist-info/METADATA | OK |
| direct | tzdata | 2026.3 | pkg:pypi/tzdata@2026.3 | License: Apache-2.0 | uv.lock; .venv/site-packages/tzdata-2026.3.dist-info/METADATA | OK |
| transitive | urllib3 | 2.7.0 | pkg:pypi/urllib3@2.7.0 | License-Expression: MIT | uv.lock; .venv/site-packages/urllib3-2.7.0.dist-info/METADATA | OK |
| direct | uvicorn | 0.52.1 | pkg:pypi/uvicorn@0.52.1 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/uvicorn-0.52.1.dist-info/METADATA | OK |
| transitive | watchdog | 6.0.0 | pkg:pypi/watchdog@6.0.0 | wheel LICENSE SHA-256 cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30 | uv.lock; manual-audit:watchdog-6.0.0.dist-info/LICENSE | OK |
| transitive | websockets | 16.1.1 | pkg:pypi/websockets@16.1.1 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/websockets-16.1.1.dist-info/METADATA | OK |
| workspace-root | visiondata-gate-web | 0.1.0 | pkg:npm/visiondata-gate-web@0.1.0 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @oxc-project/types | 0.147.0 | pkg:npm/%40oxc-project/types@0.147.0 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-android-arm-eabi | 1.2.6 | pkg:npm/%40rolldown/binding-android-arm-eabi@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-android-arm64 | 1.2.6 | pkg:npm/%40rolldown/binding-android-arm64@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-darwin-arm64 | 1.2.6 | pkg:npm/%40rolldown/binding-darwin-arm64@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-darwin-x64 | 1.2.6 | pkg:npm/%40rolldown/binding-darwin-x64@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-freebsd-x64 | 1.2.6 | pkg:npm/%40rolldown/binding-freebsd-x64@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-linux-arm-gnueabihf | 1.2.6 | pkg:npm/%40rolldown/binding-linux-arm-gnueabihf@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-linux-arm64-gnu | 1.2.6 | pkg:npm/%40rolldown/binding-linux-arm64-gnu@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-linux-arm64-musl | 1.2.6 | pkg:npm/%40rolldown/binding-linux-arm64-musl@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-linux-ppc64-gnu | 1.2.6 | pkg:npm/%40rolldown/binding-linux-ppc64-gnu@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-linux-s390x-gnu | 1.2.6 | pkg:npm/%40rolldown/binding-linux-s390x-gnu@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-linux-x64-gnu | 1.2.6 | pkg:npm/%40rolldown/binding-linux-x64-gnu@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-linux-x64-musl | 1.2.6 | pkg:npm/%40rolldown/binding-linux-x64-musl@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-openharmony-arm64 | 1.2.6 | pkg:npm/%40rolldown/binding-openharmony-arm64@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-win32-arm64-msvc | 1.2.6 | pkg:npm/%40rolldown/binding-win32-arm64-msvc@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/binding-win32-x64-msvc | 1.2.6 | pkg:npm/%40rolldown/binding-win32-x64-msvc@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @rolldown/pluginutils | 1.0.1 | pkg:npm/%40rolldown/pluginutils@1.0.1 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| direct | @tauri-apps/api | 2.11.1 | pkg:npm/%40tauri-apps/api@2.11.1 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| direct | @tauri-apps/cli | 2.11.4 | pkg:npm/%40tauri-apps/cli@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @tauri-apps/cli-darwin-arm64 | 2.11.4 | pkg:npm/%40tauri-apps/cli-darwin-arm64@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @tauri-apps/cli-darwin-x64 | 2.11.4 | pkg:npm/%40tauri-apps/cli-darwin-x64@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @tauri-apps/cli-linux-arm-gnueabihf | 2.11.4 | pkg:npm/%40tauri-apps/cli-linux-arm-gnueabihf@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @tauri-apps/cli-linux-arm64-gnu | 2.11.4 | pkg:npm/%40tauri-apps/cli-linux-arm64-gnu@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @tauri-apps/cli-linux-arm64-musl | 2.11.4 | pkg:npm/%40tauri-apps/cli-linux-arm64-musl@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @tauri-apps/cli-linux-riscv64-gnu | 2.11.4 | pkg:npm/%40tauri-apps/cli-linux-riscv64-gnu@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @tauri-apps/cli-linux-x64-gnu | 2.11.4 | pkg:npm/%40tauri-apps/cli-linux-x64-gnu@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @tauri-apps/cli-linux-x64-musl | 2.11.4 | pkg:npm/%40tauri-apps/cli-linux-x64-musl@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @tauri-apps/cli-win32-arm64-msvc | 2.11.4 | pkg:npm/%40tauri-apps/cli-win32-arm64-msvc@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @tauri-apps/cli-win32-ia32-msvc | 2.11.4 | pkg:npm/%40tauri-apps/cli-win32-ia32-msvc@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @tauri-apps/cli-win32-x64-msvc | 2.11.4 | pkg:npm/%40tauri-apps/cli-win32-x64-msvc@2.11.4 | web/package-lock.json License: Apache-2.0 OR MIT | web/package-lock.json; web/package-lock.json | OK |
| direct | @types/react | 19.2.18 | pkg:npm/%40types/react@19.2.18 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| direct | @types/react-dom | 19.2.5 | pkg:npm/%40types/react-dom@19.2.5 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-aix-ppc64 | 7.0.2 | pkg:npm/%40typescript/typescript-aix-ppc64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-darwin-arm64 | 7.0.2 | pkg:npm/%40typescript/typescript-darwin-arm64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-darwin-x64 | 7.0.2 | pkg:npm/%40typescript/typescript-darwin-x64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-freebsd-arm64 | 7.0.2 | pkg:npm/%40typescript/typescript-freebsd-arm64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-freebsd-x64 | 7.0.2 | pkg:npm/%40typescript/typescript-freebsd-x64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-linux-arm | 7.0.2 | pkg:npm/%40typescript/typescript-linux-arm@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-linux-arm64 | 7.0.2 | pkg:npm/%40typescript/typescript-linux-arm64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-linux-loong64 | 7.0.2 | pkg:npm/%40typescript/typescript-linux-loong64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-linux-mips64el | 7.0.2 | pkg:npm/%40typescript/typescript-linux-mips64el@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-linux-ppc64 | 7.0.2 | pkg:npm/%40typescript/typescript-linux-ppc64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-linux-riscv64 | 7.0.2 | pkg:npm/%40typescript/typescript-linux-riscv64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-linux-s390x | 7.0.2 | pkg:npm/%40typescript/typescript-linux-s390x@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-linux-x64 | 7.0.2 | pkg:npm/%40typescript/typescript-linux-x64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-netbsd-arm64 | 7.0.2 | pkg:npm/%40typescript/typescript-netbsd-arm64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-netbsd-x64 | 7.0.2 | pkg:npm/%40typescript/typescript-netbsd-x64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-openbsd-arm64 | 7.0.2 | pkg:npm/%40typescript/typescript-openbsd-arm64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-openbsd-x64 | 7.0.2 | pkg:npm/%40typescript/typescript-openbsd-x64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-sunos-x64 | 7.0.2 | pkg:npm/%40typescript/typescript-sunos-x64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-win32-arm64 | 7.0.2 | pkg:npm/%40typescript/typescript-win32-arm64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | @typescript/typescript-win32-x64 | 7.0.2 | pkg:npm/%40typescript/typescript-win32-x64@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| direct | @vitejs/plugin-react | 6.1.0 | pkg:npm/%40vitejs/plugin-react@6.1.0 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | cookie | 1.1.1 | pkg:npm/cookie@1.1.1 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | csstype | 3.2.3 | pkg:npm/csstype@3.2.3 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | detect-libc | 2.1.2 | pkg:npm/detect-libc@2.1.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | fdir | 6.5.0 | pkg:npm/fdir@6.5.0 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | fsevents | 2.3.3 | pkg:npm/fsevents@2.3.3 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss | 1.33.0 | pkg:npm/lightningcss@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss-android-arm64 | 1.33.0 | pkg:npm/lightningcss-android-arm64@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss-darwin-arm64 | 1.33.0 | pkg:npm/lightningcss-darwin-arm64@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss-darwin-x64 | 1.33.0 | pkg:npm/lightningcss-darwin-x64@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss-freebsd-x64 | 1.33.0 | pkg:npm/lightningcss-freebsd-x64@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss-linux-arm-gnueabihf | 1.33.0 | pkg:npm/lightningcss-linux-arm-gnueabihf@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss-linux-arm64-gnu | 1.33.0 | pkg:npm/lightningcss-linux-arm64-gnu@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss-linux-arm64-musl | 1.33.0 | pkg:npm/lightningcss-linux-arm64-musl@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss-linux-x64-gnu | 1.33.0 | pkg:npm/lightningcss-linux-x64-gnu@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss-linux-x64-musl | 1.33.0 | pkg:npm/lightningcss-linux-x64-musl@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss-win32-arm64-msvc | 1.33.0 | pkg:npm/lightningcss-win32-arm64-msvc@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| transitive | lightningcss-win32-x64-msvc | 1.33.0 | pkg:npm/lightningcss-win32-x64-msvc@1.33.0 | web/package-lock.json License: MPL-2.0 | web/package-lock.json; web/package-lock.json | OK |
| direct | lucide-react | 1.34.0 | pkg:npm/lucide-react@1.34.0 | web/package-lock.json License: ISC | web/package-lock.json; web/package-lock.json | OK |
| transitive | nanoid | 3.3.18 | pkg:npm/nanoid@3.3.18 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | picocolors | 1.1.1 | pkg:npm/picocolors@1.1.1 | web/package-lock.json License: ISC | web/package-lock.json; web/package-lock.json | OK |
| transitive | picomatch | 4.0.7 | pkg:npm/picomatch@4.0.7 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | postcss | 8.5.26 | pkg:npm/postcss@8.5.26 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| direct | react | 19.2.8 | pkg:npm/react@19.2.8 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| direct | react-dom | 19.2.8 | pkg:npm/react-dom@19.2.8 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | react-router | 7.18.2 | pkg:npm/react-router@7.18.2 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| direct | react-router-dom | 7.18.2 | pkg:npm/react-router-dom@7.18.2 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | rolldown | 1.2.6 | pkg:npm/rolldown@1.2.6 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | scheduler | 0.27.0 | pkg:npm/scheduler@0.27.0 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | set-cookie-parser | 2.7.2 | pkg:npm/set-cookie-parser@2.7.2 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | source-map-js | 1.2.1 | pkg:npm/source-map-js@1.2.1 | web/package-lock.json License: BSD-3-Clause | web/package-lock.json; web/package-lock.json | OK |
| transitive | tinyglobby | 0.2.17 | pkg:npm/tinyglobby@0.2.17 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| direct | typescript | 7.0.2 | pkg:npm/typescript@7.0.2 | web/package-lock.json License: Apache-2.0 | web/package-lock.json; web/package-lock.json | OK |
| direct | vite | 8.2.2 | pkg:npm/vite@8.2.2 | web/package-lock.json License: MIT | web/package-lock.json; web/package-lock.json | OK |
| transitive | adler2 | 2.0.1 | pkg:cargo/adler2@2.0.1 | web/src-tauri/Cargo.lock License: 0BSD OR MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | aho-corasick | 1.1.5 | pkg:cargo/aho-corasick@1.1.5 | web/src-tauri/Cargo.lock License: Unlicense OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | alloc-no-stdlib | 2.0.4 | pkg:cargo/alloc-no-stdlib@2.0.4 | web/src-tauri/Cargo.lock License: BSD-3-Clause | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | alloc-stdlib | 0.2.4 | pkg:cargo/alloc-stdlib@0.2.4 | web/src-tauri/Cargo.lock License: BSD-3-Clause | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | anyhow | 1.0.104 | pkg:cargo/anyhow@1.0.104 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | autocfg | 1.5.1 | pkg:cargo/autocfg@1.5.1 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | base64 | 0.22.1 | pkg:cargo/base64@0.22.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | bit-set | 0.8.0 | pkg:cargo/bit-set@0.8.0 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | bit-vec | 0.8.0 | pkg:cargo/bit-vec@0.8.0 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | bitflags | 1.3.2 | pkg:cargo/bitflags@1.3.2 | web/src-tauri/Cargo.lock License: MIT/Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | bitflags | 2.13.1 | pkg:cargo/bitflags@2.13.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | block-buffer | 0.10.4 | pkg:cargo/block-buffer@0.10.4 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | brotli | 8.0.4 | pkg:cargo/brotli@8.0.4 | web/src-tauri/Cargo.lock License: BSD-3-Clause AND MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | brotli-decompressor | 5.0.3 | pkg:cargo/brotli-decompressor@5.0.3 | web/src-tauri/Cargo.lock License: BSD-3-Clause/MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | bs58 | 0.5.1 | pkg:cargo/bs58@0.5.1 | web/src-tauri/Cargo.lock License: MIT/Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | byteorder | 1.5.0 | pkg:cargo/byteorder@1.5.0 | web/src-tauri/Cargo.lock License: Unlicense OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | bytes | 1.12.1 | pkg:cargo/bytes@1.12.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | camino | 1.2.5 | pkg:cargo/camino@1.2.5 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | cargo-platform | 0.1.9 | pkg:cargo/cargo-platform@0.1.9 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | cargo_metadata | 0.19.2 | pkg:cargo/cargo_metadata@0.19.2 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | cargo_toml | 0.22.3 | pkg:cargo/cargo_toml@0.22.3 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | cc | 1.4.4 | pkg:cargo/cc@1.4.4 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | cfb | 0.7.3 | pkg:cargo/cfb@0.7.3 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | cfg-if | 1.0.4 | pkg:cargo/cfg-if@1.0.4 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | chrono | 0.4.45 | pkg:cargo/chrono@0.4.45 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | cookie | 0.18.2 | pkg:cargo/cookie@0.18.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | cpufeatures | 0.2.17 | pkg:cargo/cpufeatures@0.2.17 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | crc32fast | 1.5.1 | pkg:cargo/crc32fast@1.5.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | crossbeam-channel | 0.5.16 | pkg:cargo/crossbeam-channel@0.5.16 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | crossbeam-utils | 0.8.22 | pkg:cargo/crossbeam-utils@0.8.22 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | crypto-common | 0.1.7 | pkg:cargo/crypto-common@0.1.7 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | cssparser | 0.36.0 | pkg:cargo/cssparser@0.36.0 | web/src-tauri/Cargo.lock License: MPL-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | cssparser-macros | 0.6.1 | pkg:cargo/cssparser-macros@0.6.1 | web/src-tauri/Cargo.lock License: MPL-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | ctor | 0.8.0 | pkg:cargo/ctor@0.8.0 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | ctor-proc-macro | 0.0.7 | pkg:cargo/ctor-proc-macro@0.0.7 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | darling | 0.23.0 | pkg:cargo/darling@0.23.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | darling_core | 0.23.0 | pkg:cargo/darling_core@0.23.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | darling_macro | 0.23.0 | pkg:cargo/darling_macro@0.23.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | defmt | 1.1.1 | pkg:cargo/defmt@1.1.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | defmt-macros | 1.1.1 | pkg:cargo/defmt-macros@1.1.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | defmt-parser | 1.0.0 | pkg:cargo/defmt-parser@1.0.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | deranged | 0.5.8 | pkg:cargo/deranged@0.5.8 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | derive_more | 2.1.1 | pkg:cargo/derive_more@2.1.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | derive_more-impl | 2.1.1 | pkg:cargo/derive_more-impl@2.1.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | digest | 0.10.7 | pkg:cargo/digest@0.10.7 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | dirs | 6.0.0 | pkg:cargo/dirs@6.0.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | dirs-sys | 0.5.0 | pkg:cargo/dirs-sys@0.5.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | displaydoc | 0.2.7 | pkg:cargo/displaydoc@0.2.7 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | dom_query | 0.27.0 | pkg:cargo/dom_query@0.27.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | dpi | 0.1.2 | pkg:cargo/dpi@0.1.2 | web/src-tauri/Cargo.lock License: Apache-2.0 AND MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | dtoa | 1.0.11 | pkg:cargo/dtoa@1.0.11 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | dtoa-short | 0.3.5 | pkg:cargo/dtoa-short@0.3.5 | web/src-tauri/Cargo.lock License: MPL-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | dtor | 0.3.0 | pkg:cargo/dtor@0.3.0 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | dtor-proc-macro | 0.0.6 | pkg:cargo/dtor-proc-macro@0.0.6 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | dunce | 1.0.5 | pkg:cargo/dunce@1.0.5 | web/src-tauri/Cargo.lock License: CC0-1.0 OR MIT-0 OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | dyn-clone | 1.0.20 | pkg:cargo/dyn-clone@1.0.20 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | embed-resource | 3.0.11 | pkg:cargo/embed-resource@3.0.11 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | equivalent | 1.0.2 | pkg:cargo/equivalent@1.0.2 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | erased-serde | 0.4.10 | pkg:cargo/erased-serde@0.4.10 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | fastrand | 2.5.0 | pkg:cargo/fastrand@2.5.0 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | fdeflate | 0.3.7 | pkg:cargo/fdeflate@0.3.7 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | find-msvc-tools | 0.1.11 | pkg:cargo/find-msvc-tools@0.1.11 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | flate2 | 1.1.10 | pkg:cargo/flate2@1.1.10 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | fnv | 1.0.7 | pkg:cargo/fnv@1.0.7 | web/src-tauri/Cargo.lock License: Apache-2.0 / MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | foldhash | 0.2.0 | pkg:cargo/foldhash@0.2.0 | web/src-tauri/Cargo.lock License: Zlib | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | form_urlencoded | 1.2.2 | pkg:cargo/form_urlencoded@1.2.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | generic-array | 0.14.7 | pkg:cargo/generic-array@0.14.7 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | getrandom | 0.3.4 | pkg:cargo/getrandom@0.3.4 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | getrandom | 0.4.3 | pkg:cargo/getrandom@0.4.3 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | glob | 0.3.4 | pkg:cargo/glob@0.3.4 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | hashbrown | 0.12.3 | pkg:cargo/hashbrown@0.12.3 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | hashbrown | 0.17.1 | pkg:cargo/hashbrown@0.17.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | heck | 0.5.0 | pkg:cargo/heck@0.5.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | hex | 0.4.3 | pkg:cargo/hex@0.4.3 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | html5ever | 0.38.0 | pkg:cargo/html5ever@0.38.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | http | 1.5.0 | pkg:cargo/http@1.5.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | ico | 0.5.0 | pkg:cargo/ico@0.5.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | icu_collections | 2.3.0 | pkg:cargo/icu_collections@2.3.0 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | icu_locale_core | 2.3.0 | pkg:cargo/icu_locale_core@2.3.0 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | icu_normalizer | 2.3.0 | pkg:cargo/icu_normalizer@2.3.0 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | icu_normalizer_data | 2.3.0 | pkg:cargo/icu_normalizer_data@2.3.0 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | icu_properties | 2.3.0 | pkg:cargo/icu_properties@2.3.0 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | icu_properties_data | 2.3.0 | pkg:cargo/icu_properties_data@2.3.0 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | icu_provider | 2.3.1 | pkg:cargo/icu_provider@2.3.1 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | ident_case | 1.0.1 | pkg:cargo/ident_case@1.0.1 | web/src-tauri/Cargo.lock License: MIT/Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | idna | 1.1.0 | pkg:cargo/idna@1.1.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | idna_adapter | 1.2.2 | pkg:cargo/idna_adapter@1.2.2 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | indexmap | 1.9.3 | pkg:cargo/indexmap@1.9.3 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | indexmap | 2.14.0 | pkg:cargo/indexmap@2.14.0 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | infer | 0.19.0 | pkg:cargo/infer@0.19.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | itoa | 1.0.18 | pkg:cargo/itoa@1.0.18 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | jiff | 0.2.35 | pkg:cargo/jiff@0.2.35 | web/src-tauri/Cargo.lock License: Unlicense OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | jiff-core | 0.1.0 | pkg:cargo/jiff-core@0.1.0 | web/src-tauri/Cargo.lock License: Unlicense OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | jiff-tzdb | 0.1.8 | pkg:cargo/jiff-tzdb@0.1.8 | web/src-tauri/Cargo.lock License: Unlicense OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | jiff-tzdb-platform | 0.1.3 | pkg:cargo/jiff-tzdb-platform@0.1.3 | web/src-tauri/Cargo.lock License: Unlicense OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | json-patch | 3.0.1 | pkg:cargo/json-patch@3.0.1 | web/src-tauri/Cargo.lock License: MIT/Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | jsonptr | 0.6.3 | pkg:cargo/jsonptr@0.6.3 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | keyboard-types | 0.7.0 | pkg:cargo/keyboard-types@0.7.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | libc | 0.2.189 | pkg:cargo/libc@0.2.189 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | litemap | 0.8.3 | pkg:cargo/litemap@0.8.3 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | lock_api | 0.4.14 | pkg:cargo/lock_api@0.4.14 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | log | 0.4.34 | pkg:cargo/log@0.4.34 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | markup5ever | 0.38.0 | pkg:cargo/markup5ever@0.38.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | memchr | 2.8.3 | pkg:cargo/memchr@2.8.3 | web/src-tauri/Cargo.lock License: Unlicense OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | mime | 0.3.17 | pkg:cargo/mime@0.3.17 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | miniz_oxide | 0.8.9 | pkg:cargo/miniz_oxide@0.8.9 | web/src-tauri/Cargo.lock License: MIT OR Zlib OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | miniz_oxide | 0.9.1 | pkg:cargo/miniz_oxide@0.9.1 | web/src-tauri/Cargo.lock License: MIT OR Zlib OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | mio | 1.2.2 | pkg:cargo/mio@1.2.2 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | muda | 0.19.3 | pkg:cargo/muda@0.19.3 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | new_debug_unreachable | 1.0.6 | pkg:cargo/new_debug_unreachable@1.0.6 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | num-conv | 0.2.2 | pkg:cargo/num-conv@0.2.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | num-traits | 0.2.19 | pkg:cargo/num-traits@0.2.19 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | once_cell | 1.21.4 | pkg:cargo/once_cell@1.21.4 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | option-ext | 0.2.0 | pkg:cargo/option-ext@0.2.0 | web/src-tauri/Cargo.lock License: MPL-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | parking_lot | 0.12.5 | pkg:cargo/parking_lot@0.12.5 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | parking_lot_core | 0.9.12 | pkg:cargo/parking_lot_core@0.9.12 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | percent-encoding | 2.3.2 | pkg:cargo/percent-encoding@2.3.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | phf | 0.13.1 | pkg:cargo/phf@0.13.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | phf_codegen | 0.13.1 | pkg:cargo/phf_codegen@0.13.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | phf_generator | 0.13.1 | pkg:cargo/phf_generator@0.13.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | phf_macros | 0.13.1 | pkg:cargo/phf_macros@0.13.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | phf_shared | 0.13.1 | pkg:cargo/phf_shared@0.13.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | pin-project-lite | 0.2.17 | pkg:cargo/pin-project-lite@0.2.17 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | plist | 1.10.0 | pkg:cargo/plist@1.10.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | png | 0.17.16 | pkg:cargo/png@0.17.16 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | potential_utf | 0.1.6 | pkg:cargo/potential_utf@0.1.6 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | powerfmt | 0.2.0 | pkg:cargo/powerfmt@0.2.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | precomputed-hash | 0.1.1 | pkg:cargo/precomputed-hash@0.1.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | proc-macro2 | 1.0.107 | pkg:cargo/proc-macro2@1.0.107 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | quick-xml | 0.41.0 | pkg:cargo/quick-xml@0.41.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | quote | 1.0.47 | pkg:cargo/quote@1.0.47 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | raw-window-handle | 0.6.2 | pkg:cargo/raw-window-handle@0.6.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 OR Zlib | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | ref-cast | 1.0.27 | pkg:cargo/ref-cast@1.0.27 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | ref-cast-impl | 1.0.27 | pkg:cargo/ref-cast-impl@1.0.27 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | regex | 1.13.1 | pkg:cargo/regex@1.13.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | regex-automata | 0.4.18 | pkg:cargo/regex-automata@0.4.18 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | regex-syntax | 0.8.11 | pkg:cargo/regex-syntax@0.8.11 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | rustc-hash | 2.1.3 | pkg:cargo/rustc-hash@2.1.3 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | rustc_version | 0.4.1 | pkg:cargo/rustc_version@0.4.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | same-file | 1.0.6 | pkg:cargo/same-file@1.0.6 | web/src-tauri/Cargo.lock License: Unlicense/MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | schemars | 0.8.22 | pkg:cargo/schemars@0.8.22 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | schemars | 0.9.0 | pkg:cargo/schemars@0.9.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | schemars | 1.2.2 | pkg:cargo/schemars@1.2.2 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | schemars_derive | 0.8.22 | pkg:cargo/schemars_derive@0.8.22 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | scopeguard | 1.2.0 | pkg:cargo/scopeguard@1.2.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | selectors | 0.36.1 | pkg:cargo/selectors@0.36.1 | web/src-tauri/Cargo.lock License: MPL-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | semver | 1.0.28 | pkg:cargo/semver@1.0.28 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serde | 1.0.229 | pkg:cargo/serde@1.0.229 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serde-untagged | 0.1.9 | pkg:cargo/serde-untagged@0.1.9 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serde_core | 1.0.229 | pkg:cargo/serde_core@1.0.229 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serde_derive | 1.0.229 | pkg:cargo/serde_derive@1.0.229 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serde_derive_internals | 0.29.1 | pkg:cargo/serde_derive_internals@0.29.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serde_json | 1.0.151 | pkg:cargo/serde_json@1.0.151 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serde_repr | 0.1.21 | pkg:cargo/serde_repr@0.1.21 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serde_spanned | 1.1.1 | pkg:cargo/serde_spanned@1.1.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serde_with | 3.22.0 | pkg:cargo/serde_with@3.22.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serde_with_macros | 3.22.0 | pkg:cargo/serde_with_macros@3.22.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serialize-to-javascript | 0.1.2 | pkg:cargo/serialize-to-javascript@0.1.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | serialize-to-javascript-impl | 0.1.2 | pkg:cargo/serialize-to-javascript-impl@0.1.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | servo_arc | 0.4.3 | pkg:cargo/servo_arc@0.4.3 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | sha2 | 0.10.9 | pkg:cargo/sha2@0.10.9 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | shlex | 2.0.1 | pkg:cargo/shlex@2.0.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | simd-adler32 | 0.3.10 | pkg:cargo/simd-adler32@0.3.10 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | siphasher | 1.0.3 | pkg:cargo/siphasher@1.0.3 | web/src-tauri/Cargo.lock License: MIT/Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | smallvec | 1.15.2 | pkg:cargo/smallvec@1.15.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | socket2 | 0.6.5 | pkg:cargo/socket2@0.6.5 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | softbuffer | 0.4.8 | pkg:cargo/softbuffer@0.4.8 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | stable_deref_trait | 1.2.1 | pkg:cargo/stable_deref_trait@1.2.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | string_cache | 0.9.0 | pkg:cargo/string_cache@0.9.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | string_cache_codegen | 0.6.1 | pkg:cargo/string_cache_codegen@0.6.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | strsim | 0.11.1 | pkg:cargo/strsim@0.11.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | syn | 2.0.119 | pkg:cargo/syn@2.0.119 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | syn | 3.0.4 | pkg:cargo/syn@3.0.4 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | synstructure | 0.13.2 | pkg:cargo/synstructure@0.13.2 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tao | 0.35.3 | pkg:cargo/tao@0.35.3 | web/src-tauri/Cargo.lock License: Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tauri | 2.11.5 | pkg:cargo/tauri@2.11.5 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tauri-build | 2.6.3 | pkg:cargo/tauri-build@2.6.3 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tauri-codegen | 2.6.3 | pkg:cargo/tauri-codegen@2.6.3 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tauri-macros | 2.6.3 | pkg:cargo/tauri-macros@2.6.3 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tauri-plugin-single-instance | 2.4.3 | pkg:cargo/tauri-plugin-single-instance@2.4.3 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tauri-runtime | 2.11.3 | pkg:cargo/tauri-runtime@2.11.3 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tauri-runtime-wry | 2.11.4 | pkg:cargo/tauri-runtime-wry@2.11.4 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tauri-utils | 2.9.3 | pkg:cargo/tauri-utils@2.9.3 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tauri-winres | 0.3.6 | pkg:cargo/tauri-winres@0.3.6 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tendril | 0.5.1 | pkg:cargo/tendril@0.5.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | thiserror | 1.0.69 | pkg:cargo/thiserror@1.0.69 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | thiserror | 2.0.20 | pkg:cargo/thiserror@2.0.20 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | thiserror-impl | 1.0.69 | pkg:cargo/thiserror-impl@1.0.69 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | thiserror-impl | 2.0.20 | pkg:cargo/thiserror-impl@2.0.20 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | time | 0.3.55 | pkg:cargo/time@0.3.55 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | time-core | 0.1.9 | pkg:cargo/time-core@0.1.9 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | time-macros | 0.2.32 | pkg:cargo/time-macros@0.2.32 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tinystr | 0.8.4 | pkg:cargo/tinystr@0.8.4 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tinyvec | 1.12.0 | pkg:cargo/tinyvec@1.12.0 | web/src-tauri/Cargo.lock License: Zlib OR Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tinyvec_macros | 0.1.1 | pkg:cargo/tinyvec_macros@0.1.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 OR Zlib | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tokio | 1.53.1 | pkg:cargo/tokio@1.53.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | toml | 0.9.12+spec-1.1.0 | pkg:cargo/toml@0.9.12%2Bspec-1.1.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | toml | 1.1.4+spec-1.1.0 | pkg:cargo/toml@1.1.4%2Bspec-1.1.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | toml_datetime | 0.7.5+spec-1.1.0 | pkg:cargo/toml_datetime@0.7.5%2Bspec-1.1.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | toml_datetime | 1.1.1+spec-1.1.0 | pkg:cargo/toml_datetime@1.1.1%2Bspec-1.1.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | toml_parser | 1.1.3+spec-1.1.0 | pkg:cargo/toml_parser@1.1.3%2Bspec-1.1.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | toml_writer | 1.1.2+spec-1.1.0 | pkg:cargo/toml_writer@1.1.2%2Bspec-1.1.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tracing | 0.1.44 | pkg:cargo/tracing@0.1.44 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tracing-attributes | 0.1.31 | pkg:cargo/tracing-attributes@0.1.31 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tracing-core | 0.1.36 | pkg:cargo/tracing-core@0.1.36 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | tray-icon | 0.24.2 | pkg:cargo/tray-icon@0.24.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | typeid | 1.0.3 | pkg:cargo/typeid@1.0.3 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | typenum | 1.20.1 | pkg:cargo/typenum@1.20.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | unic-char-property | 0.9.0 | pkg:cargo/unic-char-property@0.9.0 | web/src-tauri/Cargo.lock License: MIT/Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | unic-char-range | 0.9.0 | pkg:cargo/unic-char-range@0.9.0 | web/src-tauri/Cargo.lock License: MIT/Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | unic-common | 0.9.0 | pkg:cargo/unic-common@0.9.0 | web/src-tauri/Cargo.lock License: MIT/Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | unic-ucd-ident | 0.9.0 | pkg:cargo/unic-ucd-ident@0.9.0 | web/src-tauri/Cargo.lock License: MIT/Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | unic-ucd-version | 0.9.0 | pkg:cargo/unic-ucd-version@0.9.0 | web/src-tauri/Cargo.lock License: MIT/Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | unicode-ident | 1.0.24 | pkg:cargo/unicode-ident@1.0.24 | web/src-tauri/Cargo.lock License: (MIT OR Apache-2.0) AND Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | unicode-segmentation | 1.13.3 | pkg:cargo/unicode-segmentation@1.13.3 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | url | 2.5.8 | pkg:cargo/url@2.5.8 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | urlpattern | 0.3.0 | pkg:cargo/urlpattern@0.3.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | utf8_iter | 1.0.4 | pkg:cargo/utf8_iter@1.0.4 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | uuid | 1.26.0 | pkg:cargo/uuid@1.26.0 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | version_check | 0.9.5 | pkg:cargo/version_check@0.9.5 | web/src-tauri/Cargo.lock License: MIT/Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| workspace-root | visiondata-gate-desktop | 0.1.0 | pkg:cargo/visiondata-gate-desktop@0.1.0 | web/src-tauri/Cargo.lock License: Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | vswhom | 0.1.0 | pkg:cargo/vswhom@0.1.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | vswhom-sys | 0.1.3 | pkg:cargo/vswhom-sys@0.1.3 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | walkdir | 2.5.0 | pkg:cargo/walkdir@2.5.0 | web/src-tauri/Cargo.lock License: Unlicense/MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | web_atoms | 0.2.6 | pkg:cargo/web_atoms@0.2.6 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | webview2-com | 0.38.2 | pkg:cargo/webview2-com@0.38.2 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | webview2-com-macros | 0.8.1 | pkg:cargo/webview2-com-macros@0.8.1 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | webview2-com-sys | 0.38.2 | pkg:cargo/webview2-com-sys@0.38.2 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | winapi-util | 0.1.11 | pkg:cargo/winapi-util@0.1.11 | web/src-tauri/Cargo.lock License: Unlicense OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | window-vibrancy | 0.6.0 | pkg:cargo/window-vibrancy@0.6.0 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows | 0.61.3 | pkg:cargo/windows@0.61.3 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-collections | 0.2.0 | pkg:cargo/windows-collections@0.2.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-core | 0.61.2 | pkg:cargo/windows-core@0.61.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-future | 0.2.1 | pkg:cargo/windows-future@0.2.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-implement | 0.60.2 | pkg:cargo/windows-implement@0.60.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-interface | 0.59.3 | pkg:cargo/windows-interface@0.59.3 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-link | 0.1.3 | pkg:cargo/windows-link@0.1.3 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-link | 0.2.1 | pkg:cargo/windows-link@0.2.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-numerics | 0.2.0 | pkg:cargo/windows-numerics@0.2.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-result | 0.3.4 | pkg:cargo/windows-result@0.3.4 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-strings | 0.4.2 | pkg:cargo/windows-strings@0.4.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-sys | 0.59.0 | pkg:cargo/windows-sys@0.59.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-sys | 0.60.2 | pkg:cargo/windows-sys@0.60.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-sys | 0.61.2 | pkg:cargo/windows-sys@0.61.2 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-targets | 0.52.6 | pkg:cargo/windows-targets@0.52.6 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-targets | 0.53.5 | pkg:cargo/windows-targets@0.53.5 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-threading | 0.1.0 | pkg:cargo/windows-threading@0.1.0 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows-version | 0.1.7 | pkg:cargo/windows-version@0.1.7 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows_x86_64_msvc | 0.52.6 | pkg:cargo/windows_x86_64_msvc@0.52.6 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | windows_x86_64_msvc | 0.53.1 | pkg:cargo/windows_x86_64_msvc@0.53.1 | web/src-tauri/Cargo.lock License: MIT OR Apache-2.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | winnow | 0.7.15 | pkg:cargo/winnow@0.7.15 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | winnow | 1.0.4 | pkg:cargo/winnow@1.0.4 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | winreg | 0.55.0 | pkg:cargo/winreg@0.55.0 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | writeable | 0.6.4 | pkg:cargo/writeable@0.6.4 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | wry | 0.55.1 | pkg:cargo/wry@0.55.1 | web/src-tauri/Cargo.lock License: Apache-2.0 OR MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | yoke | 0.8.3 | pkg:cargo/yoke@0.8.3 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | yoke-derive | 0.8.2 | pkg:cargo/yoke-derive@0.8.2 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | zerofrom | 0.1.8 | pkg:cargo/zerofrom@0.1.8 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | zerofrom-derive | 0.1.7 | pkg:cargo/zerofrom-derive@0.1.7 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | zerotrie | 0.2.5 | pkg:cargo/zerotrie@0.2.5 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | zerovec | 0.11.8 | pkg:cargo/zerovec@0.11.8 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | zerovec-derive | 0.11.6 | pkg:cargo/zerovec-derive@0.11.6 | web/src-tauri/Cargo.lock License: Unicode-3.0 | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | zlib-rs | 0.6.7 | pkg:cargo/zlib-rs@0.6.7 | web/src-tauri/Cargo.lock License: Zlib | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |
| transitive | zmij | 1.0.23 | pkg:cargo/zmij@1.0.23 | web/src-tauri/Cargo.lock License: MIT | web/src-tauri/Cargo.lock; web/src-tauri/Cargo.lock | OK |

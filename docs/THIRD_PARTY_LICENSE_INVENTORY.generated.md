# 第三方许可证元数据清单（自动生成）

> 本文件由 `uv.lock` 与项目 `.venv` 中已安装的 `METADATA` 离线生成，仅是可审计的元数据清单；不构成法律审查，也不替代项目顶层 `LICENSE` / `NOTICE`。

- 锁定组件总数（含内部根项目）：`55`
- `REVIEW_REQUIRED`：`9`
- 数据范围：只枚举 `uv.lock` 中的项目及锁定依赖；`.venv` 中不在锁内的分发包不会进入本表。
- 条件依赖：仅通过 marker 入边引用的组件不读取当前平台安装 METADATA，避免跨平台借用许可证据。
- 重建方式：`python tools/generate_supply_chain_artifacts.py`；不需要联网。

| 关系 | 名称 | 版本 | PURL | 许可表达式 / classifiers | 元数据来源 | 复核状态 |
|---|---|---|---|---|---|---|
| internal-root | visiondata-gate | 0.1.0 | pkg:pypi/visiondata-gate@0.1.0 | no license metadata | uv.lock; .venv/site-packages/visiondata_gate-0.1.0.dist-info/METADATA | REVIEW_REQUIRED |
| transitive | altair | 6.2.2 | pkg:pypi/altair@6.2.2 | License: long text (1480 chars); Classifier: License :: OSI Approved :: BSD License | uv.lock; .venv/site-packages/altair-6.2.2.dist-info/METADATA | REVIEW_REQUIRED |
| transitive | annotated-doc | 0.0.5 | pkg:pypi/annotated-doc@0.0.5 | License-Expression: MIT | uv.lock; .venv/site-packages/annotated_doc-0.0.5.dist-info/METADATA | OK |
| transitive | annotated-types | 0.8.0 | pkg:pypi/annotated-types@0.8.0 | License-Expression: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/annotated_types-0.8.0.dist-info/METADATA | OK |
| transitive | anyio | 4.14.2 | pkg:pypi/anyio@4.14.2 | License-Expression: MIT | uv.lock; .venv/site-packages/anyio-4.14.2.dist-info/METADATA | OK |
| transitive | attrs | 26.1.0 | pkg:pypi/attrs@26.1.0 | License-Expression: MIT | uv.lock; .venv/site-packages/attrs-26.1.0.dist-info/METADATA | OK |
| transitive | blinker | 1.9.0 | pkg:pypi/blinker@1.9.0 | Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/blinker-1.9.0.dist-info/METADATA | OK |
| transitive | certifi | 2026.7.22 | pkg:pypi/certifi@2026.7.22 | License: MPL-2.0; Classifier: License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0) | uv.lock; .venv/site-packages/certifi-2026.7.22.dist-info/METADATA | OK |
| transitive | charset-normalizer | 3.4.9 | pkg:pypi/charset-normalizer@3.4.9 | License: MIT | uv.lock; .venv/site-packages/charset_normalizer-3.4.9.dist-info/METADATA | OK |
| transitive | click | 8.4.2 | pkg:pypi/click@8.4.2 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/click-8.4.2.dist-info/METADATA | OK |
| transitive | colorama | 0.4.6 | pkg:pypi/colorama@0.4.6 | conditional dependency; installed METADATA intentionally not used | uv.lock; uv.lock conditional edge | REVIEW_REQUIRED |
| direct | fastapi | 0.141.1 | pkg:pypi/fastapi@0.141.1 | License-Expression: MIT | uv.lock; .venv/site-packages/fastapi-0.141.1.dist-info/METADATA | OK |
| transitive | h11 | 0.16.0 | pkg:pypi/h11@0.16.0 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/h11-0.16.0.dist-info/METADATA | OK |
| transitive | httpcore | 1.0.9 | pkg:pypi/httpcore@1.0.9 | License-Expression: BSD-3-Clause; Classifier: License :: OSI Approved :: BSD License | uv.lock; .venv/site-packages/httpcore-1.0.9.dist-info/METADATA | OK |
| transitive | httptools | 0.8.0 | pkg:pypi/httptools@0.8.0 | License-Expression: MIT | uv.lock; .venv/site-packages/httptools-0.8.0.dist-info/METADATA | OK |
| direct | httpx | 0.28.1 | pkg:pypi/httpx@0.28.1 | License: BSD-3-Clause; Classifier: License :: OSI Approved :: BSD License | uv.lock; .venv/site-packages/httpx-0.28.1.dist-info/METADATA | OK |
| transitive | idna | 3.18 | pkg:pypi/idna@3.18 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/idna-3.18.dist-info/METADATA | OK |
| transitive | iniconfig | 2.3.0 | pkg:pypi/iniconfig@2.3.0 | License-Expression: MIT | uv.lock; .venv/site-packages/iniconfig-2.3.0.dist-info/METADATA | OK |
| transitive | itsdangerous | 2.2.0 | pkg:pypi/itsdangerous@2.2.0 | Classifier: License :: OSI Approved :: BSD License | uv.lock; .venv/site-packages/itsdangerous-2.2.0.dist-info/METADATA | REVIEW_REQUIRED |
| transitive | jinja2 | 3.1.6 | pkg:pypi/jinja2@3.1.6 | Classifier: License :: OSI Approved :: BSD License | uv.lock; .venv/site-packages/jinja2-3.1.6.dist-info/METADATA | REVIEW_REQUIRED |
| transitive | jsonschema | 4.26.0 | pkg:pypi/jsonschema@4.26.0 | License-Expression: MIT | uv.lock; .venv/site-packages/jsonschema-4.26.0.dist-info/METADATA | OK |
| transitive | jsonschema-specifications | 2025.9.1 | pkg:pypi/jsonschema-specifications@2025.9.1 | License-Expression: MIT | uv.lock; .venv/site-packages/jsonschema_specifications-2025.9.1.dist-info/METADATA | OK |
| transitive | markupsafe | 3.0.3 | pkg:pypi/markupsafe@3.0.3 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/markupsafe-3.0.3.dist-info/METADATA | OK |
| transitive | narwhals | 2.24.0 | pkg:pypi/narwhals@2.24.0 | License-Expression: MIT | uv.lock; .venv/site-packages/narwhals-2.24.0.dist-info/METADATA | OK |
| direct | numpy | 2.2.6 | pkg:pypi/numpy@2.2.6 | License: long text (45442 chars); Classifier: License :: OSI Approved :: BSD License | uv.lock; .venv/site-packages/numpy-2.2.6.dist-info/METADATA | REVIEW_REQUIRED |
| transitive | packaging | 26.3 | pkg:pypi/packaging@26.3 | License-Expression: Apache-2.0 OR BSD-2-Clause | uv.lock; .venv/site-packages/packaging-26.3.dist-info/METADATA | OK |
| direct | pandas | 2.3.3 | pkg:pypi/pandas@2.3.3 | License: long text (1616 chars); Classifier: License :: OSI Approved :: BSD License | uv.lock; .venv/site-packages/pandas-2.3.3.dist-info/METADATA | REVIEW_REQUIRED |
| direct | pillow | 12.3.0 | pkg:pypi/pillow@12.3.0 | License-Expression: MIT-CMU | uv.lock; .venv/site-packages/pillow-12.3.0.dist-info/METADATA | OK |
| transitive | pluggy | 1.6.0 | pkg:pypi/pluggy@1.6.0 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/pluggy-1.6.0.dist-info/METADATA | OK |
| transitive | protobuf | 7.35.1 | pkg:pypi/protobuf@7.35.1 | License: 3-Clause BSD License | uv.lock; .venv/site-packages/protobuf-7.35.1.dist-info/METADATA | OK |
| transitive | pyarrow | 24.0.0 | pkg:pypi/pyarrow@24.0.0 | License-Expression: Apache-2.0 | uv.lock; .venv/site-packages/pyarrow-24.0.0.dist-info/METADATA | OK |
| direct | pydantic | 2.13.4 | pkg:pypi/pydantic@2.13.4 | License-Expression: MIT | uv.lock; .venv/site-packages/pydantic-2.13.4.dist-info/METADATA | OK |
| transitive | pydantic-core | 2.46.4 | pkg:pypi/pydantic-core@2.46.4 | License-Expression: MIT | uv.lock; .venv/site-packages/pydantic_core-2.46.4.dist-info/METADATA | OK |
| transitive | pydeck | 0.9.3 | pkg:pypi/pydeck@0.9.3 | License: Apache License 2.0 | uv.lock; .venv/site-packages/pydeck-0.9.3.dist-info/METADATA | OK |
| transitive | pygments | 2.20.0 | pkg:pypi/pygments@2.20.0 | License-Expression: BSD-2-Clause | uv.lock; .venv/site-packages/pygments-2.20.0.dist-info/METADATA | OK |
| direct | pytest | 8.4.2 | pkg:pypi/pytest@8.4.2 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/pytest-8.4.2.dist-info/METADATA | OK |
| transitive | python-dateutil | 2.9.0.post0 | pkg:pypi/python-dateutil@2.9.0.post0 | License: Dual License; Classifier: License :: OSI Approved :: Apache Software License; Classifier: License :: OSI Approved :: BSD License | uv.lock; .venv/site-packages/python_dateutil-2.9.0.post0.dist-info/METADATA | REVIEW_REQUIRED |
| transitive | python-multipart | 0.0.32 | pkg:pypi/python-multipart@0.0.32 | License-Expression: Apache-2.0; Classifier: License :: OSI Approved :: Apache Software License | uv.lock; .venv/site-packages/python_multipart-0.0.32.dist-info/METADATA | OK |
| transitive | pytz | 2026.3.post1 | pkg:pypi/pytz@2026.3.post1 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/pytz-2026.3.post1.dist-info/METADATA | OK |
| transitive | referencing | 0.37.0 | pkg:pypi/referencing@0.37.0 | License-Expression: MIT | uv.lock; .venv/site-packages/referencing-0.37.0.dist-info/METADATA | OK |
| transitive | requests | 2.34.2 | pkg:pypi/requests@2.34.2 | License: Apache-2.0; Classifier: License :: OSI Approved :: Apache Software License | uv.lock; .venv/site-packages/requests-2.34.2.dist-info/METADATA | OK |
| transitive | rpds-py | 2026.6.3 | pkg:pypi/rpds-py@2026.6.3 | License-Expression: MIT | uv.lock; .venv/site-packages/rpds_py-2026.6.3.dist-info/METADATA | OK |
| direct | ruff | 0.15.22 | pkg:pypi/ruff@0.15.22 | License-Expression: MIT | uv.lock; .venv/site-packages/ruff-0.15.22.dist-info/METADATA | OK |
| transitive | six | 1.17.0 | pkg:pypi/six@1.17.0 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/six-1.17.0.dist-info/METADATA | OK |
| transitive | starlette | 1.3.1 | pkg:pypi/starlette@1.3.1 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/starlette-1.3.1.dist-info/METADATA | OK |
| direct | streamlit | 1.61.1 | pkg:pypi/streamlit@1.61.1 | License-Expression: Apache-2.0 | uv.lock; .venv/site-packages/streamlit-1.61.1.dist-info/METADATA | OK |
| transitive | tenacity | 9.1.4 | pkg:pypi/tenacity@9.1.4 | License: Apache 2.0; Classifier: License :: OSI Approved :: Apache Software License | uv.lock; .venv/site-packages/tenacity-9.1.4.dist-info/METADATA | OK |
| transitive | toml | 0.10.2 | pkg:pypi/toml@0.10.2 | License: MIT; Classifier: License :: OSI Approved :: MIT License | uv.lock; .venv/site-packages/toml-0.10.2.dist-info/METADATA | OK |
| transitive | typing-extensions | 4.16.0 | pkg:pypi/typing-extensions@4.16.0 | License-Expression: PSF-2.0 | uv.lock; .venv/site-packages/typing_extensions-4.16.0.dist-info/METADATA | OK |
| transitive | typing-inspection | 0.4.2 | pkg:pypi/typing-inspection@0.4.2 | License-Expression: MIT | uv.lock; .venv/site-packages/typing_inspection-0.4.2.dist-info/METADATA | OK |
| transitive | tzdata | 2026.3 | pkg:pypi/tzdata@2026.3 | License: Apache-2.0 | uv.lock; .venv/site-packages/tzdata-2026.3.dist-info/METADATA | OK |
| transitive | urllib3 | 2.7.0 | pkg:pypi/urllib3@2.7.0 | License-Expression: MIT | uv.lock; .venv/site-packages/urllib3-2.7.0.dist-info/METADATA | OK |
| direct | uvicorn | 0.52.1 | pkg:pypi/uvicorn@0.52.1 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/uvicorn-0.52.1.dist-info/METADATA | OK |
| transitive | watchdog | 6.0.0 | pkg:pypi/watchdog@6.0.0 | conditional dependency; installed METADATA intentionally not used | uv.lock; uv.lock conditional edge | REVIEW_REQUIRED |
| transitive | websockets | 16.1.1 | pkg:pypi/websockets@16.1.1 | License-Expression: BSD-3-Clause | uv.lock; .venv/site-packages/websockets-16.1.1.dist-info/METADATA | OK |

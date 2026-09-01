# VisionData Gate

VisionData Gate 是面向工业视觉算法工程师与质量负责人的数据治理和发布 Agent。它把数据接入、确定性质量工具、动态补证、受控整改、Child Run 复验和人工放行边界组织成一套可追溯工作台。

**[打开公开多页面工作台](https://dukeandbaron.github.io/visiondata-gate-public/#/command-center)**

公开网页运行在 `PUBLIC_SYNTHETIC_REPLAY` 模式。它会下载冻结的 Synthetic-v3 JSON 清单，并在浏览器内复算 JCS SHA-256；只有摘要一致时，才展示 selected/rejected Workers、选择原因、预算、triggering evidence、竞争假设、缺失证据、六阶段运行状态和 Parent/Human/Child 血缘。它不是截图，但它也不是生产系统。

## 公开边界

- 只读静态回放，无 Python 后端、账户、API Key 输入或生产写操作。
- 不包含客户/工厂原图、私域 mask、真实类别名、设备帧、本机数据库、调试日志、API Key、DPAPI 密文、个人提交历史或含审批人显示区域的私有截图；公开二进制逐文件绑定 SHA-256。
- `official_submission=PENDING`、`official_evaluation=NOT_EVALUATED`、`production_release_allowed=false`。
- AI 只提供证据组织、受控编排和门禁建议；质量负责人保留最终判断权。
- 公共镜像使用新 Git 历史；它不是私有开发仓的镜像，也不含 release ZIP、PPTX、PDF、视频或私域回执。

完整规则见 [GitHub 与 GitHub Pages 公开边界](docs/PUBLICATION_BOUNDARY.md)。

## 本地开发

Python 内核：

```powershell
uv sync --frozen
uv run python -m pytest
```

React 工作台：

```powershell
cd web
npm ci
npm run typecheck
npm run build
```

公开 Pages 构建：

```powershell
cd web
$env:VITE_VISIONDATA_PUBLIC_REPLAY = "true"
$env:VISIONDATA_WEB_BASE_PATH = "/visiondata-gate-public/"
npm run build
python ..\tools\check_public_pages.py --dist dist
```

本地真实工作台、BYOK Provider Profile、Hosted AgentTeams 和桌面封装具有更强的本机信任边界；请先阅读 [运行说明](docs/RUNNING.md)、[API 快速上手](docs/API_QUICKSTART.md) 与 [外部模型配置](docs/EXTERNAL_MODEL_CONFIGURATION.md)。

## 可复用资产

- `src/visiondata_gate/`：受控 Agent 内核、证据、CAPA、血缘与发布门禁实现。
- `schemas/`、`rulepacks/`、`skills/`：可迁移合同和工业规则。
- `adapters/`、`agentteams/`：外部系统与 Hosted AgentTeams 的显式合同。
- `sample_data/`：固定合成样本及 SHA-256 清单。
- `web/`：React/Tauri 多页面工作台与静态公开回放模式。
- `tests/`：合同、失败关闭、安全边界和回放测试。

Apache-2.0。合并 CycloneDX 同时绑定 `uv.lock`、`web/package-lock.json` 与 `web/src-tauri/Cargo.lock`；Rust 部分明确限定为 Windows `x86_64-pc-windows-msvc` 目标可达依赖，并使用不含作者或本机路径的许可证快照。详见 [SBOM](docs/SBOM.cdx.json)、[Cargo 许可证快照](docs/CARGO_LICENSES.locked.json)、[第三方许可证清单](docs/THIRD_PARTY_LICENSE_INVENTORY.generated.md) 和 [Notices](docs/THIRD_PARTY_NOTICES.md)。

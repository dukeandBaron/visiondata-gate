# VisionData Gate｜运行与验证

VisionData Gate 的产品形态是本地或内网部署的工业 Web 工作台：浏览器负责工作台界面，FastAPI 与本地服务负责案件、证据和策略治理。它不是互联网 SaaS；当前 Web 运行不依赖桌面包装。本地已经生成 Tauri 2 EXE 与 unsigned NSIS test installer，但干净 Windows 安装/卸载、签名和正式发布均未验证。

当前发布状态见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。本地运行成功不等于 RC3 已冻结、官方已提交或生产可以放行。

## 环境

- Windows；
- Python 3.12 或 3.13；
- [uv](https://docs.astral.sh/uv/)；
- 新多页面 Web 需要 Node.js 22 或更高版本；
- 核心确定性闭环不要求 GPU、外部模型或付费 API。

## 1. 按锁文件安装

```powershell
.\setup_env.ps1
```

脚本执行 `uv sync --frozen --all-extras`，只接受当前 `uv.lock`。它不会升级 pip、重新求解依赖或静默退回未锁定的 `pip install -e`。

需要指定解释器时：

```powershell
.\setup_env.ps1 -Python py
```

## 2. 启动多页面 Web 工作台

Windows 首次运行：

```powershell
.\run_workbench.ps1 -Install
```

后续直接执行 `.\run_workbench.ps1`，访问 `http://127.0.0.1:4173/workspace`。前端开发热更新使用：

```powershell
.\run_workbench.ps1 -Mode Dev
```

该入口会同时启动本地 API 和 Web。`/workspace` 提供 IDE 式 Explorer、真实图片上传、交互画布、框选标注、属性检查、本地 revision 保存、可审计 Agent Activity Trace、Evidence Copilot 与强制人工复核工单；其他路由提供数据集选择、指挥中心、案件、Evidence Lab、CAPA、血缘、运行回执、集成、治理、评委模式和平台设置。上传的源图、预览、标注、Agent 回执和工单保存在 `output/product/operator_workspace/`，原始图片不会发送到 OpenToken。当前 Agent 工作台使用本地确定性工具且 `model_call_count=0`，不能声明 Gemini 已连接。冻结只读页面仍使用脱敏 fixture；React 页面不读取 OpenToken Key。

如果只需启动一侧，可分别运行 `.\run_api.ps1` 和 `.\run_web.ps1`。当前接口只监听本机，`X-Actor-User-Id` 仅用于本地逻辑作用域，不代表生产认证。macOS/Linux 的 Web 源码运行方式及桌面包未完成边界见 [Web README](../web/README.md)。

`run_web.ps1` 的 Preview 模式会为当前进程生成独立、不可变的静态资源目录。运行中的页面不会因为另一个终端执行 `npm run build` 而丢失旧哈希分块；端口被占用时也会直接失败，不会静默漂移到其他端口。

## 3. 启动复赛隔离 Reviewer 工作台

```powershell
.\run_semifinal_demo.ps1
```

该入口不是测试桩，也不是生产项目的静态截图。它会使用正常
`ProductService`，在 `output/semifinal_demo/product/` 下幂等准备一个隔离项目，
依次生成：

```text
冻结合成回放资产
→ 受控 Task
→ Parent Incident 暂停
→ 具名人工决定
→ 不可变 Child Case 续跑
→ Interaction Receipt
```

启动器先由准备进程写入 `semifinal_demo_manifest.json`，再由独立验证进程
完成“manifest 声明 → Product SQLite → Incident 源工件 → 两张视觉资产字节”
三方对账。Task 必须保持 `PASS / DEMO_ONLY`，Child Incident 必须保持
`INVESTIGATION_REQUIRED / CONTINUE_HOLD`，同时锁定 ProductRoot、精确 Task 深链、
开放问题数以及 `production_release_allowed=false`、
`machine_write_permitted=false`、客户与 shadow 指标边界。验证通过后才打开
manifest 绑定的 `/review?task=...`，不会依赖“最新任务”猜测评审对象。默认
使用 API `8788` 和 Web `4180`；指定隔离 `ProductRoot` 时，只要任一端口已被
占用且进程身份无法证明，启动器就会失败关闭，避免把其他工作台或产品数据库
冒充成复赛 Demo。

边界保持不变：该入口只证明冻结合成 fixture 上的本地产品闭环；
`production_release_allowed=false`、`machine_write_permitted=false`，真实工厂
误放行率、误拦截率和整改后通过率仍为
`NOT_MEASURED_PENDING_ADJUDICATION`。当前 UI 回执与 89.9 秒冻结视频分别证明
多视口界面稳定性和 Synthetic Fixture Replay 叙事时长；它们不等于三次全新环境冷启动
均在 89.9 秒内，也不证明实时重算或工厂效果。当前 60 秒现场主轨会提前打开标签页，
不得称为 60 秒冷启动；若对外作出这一声明，必须另行保存三次启动时间、console、截图与 manifest 摘要。

## 4. 启动团队工作台

```powershell
.\run_workbench.ps1 -ApiPort 8787 -WebPort 4173
```

工作台默认使用 `output/product/product.sqlite3`。主要页面包括：

- 工作台；
- 异常处置；
- Reviewer Mode；
- 项目与数据源；
- 审核记录；
- 能力目录；
- API 接入；
- 安全与权限。

真实本地数据只能从服务端 allowlist 内授权。操作者必须主动填写用途与权利依据；系统不会代填或推定权利状态。

## 5. 启动 REST API

```powershell
.\run_api.ps1 -Port 8787
```

OpenAPI：`http://127.0.0.1:8787/docs`

`X-Actor-User-Id` 只用于本地成员关系与逻辑作用域，不是登录认证、API Key 或生产 IAM。完整调用见 [API_QUICKSTART.md](API_QUICKSTART.md)。

## 6. 运行合成工程闭环

Reviewer Demo 用于展示产品；Synthetic-v3 用于复验确定性工具和整改路径。两者不要混写。

```powershell
uv run --frozen python -m visiondata_gate.cli agent-demo `
  --seed 20260809 `
  --output output\agent-demo `
  --memory-path output\agent-demo\runtime-memory.json
```

冻结合成验收值：

```text
initial decision=RECAPTURE
initial findings=12
recheck decision=PASS
recheck findings=0
F1=1.00
```

这些数字只适用于程序化注入真值，不证明真实工厂效果。

## 7. 运行确定性基准与复用合同

```powershell
uv run --frozen python -m visiondata_gate.cli dynamic-benchmark `
  --output output\dynamic-benchmark\dynamic_benchmark.json `
  --repeats 3

uv run --frozen python -m visiondata_gate.cli rulepack-verify `
  --rulepack rulepacks\industrial-v1.json `
  --output output\reuse\rulepack_receipt.json

uv run --frozen python -m visiondata_gate.cli adapter-conformance `
  --manifest adapters\examples\omni-readonly-manifest.json `
  --observation adapters\examples\omni-readonly-observation.json `
  --output output\reuse\adapter_conformance_receipt.json
```

DynamicBench 评测的是确定性触发语义，实际模型调用为 0。Adapter 或 Rule Pack 的本地 `PASS` 不等于外部系统已经连接。

ProductService / API 默认不启用 Rule Pack，运行证据保持
`rule_pack_runtime_status=NOT_CONFIGURED`。如需让授权 Omni 任务使用已审核规则包，
在本地环境设置 `VISIONDATA_OMNI_RULEPACK_PATH` 为该 JSON 文件的绝对路径后重启服务。
服务启动时会严格解析、编译并钉住源文件 SHA-256；任务执行前若文件缺失或哈希漂移，
任务将失败关闭。这里不是热加载，规则包变更必须经过审核并重启服务。

## 8. 验证代码与冻结证据

功能开发期先运行受影响测试。候选冻结前执行：

```powershell
uv run --frozen python -m pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen python -m compileall -q src tools
uv lock --check
Push-Location web; npm run check; Pop-Location
```

不要在文档中复制易过期的测试总数。最终回执应绑定 Git commit/tree、dirty 状态、测试结果、SBOM、clean-extract 和候选 ZIP SHA-256。

## 9. CAPA 与 Child Run 边界

CAPA 只能通过产品服务或 API 执行，不能直接覆盖父来源。真实 `_05` 是已有权威本地证据，不得为了得到更好结果在同一 product root 上重复执行。

如需新实验，必须使用新的私有 product root、新的 evidence namespace 和新的回执。Parent Evidence、Child Run、人工决定与最终责任队列必须保持可交叉验证。

当前 `_05` 的有效结论为：

```text
findings=49 → 33
verified_closed=6
open=43
status=TRANSFERRED_TO_INVESTIGATION
production_release_allowed=false
```

## 10. 外部模型与外部系统

CVAT/FiftyOne 当前完成的是本地合同验证；真实外部连接需要只读可达、身份读取与响应哈希同时成立。外部模型同样必须提供端点、后端身份、真实响应与运行回执。OpenAI-compatible Gateway 的 Base URL 与本机 Key 配置见 [EXTERNAL_MODEL_CONFIGURATION.md](EXTERNAL_MODEL_CONFIGURATION.md)；Reviewer Workbench 只显示是否已配置，永不接收或返回 Key。

连接方法见 [API_QUICKSTART.md](API_QUICKSTART.md) 和 [ECOSYSTEM_P0_UPGRADE.md](ECOSYSTEM_P0_UPGRADE.md)。没有这些回执时，状态必须保持 `NOT_CONNECTED`、`LOCAL_CONTRACT_ONLY` 或 `NOT_TESTED`。

## 11. 分层测试与完整回归

测试分层只用于缩短开发反馈时间，不改变冻结前的完整测试分母。仓库根目录的
`run_tests.ps1` 提供六个显式层级：

| 层级 | 覆盖范围 | 用途 |
|---|---|---|
| `Quick` | 核心合同 + 非慢速后端集成 | 日常修改后的快速门禁，目标控制在 90 秒内 |
| `Backend` | 全部核心合同 + 全部后端集成 | 后端生命周期、API、存储与本地协议回归 |
| `Release` | 构包、供应链与 Release Attestation | 发布安全与可复现性专项检查 |
| `Benchmark` | 基准、评测与固定分母实验 | 运行成本较高的科学证据专项检查 |
| `UI` | Streamlit、React/website 源码合同与 Reviewer 页面 | 界面源码及只读展示合同检查 |
| `Full` | 不使用 marker 过滤的全仓测试 | 冻结候选前唯一完整回归 |

常用命令：

```powershell
.\run_tests.ps1 -Tier Quick
.\run_tests.ps1 -Tier Backend
.\run_tests.ps1 -Tier Release
.\run_tests.ps1 -Tier Benchmark
.\run_tests.ps1 -Tier UI
.\run_tests.ps1 -Tier Full
```

默认生成 JUnit 回执到 `.pytest_cache/regression-<tier>.xml`。临时调试时可使用
`-NoJUnit`，但冻结报告必须保留 Full 的 JUnit 文件。直接运行
`uv run --frozen python -m pytest -q` 与 `Full` 等价；不能用 Quick 的通过结果替代
Full，也不能把 marker deselected 项写成已通过。

历史 Quick 数字只证明对应工作树的快速层级，不能替代当前 Full，也不在本页硬编码。
当前 Full 计数、JUnit SHA、Git commit/tree 与候选 ZIP SHA 只从最终 detached receipt 读取。

## 12. 发布与构包

当前 `tools/build_submission_package.py` 是冻结 RC2 工具，不能被当成 RC3 发布器。RC3 由
`tools/build_rc3_release_evidence.py` 生成 Full、双构包、clean-extract 与 unsigned
Attestation，再由 `tools/verify_release_attestation.py` 对 detached release namespace、
匹配的 clean checkout 与声明 toolchain 做本地完整性验证；任一对账项缺失即退回
`HOLD_AS_RELEASE_TREE`。

RC2 历史一致性工具只存在于完整 source checkout，不是 RC3 主候选随包入口。评委解压
RC3 候选后应使用本节的 `run_semifinal_demo.ps1`；RC3 完整性由包外 release namespace
和 `verify_release_attestation.py` 对账。

所有发布包都必须满足：

- 原始图像、私有路径、凭据、缓存和运行数据库不进入公开包；
- 两个隔离 workspace 的声明输出 SHA-256 一致；这不等于独立可信 builder 证明；
- 对候选内容执行 clean-extract 文件审计，并对最终 ZIP 另行执行 fresh-extract API/Web 与浏览器 smoke；
- 包外 detached release namespace 绑定两份候选 ZIP、Git、测试、SBOM 与构建身份；单独复制候选 ZIP 与 Attestation 不足以复验；
- SHA-256 只声明完整性，签名与可信时间戳按真实配置单独声明。

完整实验分母见 [EVIDENCE_AND_BENCHMARKS.md](EVIDENCE_AND_BENCHMARKS.md)，可声明边界见 [CLAIM_SCOPE.md](CLAIM_SCOPE.md)。

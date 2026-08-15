# 运行与确定性构包说明

> 参赛定位：GOAI 赛道二“无界应用 Boundless Agents”与 AI+工业制造；工业视觉数据治理与发布 Agent 是主应用，Infra 是可信后台。`local-deterministic` 只表示本地可审计运行，不等于 hosted AgentTeams/Matrix 已连接。

## 环境

- 已验证项目环境：Windows、Python 3.12.5、`uv`
- 支持范围：Python 3.12 或 3.13，具体依赖见 `pyproject.toml`
- 核心闭环、报告与构包不需要网络、GPU 或外部模型 API
- `uv.lock` 已生成；源码候选包的干净环境复验结果记录在包外 detached receipt

## 推荐：使用 uv 创建项目环境

PowerShell：

```powershell
uv sync --python 3.12.5 --extra ui --extra api --extra qa
```

该命令使用项目 `.venv` 并按 `uv.lock` 同步依赖。不要把 `.venv`、缓存或本地输出放入提交包。

不使用 `uv` 时，可运行：

```powershell
.\setup_env.ps1 -Python py
```

## 运行全量测试

```powershell
uv run python -m pytest -q
```

不要在本文复制易过期的测试计数。提交前以
`10_reports/FINAL_QA_REPORT_20260816.json#/engineering` 和最新包外 detached
receipt 为唯一计数锚点；任何代码变更后必须重新运行并更新它们。

跳过项是 `tests/test_repair_evaluation.py` 的 symlink 安全用例：当前 Windows 环境不能创建测试 symlink。该结果不是测试失败，但也不等于该用例已在本机执行；发布前应在支持 symlink 的干净环境补跑。

历史冻结压力检查对合成数据 `seed=0..31` 完成 `32/32` 次闭环。该结果只证明冻结合成场景，不代表真实工业数据表现。

评审双场景可复现命令：

```powershell
uv run python tools\build_reviewer_scenario_suite.py `
  --output output\reviewer-scenario-suite `
  --seed 20260812
```

权威冻结接收单为
`07_results/reviewer_scenario_suite_20260812_v3/scenario_suite_receipt.json`。它要求
同输入/合同/策略下 happy path `RECAPTURE → PASS`、missing-worker
`DEFER → DEFER`，并验证执行配置摘要与 run ID 不碰撞。

## 运行完整 Demo

推荐运行可观察 Agent 版本：

```powershell
uv run python -m visiondata_gate.cli agent-demo `
  --seed 20260809 `
  --output output\agent-demo `
  --memory-path output\runtime-memory.json
```

该命令执行 Router、Planner、四个并行 Worker、Tool Gateway、AI Council、Policy Judge、修复复验和证据交付，并额外生成 `evidence/agent_runtime_trace.json`。默认不访问网络。

若已有本机 OpenAI-compatible 服务，可以显式配置：

```powershell
uv run python -m visiondata_gate.cli agent-demo `
  --seed 20260809 `
  --output output\agent-demo-llm `
  --backend openai_compatible `
  --endpoint http://127.0.0.1:11434/v1/chat/completions `
  --model qwen3:8b
```

远程端点还必须增加 `--allow-remote-model`，并使用 HTTPS。API Key 只从进程环境变量 `VISIONDATA_LLM_API_KEY` 读取，不接受命令行明文参数，也不写入 trace。

保留的兼容 Demo 命令：

直接运行 CLI：

```powershell
uv run python -m visiondata_gate.cli demo `
  --seed 20260809 `
  --output output\demo
```

或使用包装脚本：

```powershell
.\run_demo.ps1 -Seed 20260809 -Output output\demo
```

成功输出应同时满足：首轮 `RECAPTURE`、12 个 findings；修复后 `PASS`、0 个 findings；F1 与工单召回率均为 `1.0`。这些验收值仅适用于冻结合成 Demo。

## 运行 Streamlit 工作台

```powershell
.\run_app.ps1 -Port 8502
```

浏览器访问 `http://127.0.0.1:8502`。默认界面是企业工作台：工作台、项目、审核记录、能力目录、API 接入与安全权限。HTML5 Canvas、任务 DAG、ContextTransfer、AgentTeams 与审计回执收在完成任务的“高级审计”中；赛事与外部验证缺口收在安全权限的折叠区和评审文档中。Council 中所有角色均为 AI 角色，不是真人专家；角色投票不是独立证据。

## 本地 REST API

```powershell
.\run_api.ps1 -Port 8787
```

访问 `http://127.0.0.1:8787/docs` 查看 OpenAPI。API 与工作台共用 `output/product/product.sqlite3`、任务目录和 `ProductService`，默认只绑定本机。详细调用见 [API_QUICKSTART.md](API_QUICKSTART.md)。

`X-Actor-User-Id` 是本地成员关系与逻辑作用域，不是身份认证。UI 与 API 多进程并行时不自动判定另一进程的 RUNNING 任务已中断；当前原型没有租约调度、生产 IAM、客户部署或 SLA。

## 冻结证据

当前冻结运行与材料：

- `07_results/frozen_demo_20260809/`
- `07_results/VisionDataGate_FrozenDemo_Evidence.zip`
- 当前浏览器截图保留在本地 `output/playwright/`，不进入公开候选包；RC1 的包内视觉锚点是终版 PPT/PDF 与其来源说明。
- `deliverables/GOAI_VisionDataGate_BoundlessAgents_20260816.pptx`
- `deliverables/GOAI_VisionDataGate_BoundlessAgents_20260816.pdf`
- `docs/SBOM.cdx.json`
- `docs/THIRD_PARTY_LICENSE_INVENTORY.generated.md`

`VisionDataGate_GOAI_FinalDemo_20260813.mp4`、对应 QA JSON 和联系表保留为本地历史工程证据，不进入 Boundless Agents RC1。三者在源码工作区存在时必须成套并通过严格哈希/帧数检查；在干净解压候选包中必须同时缺席，任何部分残留都视为构包缺陷。若赛事平台另需视频，应基于当前 Reviewer Mode 重新录制、单独 QA 后作为独立上传物，不应回塞到已冻结的 RC1 ZIP。

evidence ZIP 含 9 个证据条目、内部 `submission_manifest.json` 和一个已计算的 SHA-256，ZIP CRC 自检无坏成员。它不是完整源码提交包，因此不能用“缺少源码必需文件”把它误写成最终提交包审计通过。

2026-08-13 本地演示视频（早于 Boundless Agents RC1 材料冻结）为 170.02 秒、1920×1080、30 fps、H.264 + AAC，大小 12,826,648 bytes。`final_video_qa_20260813.json` 使用 `visiondata-gate.video-qa.v2`，记录 5100 帧完整解码、10/10 场景抽帧、音轨与匿名载荷扫描结果；MP4 SHA-256 为 `399cc2f26e1eb07634ec7a9e41dd499a43452d50c2f08d36245f1e956d8b2ad2`。`tests/test_release_artifacts.py` 在本地三件套存在时硬校验 v2 QA、MP4、联系表、文件大小、SHA-256、帧数和场景时间点；在 RC1 中则硬校验三件套同时缺席。

机器 QA 的 `PASS` 只表示该视频文件通过上述技术检查，不证明真实工业效果、客户验收、生产部署、hosted AgentTeams 连接或官网提交。2026-08-10、2026-08-12、2026-08-13 的视频及其 QA 均仅作为本地历史审计材料保留，不得用作 Boundless Agents RC1 的终版标识。

单独复核本地历史视频证据与 RC1 排除契约：

```powershell
uv run python -m pytest -q tests\test_release_artifacts.py
```

## 重建供应链材料

在锁定环境中离线生成 CycloneDX 1.6 SBOM 和许可证元数据清单：

```powershell
uv run python tools\generate_supply_chain_artifacts.py
```

生成器只枚举 `uv.lock` 中的 55 个组件，并忽略环境中不在锁内的临时包。清单中的 `REVIEW_REQUIRED` 是待权利主体复核标志，不构成法律结论，也不替代顶层 `LICENSE` / 正式 `NOTICE`。

## 从 GateResult 生成证据文件

```python
from pathlib import Path

from visiondata_gate.evidence import write_evidence_artifacts
from visiondata_gate.reporting import write_offline_html

output = Path("artifacts")
write_evidence_artifacts(output, gate_result, evaluation_result)
write_offline_html(output / "report.html", gate_result, evaluation_result)
```

同一个冻结 `GateResult` 和 `EvaluationResult` 应生成相同 JSON、CSV 与 HTML 字节。序列化拒绝 NaN、Infinity、无时区 datetime、非字符串字典键和无序 set。

## 构建源码提交候选 ZIP

必须在 README、表单、视频、SBOM、许可证元数据清单和其他工程材料冻结后再执行：

```powershell
uv run python tools\build_submission_package.py `
  --output deliverables\VisionData_Gate_GOAI_BoundlessAgents_RC1_20260816.zip
```

若目标已存在，命令默认拒绝覆盖；只有确认目标后才使用 `--force`。默认构包会：

- 跳过 `.git`、虚拟环境、缓存、日志、旧 ZIP、`dist`、`output` 和安装生成的 `*.egg-info`
- 拒绝符号链接、路径逃逸、大小写冲突和凭据模式
- 生成 `submission_manifest.json`，记录每个载荷文件的大小与 SHA-256
- 使用固定顺序、`1980-01-01 00:00:00`、`0644` 权限和 stored compression
- 构包后执行路径、manifest、哈希和清洁解压审计

独立审计源码提交候选包：

```powershell
uv run python tools\audit_submission_package.py `
  deliverables\VisionData_Gate_GOAI_BoundlessAgents_RC1_20260816.zip
```

## 字节复现检查

在两个不存在的目标路径分别构包并比较 SHA-256：

```powershell
uv run python tools\build_submission_package.py --output output\release\a.zip
uv run python tools\build_submission_package.py --output output\release\b.zip
Get-FileHash -Algorithm SHA256 output\release\a.zip,output\release\b.zip
```

两个哈希不一致时不得提交。候选包哈希必须在所有输入冻结后重新生成，不能预填或沿用 evidence ZIP 的哈希。最终哈希、独立审计与全新目录复测结果写入包外 detached receipt，避免包内自引用。

## 仍未闭合

- 顶层 LICENSE 与正式 NOTICE 的权利主体确认
- 真实客户/真实工业数据验证
- 官网上传与提交回执

无论上述事项何时完成，`PASS` 都只允许进入 `sandbox_experiment_training_pool`，不代表真实工业效果或生产授权。

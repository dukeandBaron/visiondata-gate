# VisionData Gate 终版工程 QA 报告（Agent Infra 对齐复核）

核验日期：2026-08-12（北京时间）；独立 QA run：`run_20260812T134219+0800`

结论：当前版本达到“可运行、可验证、可复用的 GOAI Agent Infra（新质基座）初赛工程候选”状态，AI+工业制造是行业闭环实例。它不是官网提交回执、真实工业验证、开源许可决定或法律/安全认证。

## 已验证基线

- 环境：Windows、Python 3.12.5；`uv sync --frozen --extra ui --extra qa` 成功，依赖由 `uv.lock` 固定。
- 测试：`86 passed, 1 skipped`。唯一跳过项是本机无权限创建文件 symlink 的安全用例；不是失败，也不能写成该用例已在本机执行。
- 静态门：`ruff check .` 与 `ruff format --check .` 均通过。
- 冻结闭环：`seed=20260809` 首轮 `RECAPTURE / 12 findings`，12 份工单；reserve 模拟修复后 `PASS / 0 findings`。
- 隐藏真值：Precision / Recall / F1 = `1.0 / 1.0 / 1.0`，工单召回率 `1.0`，关键坏批次错误发布率 `0.0`。
- 压力检查：合成 `seed=0..31` 共 `32/32` 闭环与隐藏真值一致；只证明冻结合成场景。
- UI：Streamlit AppTest 覆盖初始渲染、点击主闭环、五个标签页、指标、表格、下载与 evidence ZIP 复审。
- 路演：PPTX 12 页、PDF 12 页；首屏已统一为 `GOAI Agent Infra · 新质基座 · AI+工业制造`，本报告的自动门验证文件完整性与页数，首屏另有渲染目检。
- 视频：170.02 秒、1920×1080、30 fps、H.264 High + AAC-LC；5100 帧全解码、九点抽帧、音轨和匿名扫描通过。
- 供应链：CycloneDX 1.6 SBOM 与许可证元数据清单可离线确定性重建；51 个锁定组件精确匹配，8 项保持 `REVIEW_REQUIRED`。

## 冻结产物锚点

| 产物 | 字节数 | SHA-256 |
|---|---:|---|
| `07_results/VisionDataGate_FrozenDemo_Evidence.zip` | 93,451 | `1e1418c26f28ffb7c6ebefa7109cfdb8ff98468ce0dcac8c44833069cef022d0` |
| `deliverables/GOAI_VisionDataGate_Roadshow_20260809.pptx` | 471,779 | `e38e6ca839744c9834af8181b064eaa0b2de43910c77689dbc184f96a3c647ea` |
| `deliverables/GOAI_VisionDataGate_Roadshow_20260809.pdf` | 13,093,999 | `2c7a642e6070c805d11afbe34c22cc0d55f4e7853728fb26046b42c84f328852` |
| `deliverables/VisionDataGate_GOAI_AutoDemo_20260810.mp4` | 16,119,566 | `8804f5fd8338b83627fe969603d1e095ae00bba25a6a532513478f9812f81594` |
| `deliverables/_qa/video_qa.json` | 1,697 | `63e612ad5b568cec345b15da5001f87c9f89d562170caa0933ff85b20d1b697e` |
| `docs/SBOM.cdx.json` | 36,809 | `456ad56a25f3a342c3509192dd5a2670b0dead13c3f514afdc0bd01f3f857daa` |
| `docs/THIRD_PARTY_LICENSE_INVENTORY.generated.md` | 10,275 | `021a7d2b4c4e94961e371cde066a3d831c9bbe59391a281f69c0fa103610b692` |
| `uv.lock` | 131,018 | `db2e01704eb790f390b661e5cf65055e08954f89148fc48b494e9d1bf484ed28` |

源码候选 ZIP 的哈希不写进包内，避免自引用。双构包比较、独立 ZIP 审计、全新目录解压、`uv sync --frozen`、解压后测试/Ruff/CLI smoke 的结果写入同目录包外 detached receipt。

## 仍不能宣称

- 未取得真实客户访谈、真实工业数据评测或产线部署证据。
- `PASS` 只允许进入 `sandbox_experiment_training_pool`，不代表产品、零件、模型、数据授权或安全合格。
- 五个专家角色都是共享后端的 AI 专家系统角色，不是真人专家，也不是五个独立模型。
- 顶层 LICENSE 与正式 NOTICE 尚未由权利主体确认；SBOM/元数据清单不构成法律审查。
- 尚未执行官网上传，也没有平台提交或晋级回执。

## Agent Infra 对齐补充

- AgentTeams 契约显式包含 Manager、Team Leader、Worker、Council、Policy Judge、Repair/Audit Operator，多于官方“不少于 3 个不同职能 Agent”的门槛。
- Team / Room / Task / Identity / Skill、工具白名单、证据矩阵、reason trace、工单与同合同复验均写入可下载产物。
- `connection_status=mapped_not_connected`、`matrix_connected=false`：当前是本地 AgentTeams/TeamHarness 契约映射，不是 hosted Matrix 连接回执。
- 候选源码包：`deliverables/VisionData_Gate_GOAI_AgentInfra_SubmissionCandidate_20260812.zip`；本轮构包 `223` 个条目、`222` 个载荷文件。最终字节数与 SHA-256 只记录在包外 detached receipt，避免自引用。
- 构包会排除 `.playwright-cli`、时间戳 QA 运行目录和 detached receipt；稳定视频 QA、源码、文档与复现样例保留。

## 2026-08-12 对标增量

- `context_flow`、`failure_routes`、Skill 质量指标/版本回滚、知识来源治理已写入运行时契约和 UI。
- 评审负路径：缺失必需工具时 `DEFER → DEFER`；不补写证据、不沿用历史 PASS、不伪造修复。
- 生产交接：`approval_handoff.json` 固定 `production_system / external_authorization_required / blocked`。
- 对标审计见 `docs/GOAI_REVIEWER_FEEDBACK_AUDIT_20260812.md`；其中明确区分官方/导师口径、他队自评与本地工程证据。

# VisionData Gate｜复赛 60 秒 Demo 脚本

官方窗口：1 分钟。来源：[`GOAI_SEMIFINAL_GUIDE_20260902.md`](GOAI_SEMIFINAL_GUIDE_20260902.md)。

证据模式：`PUBLIC_SYNTHETIC_REPLAY`。公开页面无 Python 后端、无客户数据、无 API Key、无生产写操作；浏览器只有在 JCS SHA-256 一致后才显示案件事实。

本脚本只读取公开清单：`3 selected / maximum 5 / 2 rejected / 4 hypotheses / 4 external evidence gaps`。这组数字不得绑定到另一条 Goal3 持久交互回执（`5 selected / budget 5 / 3 rejected / Child CONTINUE_HOLD`）。公开清单只声明 `human gate=REQUIRED`、`public_snapshot_attestation=NOT_ISSUED`，不证明具名人工审批已经完成。

## 现场路径

提前打开六个标签页，不在计时开始后输入 URL：

1. `/`：公开首页；
2. `/command-center`：Agent 与工具；
3. `/cases/public-synthetic-conflict-01`：输入、结果与缺证；
4. `/capa`：Parent / Human Gate / Derived / Child；
5. `/runs`：异常处理与复验阶段；
6. `/governance`：权限和状态边界。

## 60 秒逐秒脚本

| 时间 | 页面与动作 | 口播 |
|---:|---|---|
| 00:00–00:06 | 首页停留，指向 `PUBLIC SYNTHETIC REPLAY` 与摘要 | “这是固定合成案件。浏览器先复算清单 SHA，再显示任何事实；无客户数据、无后端写入。” |
| 00:06–00:20 | 切到工作总览，指向预算、selected/rejected、触发证据 | “三条测点触发 3 个 Worker，预算上限 5；另外 2 个因没有触发证据被拒绝。工具测量，Agent 只决定下一步。” |
| 00:20–00:31 | 指向六阶段与竞争假设 | “案件经过 Intake、Planner、Tool、Council、Judge、Delivery；三条解释有证据支持，但生产工艺根因仍未建立。” |
| 00:31–00:41 | 切到案件页，指向 Parent/Child 和 missing evidence | “首轮是 RECAPTURE。Child 只得到本地合成复验结果；工厂真值、客户验收、生产 IAM 和设备授权仍缺失。” |
| 00:41–00:50 | 切到 CAPA/血缘页 | “这里显示的是人工闸门 REQUIRED，不是具名审批已完成。Child 独立复验，不覆盖 Parent。” |
| 00:50–00:56 | 切到 Runs，指向 `FAIL_CLOSED_THEN_RECHECKED` | “异常路径先失败关闭，再在同合同下复验；不是失败后自动放行。” |
| 00:56–01:00 | 切到治理页，停在状态 | “官网提交仍 PENDING，官方评测未发生，生产放行为 false。” |

## Demo 六段验收

| 官方要求 | 画面证据 |
|---|---|
| 用户输入 | 合成案件 ID、dataset、12 个注入问题范围 |
| Agent 处理 | 六阶段状态、Worker 预算与选择 |
| 工具或知识调用 | sharpness、dHash、annotation offset 的 triggering evidence |
| 结果交付 | Parent/Child disposition、缺失证据与 manifest |
| 异常处理 | `FAIL_CLOSED_THEN_RECHECKED` |
| 效果验证 | Child 同合同复验；同时保持 `production_release_allowed=false` |

## 现场失败切换

- 公网页面 3 秒内未打开：切本机已构建静态站点；
- 本机页面仍不可用：播放 `VisionDataGate_GOAI_Semifinal_60s_RC4_20260902.mp4`；
- 视频播放失败：按同一顺序展示六张已缓存截图并继续口播；
- 任何状态或摘要与脚本不一致：停止声称该事实，保留 `HOLD`，不要临场补数字。

## 禁止口播

- 不说客户 shadow、工厂部署或生产恢复已经完成；
- 不把 `PASS_LOCAL_SYNTHETIC_ONLY` 说成生产 PASS；
- 不把 DynamicBench 指标说成工厂误放行率、模型准确率或客户 ROI；
- 不说 Hosted AgentTeams、MES、OPC UA、PLC 或外部模型已经在线连接；
- 不说官网已经提交或官方评测通过。

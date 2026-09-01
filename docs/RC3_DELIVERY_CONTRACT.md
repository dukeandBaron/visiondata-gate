# VisionData Gate RC3 工程交付合同

状态日期：2026-08-31

## 产品边界

VisionData Gate RC3 是面向中小制造企业换型后视觉质量异常的证据驱动处置与方案复验 Agent。系统可以补证、形成竞争假设、建议具名责任动作并生成复验合同；系统不能建立最终根因、批准 CAPA、放行生产或控制设备。

RC3 的“经验演化”只发生在审批后的 Site Pack、历史记忆、调查提示和输出模板层，不训练或在线修改模型，不修改 Frozen Policy 和 Evidence Schema 核心语义。

## 五项冻结能力

| 能力 | 工程入口 | 当前可核验状态 |
|---|---|---|
| Factory Site Pack | `site_pack.py`、`examples/site_packs/` | 两套异构字段映射，同一核心代码，组件验收通过 |
| Governed Context Memory | `governed_context.py` | 站点/产品/产线/相机作用域；跨站点、过期、撤销和无关记忆拒绝 |
| Multimodal Case Advisor | `multimodal_advisor.py` | `off/gated/replay`；双重图像授权；未知引用整包拒绝；外部多模态模型远程调用未执行，与已完成的 Omni 真实图像只读接入相互独立 |
| Decision Packet + Action Contract | `incident_decision_packet.py` | JSON、HTML、CSV、ZIP；具名责任人、证据引用、未决风险和人工决定入口 |
| Approved Experience Loop | `approved_experience.py` | `CANDIDATE → REPLAY_TESTED → HUMAN_APPROVED → SHADOW → PROMOTED`；失败拒绝和晋升后回滚 |

记忆优先级固定为：

```text
Frozen Policy
> Current Verified Evidence
> Current Site Profile
> Approved Historical Experience
> Model Suggestion
```

历史经验始终标记为 `historical_reference_only=true`，且 `may_set_current_case_fact=false`。

## 产品 API

已有案件可通过以下接口取得面向责任人的结果交付：

```text
GET /v1/tasks/{task_id}/industrial-incidents/{case_id}/decision-packet
GET /v1/tasks/{task_id}/industrial-incidents/{case_id}/decision-packet.html
GET /v1/tasks/{task_id}/industrial-incidents/{case_id}/decision-packet/audit-bundle
```

审计 ZIP 固定包含：

```text
capa_action_list.json
decision_packet.html
decision_packet.json
evidence_request_list.csv
manifest.json
```

归档使用固定时间戳、固定文件顺序和未压缩存储，保证相同输入得到相同字节与 SHA-256。

## 多模态运行模式

配置模板位于 `.env.example`。默认值为：

```text
VISIONDATA_MULTIMODAL_ADVISOR_MODE=off
VISIONDATA_MULTIMODAL_ADVISOR_ENDPOINT=https://api.deepseek.com/chat/completions
VISIONDATA_MULTIMODAL_ADVISOR_ALLOWED_HOSTS=api.deepseek.com
VISIONDATA_MULTIMODAL_ADVISOR_ALLOW_REMOTE=false
VISIONDATA_MULTIMODAL_ADVISOR_ALLOW_IMAGE_TRANSMISSION=false
VISIONDATA_MULTIMODAL_ADVISOR_API_KEY=YOUR_API_KEY
```

用户提供的 OpenAI 兼容 Base URL 为 `https://api.deepseek.com`；运行时使用其显式 Chat Completions 端点。`gated` 只有在远程主机显式放行、全局图像传输开关为真、且每张图像均单独授权时才会发送请求。回执不保存 API Key、本地路径、原始图片、原始网络响应或隐藏推理。

## 数据与现场连接的独立状态

```text
REAL_IMAGE_DATA_INTEGRATION = VERIFIED_LOCAL_READ_ONLY
LIVE_FACTORY_SYSTEM_CONNECTION = NOT_CONNECTED
CUSTOMER_PRIVATE_PRODUCTION_DATA = NOT_CLAIMED
FACTORY_SITE_ACCEPTANCE = NOT_PERFORMED
```

已完成操作者授权的本地 Omni 真实工业异常图像只读接入：源画像为 4,464 张图像、1,439 个 masks，固定 180 张完成 RC3 Gate；`_05` 在产品私有派生版本中复制 180 张图像/60 个 masks，并完成独立 child Run。真实图像接入证据来自独立的 `_03/_05` Omni 运行；本次固定分母组件验收没有重新执行 Omni。

尚未连接的是客户工厂在线生产与控制系统，包括实时 OPC UA、VisionMaster SDK、MES/QMS/SCADA、PLC 和客户现场系统。Omni 不是客户私有生产数据；操作者授权声明不等于独立权属认证，原始图像不得进入 Git 或公开参赛包。

## 历史组件验收与当前发布门

2026-08-26 的固定分母组件验收曾处于 `PASS_COMPONENT_CONTRACTS /
BLOCKED_UNTIL_FULL_REGRESSION`。该历史回执与旧 SHA 不进入当前公开候选，以免把阶段门状态
冒充当前发布裁决；它也不能覆盖最终 Full。当前发布状态只读取
[PROJECT_STATUS.md](PROJECT_STATUS.md) 以及 detached namespace、匹配 clean checkout 与声明
toolchain 组成的完整本地验证集：
Full、双构包、clean-extract、Attestation、匹配 clean checkout 与 toolchain 全部对账通过时为
`PASS_LOCAL_RC3_RELEASE_CANDIDATE`，任一旁车漂移即退回 HOLD。

## 当前仍未完成或不得声称

- Full 与 clean-extract 已进入本地发布门，但没有第三方可信构建器、数字签名、可信时间戳或外部 clean-clone 回执；
- 尚未执行真实 DeepSeek 远程调用；
- 尚未连接工厂在线生产/控制系统，包括实时 OPC UA、VisionMaster SDK、MES/QMS/SCADA、PLC 或客户现场系统；
- Site Pack 是本地适配合同和 fixture，不是客户部署证明；
- 组件 PASS 不是复赛提交、生产验收、客户验收或获奖结果；
- 官网提交与官方评测仍为 `PENDING / NOT_EVALUATED`，本地候选不等于提交、生产验收、客户验收或获奖结果。

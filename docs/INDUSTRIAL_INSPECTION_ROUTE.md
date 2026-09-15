# VisionData Gate 工业质检与模型反馈路线

## 结论先说

VisionData Gate 适合讲成“工业视觉数据与质检证据的可信门禁”。评审后，
业务主线统一为三个阶段：**人机协同数据集冷启动 → Agent 编排的数据质量治理
→ 受控模型开发与反馈回流**。这三个阶段分别回答“数据从哪里来”“数据是否
满足当前用途”“模型怎样学习并把分歧安全送回”，不能压缩成一个自动识别
模型。

当前模型与证据后端必须分开：

1. **有界监督 BBox 检测后端**：现有 YOLO detect 外部运行时合同执行小预算
   训练和固定协议验证；
2. **Normality 开发代理**：现有 YOLO26n classification 多尺度特征重建实验
   输出 score、heatmap 和开发评估回执；
3. **多视角几何证据后端**：VGGT/OmniVGGT 合同输出相机、深度、轨迹和跨视角
   一致性指标，真实外部服务仍未连接；
4. **VLM 辅助预标注**：仅为规划项，当前没有成功调用或标注回执。

任何后端都不能绕过来源授权、数据合同、人工闸门、Child Run 和 Frozen Policy
Judge。模型输出是证据或候选标注，不是标签真值、根因或生产放行决定。

## 1. 推荐的全流程

```text
授权 RGB / 视频 / 可选深度
  → 人机协同数据集冷启动
       人工标注 + 可选预标注候选 + annotation revision 复核
  → 初始候选数据集版本
  → Data Quality Diagnoser
       解码 / 清晰度 / 曝光 / 重复 / 标注 / 覆盖 / metadata
  → [可选] BBox detector / Normality / 多视角几何证据
  → Remediation Planner + Named Human Gate
  → 派生副本整改
  → Independent Verification Gate（Parent / Child 同合同）
       ├─ 诊断缺证或定位错误 → DIAGNOSIS_REVISION
       ├─ 整改无效、持续项或回归 → REMEDIATION_REVISION
       └─ 必要条件满足 → 经治理的数据集候选版本
  → 冻结 train / val / test → 受控模型开发与独立评估
  → 分歧样本人工裁定 → 新采集或新标注版本进入下一轮
```

“全流程”在工程上指证据和整改能闭环，不等于已经完成客户现场验收。

## 2. 两条后端的分工

| 后端 | 解决的问题 | 必须输出的证据 | 当前状态 |
|---|---|---|---|
| YOLO detect 有界监督后端 | 对已有 BBox 标注执行任务特定检测训练，并生成固定 operating point 下的预测/参考分歧 | runtime/executable/weights/dataset SHA-256、训练预算、checkpoint、confidence/IoU、逐样本 FP/FN 候选 | `BOUNDED_LOCAL_RUNTIME`；CPU 小预算与合同已实现，非工厂效果 |
| YOLO26n Normality 开发代理 | 用正常样本学习多尺度特征重建，并生成异常 score/heatmap 开发证据 | source/model pack/backbone SHA-256、feature layers、阈值、三种子稳定性、开发指标 | `PUBLIC_DEVELOPMENT_ONLY`；不是监督 BBox、分割模型或生产 Gate |
| VLM 辅助预标注 | 为无现成任务模型的图像生成候选框、候选类别和说明 | provider/model/prompt/input/response 摘要、人工复核 revision | `PLANNED_NOT_CONNECTED`；没有真实成功回执 |
| VGGT/OmniVGGT 类 | 发现视角不足、深度异常、相机/轨迹不一致 | backend/version、checkpoint SHA-256、input batch SHA-256、RGB/深度尺寸、valid/outlier/confidence、reprojection、track visibility | `PASS_LOCAL_CONTRACTS_ONLY`（协议 2/2）/ `REAL_BACKEND_NOT_CONNECTED` / `MODEL_NOT_TESTED` |
| VisionData Gate Judge | 将多源证据转成发布门禁和整改工单 | ToolTrace、Finding、WorkOrder、RuleCheck、recheck、receipt | `LOCAL_PASS`（仅训练池合同范围） |
| Industrial Delivery | 将裁决转成责任、Skill、前置条件、验收标准、证据跨度和人工节点 | `industrial_delivery_receipt.json` | `PASS_LOCAL_TESTED`；RC3 `_03` 已生成真实只读 Omni 运行回执，`_05` 已完成私有派生版本与独立 child Run |

检测置信度、Normality 分数和几何误差是不同测量量，不能简单相加成一个
“总分”。三类模型证据应保留独立命名空间，最后由 Policy Judge 按 reason
code、用途合同和证据状态决策。

## 3. 先做什么、暂时不做什么

### P0：已经适合继续开发

- 保留人机协同标注为第一阶段；模型预测只作为只读候选层，人工确认后才创建
  新 annotation revision；
- 使用 `learning_yolo_backend.py` 的标准 BBox 检测合同和固定验证分歧协议，
  不把 FP/FN 自动判为标签错误；
- 使用 Normality 模型包的 score/heatmap 作为开发证据，不称为自动 Mask 真值；
- 使用 `geometry_consistency.py` 接收标准化 JSON，不安装 CUDA/VGGT/Anomalib；
- 使用 `geometry_backends.py` 探测 `/model-info`、调用 `/infer`，并核对 backend/version/checkpoint、输入 SHA-256 和图像数；该 HTTP 协议属于 VisionData Gate，不冒充上游原生 API；
- 为每次外部推理绑定 `input_batch_sha256`、backend version、可选 checkpoint 摘要；
- 对视图缺失、深度尺寸漂移、低有效率、重投影误差和轨迹可见性生成可执行 Finding；
- 通过 `run_geometry_gate` 回到原有 Council/Policy Judge，缺失可选后端写成 `OPTIONAL_BACKEND_NOT_CONNECTED`；
- 用计划性 Dynamic Leader 分支提示补拍、深度对齐、相机校准或输入对账，不自动改动源数据。

### P1：取得客户现场真值或外部模型回执后再做

- 定义真正的样本 query strategy，把模型不确定性、预测/标注分歧、覆盖缺口和
  多样性分项记录；当前 Worker Top-K 和记忆 Top-K 都不能替代该策略；
- 在同一人工标注时间预算下，对比随机抽样、置信度抽样和分歧+覆盖抽样；
- 选择一套固定的多视角采集协议（曝光、重叠率、视角数、相机标定）；
- 保存原图批次和几何 receipt 的字节哈希，验证一次重跑的确定性；
- 用独立 calibration split 设定阈值，报告 `NOT_MEASURED` 而不是填猜测值；
- 将几何 Finding 与现有工单回传、同合同复验结合，确认整改后误报是否下降。

### P2：没有现场授权不做

- 不宣称已经实现 VLM 自动标注、Active Learning、TTT、Multi-task Detection
  或自动 Mask 真值生成；
- 直接安装/下载大型权重到共享环境；
- 使用客户图像、生产系统或真实订单做未授权试验；
- 自动改写生产数据库、自动放行产品或宣称安全/法律认证；
- 把公开数据集 benchmark 结果写成学校项目的现场验收结果。

## 4. GOAI 复赛展示建议

GOAI 无界应用 · AI+工业制造重点看多源融合、流程闭环、解释性、可操作性和安全生产边界。推荐把演示重点放在：

1. 一批授权图像经人机协同复核形成初始候选数据集版本；
2. Data Quality Diagnoser 用只读工具指出证据缺口或数据质量问题；
3. Bounded Replanner 只选择有触发证据的 Worker，而不是无条件跑完整模型；
4. Remediation Planner 输出候选动作，具名人员批准后只在派生副本执行；
5. Independent Verification Gate 用 Parent/Child 同合同复验，并明确展示
   `DIAGNOSIS_REVISION`、`REMEDIATION_REVISION` 或继续 HOLD；
6. 经治理的数据候选进入有界模型开发，预测分歧回到人工裁定，不自动写回真值。

不需要把真人露脸或大型模型安装过程放进视频；屏幕演示加中文旁白即可。若要展示真实模型，应在画面上明确标注“外部模型回执已接入/未接入”和“工业验收尚未声明”。

## 5. 量化验收表（先定义分母）

| 指标 | 分母 | 当前能否填写 |
|---|---|---|
| 几何 receipt 完整率 | 实际提交的 view records | 可在本地计算 |
| 输入哈希一致率 | 有效 geometry runs | 可在本地计算 |
| 视图覆盖率 | manifest 视图数 | 可在本地计算 |
| 深度对齐失败率 | 有深度指标的 views | 可在本地计算 |
| 几何后端协议连接率 | 冻结的 VGGT/OmniVGGT connector fixtures（2） | `2/2 PASS_LOCAL_CONTRACTS_ONLY`，不计作真实模型连接 |
| BBox 检测效果 | 独立冻结且人工裁定的 test split | 本地训练合同已实现；没有工厂真值，保持 `NOT_EVALUATED` |
| Normality 公共开发代理 | VisA capsules 冻结开发协议 | 可报告 README 中已绑定的 AUROC/FPR/F1；不得写成工厂效果 |
| VLM 预标注质量 | 独立人工复核的候选框/类别分母 | `NOT_MEASURED / PLANNED_NOT_CONNECTED` |
| 自动 Mask 质量 | 独立人工像素级真值 | `NOT_IMPLEMENTED`；heatmap 不计作 Mask 真值 |
| 生产误放行率 | 经授权的现场产品真值 | `NOT_MEASURED`，不能用 demo 代替 |
| 官方参展/平台结果 | 官方回执 | `OFFICIAL_SUBMISSION_PENDING` |

## 6. 证据边界

- `PASS_LOCAL`：只证明本地标准化 receipt、Finding、Policy Judge 和文件哈希链路通过；
- `PASS_LOCAL_CONTRACTS_ONLY`：只证明 VisionData Gate 自有 connector 协议夹具通过；当前 VGGT/OmniVGGT 为 2/2；
- `NOT_TESTED`：没有模型输出或没有独立 calibration/test；
- `OPTIONAL_BACKEND_NOT_CONNECTED`：主链可运行，但可选后端没有连接；
- `REAL_BACKEND_NOT_CONNECTED`：显式外部连接身份层没有真实服务/权重运行回执；不能由本机协议夹具升级；
- `PRODUCTION_ACCEPTANCE_NOT_CLAIMED`：没有现场授权和生产回执；
- `OFFICIAL_SUBMISSION_PENDING`：学校/主办方的正式提交和结果仍需人工完成。

这些标签应原样保留在开发报告、GOAI 复赛包和视频口径中，避免把工程实现误写成模型效果或官方结果。

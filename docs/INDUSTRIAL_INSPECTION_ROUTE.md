# VisionGate 工业质检路线（开发分支）

## 结论先说

VisionData Gate 适合讲成“工业视觉数据与质检证据的可信门禁”，当前最稳的优化是把产品质检拆成两个可插拔证据后端：

1. **异常证据后端**：PatchCore/Anomalib/Omni-AD 等输出图像级分数、像素图和阈值回执；
2. **几何证据后端**：VGGT/OmniVGGT 输出相机、深度、点图、轨迹及跨视角一致性指标。

两者都不能绕过原有的合同、证据、工单、复验和 Policy Judge。当前已实现第二条的标准化几何适配器及 VGGT/OmniVGGT HTTP 连接合同；两个本机协议夹具已通过，但真实模型服务仍未连接。异常后端仍是规划项。

## 1. 推荐的全流程

```text
采集 RGB / 视频 / 可选深度
  → 图像合同（解码、尺寸、曝光、清晰度）
  → 数据治理（重复、标注、覆盖、元数据）
  → [可选] 异常检测分支
       score + pixel map + threshold/calibration receipt
  → [可选] 多视角几何分支
       camera + depth + track + reprojection receipt
  → 证据绑定（原图/manifest/模型/权重 SHA-256）
  → Dynamic Leader 选择补证任务
  → Frozen Policy Judge
  → RECAPTURE / RELABEL / REMOVE_OR_REPARTITION / INVESTIGATE
  → 保留副本整改 → 同合同复验 → Evidence Package
```

“全流程”在工程上指证据和整改能闭环，不等于已经完成客户现场验收。

## 2. 两条后端的分工

| 后端 | 解决的问题 | 必须输出的证据 | 当前状态 |
|---|---|---|---|
| Anomalib/PatchCore/Omni-AD 类 | 发现外观、纹理、局部缺陷候选 | model/version、weights SHA-256、image score、pixel map 摘要、阈值、校准分割、每样本结果 | `PLANNED / NOT_CONNECTED` |
| VGGT/OmniVGGT 类 | 发现视角不足、深度异常、相机/轨迹不一致 | backend/version、checkpoint SHA-256、input batch SHA-256、RGB/深度尺寸、valid/outlier/confidence、reprojection、track visibility | `PASS_LOCAL_CONTRACTS_ONLY`（协议 2/2）/ `REAL_BACKEND_NOT_CONNECTED` / `MODEL_NOT_TESTED` |
| VisionData Gate Judge | 将多源证据转成发布门禁和整改工单 | ToolTrace、Finding、WorkOrder、RuleCheck、recheck、receipt | `LOCAL_PASS`（仅训练池合同范围） |
| Industrial Delivery | 将裁决转成责任、Skill、前置条件、验收标准、证据跨度和人工节点 | `industrial_delivery_receipt.json` | `PASS_LOCAL_TESTED`；RC3 `_03` 已生成真实只读 Omni 运行回执，`_05` 已完成私有派生版本与独立 child Run |

异常分数和几何误差是不同测量量，不能简单相加成一个“总分”。建议保留两个证据命名空间，最后由 Policy Judge 按 reason code 和证据状态决策。

## 3. 先做什么、暂时不做什么

### P0：已经适合继续开发

- 使用 `geometry_consistency.py` 接收标准化 JSON，不安装 CUDA/VGGT/Anomalib；
- 使用 `geometry_backends.py` 探测 `/model-info`、调用 `/infer`，并核对 backend/version/checkpoint、输入 SHA-256 和图像数；该 HTTP 协议属于 VisionData Gate，不冒充上游原生 API；
- 为每次外部推理绑定 `input_batch_sha256`、backend version、可选 checkpoint 摘要；
- 对视图缺失、深度尺寸漂移、低有效率、重投影误差和轨迹可见性生成可执行 Finding；
- 通过 `run_geometry_gate` 回到原有 Council/Policy Judge，缺失可选后端写成 `OPTIONAL_BACKEND_NOT_CONNECTED`；
- 用计划性 Dynamic Leader 分支提示补拍、深度对齐、相机校准或输入对账，不自动改动源数据。

### P1：取得客户现场真值或外部模型回执后再做

- 选择一套固定的多视角采集协议（曝光、重叠率、视角数、相机标定）；
- 保存原图批次和几何 receipt 的字节哈希，验证一次重跑的确定性；
- 用独立 calibration split 设定阈值，报告 `NOT_MEASURED` 而不是填猜测值；
- 将几何 Finding 与现有工单回传、同合同复验结合，确认整改后误报是否下降。

### P2：没有现场授权不做

- 直接安装/下载大型权重到共享环境；
- 使用客户图像、生产系统或真实订单做未授权试验；
- 自动改写生产数据库、自动放行产品或宣称安全/法律认证；
- 把公开数据集 benchmark 结果写成学校项目的现场验收结果。

## 4. GOAI 复赛展示建议

此前 20 页手册的 AI+工业制造分类重点关注多源融合、流程闭环、解释性、可操作性和安全生产边界；2026-09-02 最新复赛排期将第 03 队列为 `AI+其他`，工业视觉 / 制造业只作为本项目应用领域。推荐把演示重点放在：

1. 一批多视角工业图像进入 VisionGate；
2. 几何 evidence adapter 发现“深度未对齐/重投影误差高/视角缺失”；
3. Leader 生成针对性的补证计划，而不是无条件跑完整模型；
4. Policy Judge 输出 `RECAPTURE` 或 `DEFER`，并留下可核验 SHA-256；
5. 在保留副本修复后，用同一合同复验，展示证据闭环。

不需要把真人露脸或大型模型安装过程放进视频；屏幕演示加中文旁白即可。若要展示真实模型，应在画面上明确标注“外部模型回执已接入/未接入”和“工业验收尚未声明”。

## 5. 量化验收表（先定义分母）

| 指标 | 分母 | 当前能否填写 |
|---|---|---|
| 几何 receipt 完整率 | 实际提交的 view records | 可在本地计算 |
| 输入哈希一致率 | 有效 geometry runs | 可在本地计算 |
| 视图覆盖率 | manifest 视图数 | 可在本地计算 |
| 深度对齐失败率 | 有深度指标的 views | 可在本地计算 |
| 几何后端协议连接率 | 冻结的 VGGT/OmniVGGT connector fixtures（2） | `2/2 PASS_LOCAL_CONTRACTS_ONLY`，不计作真实模型连接 |
| 异常召回率/误报率 | 固定、独立的 defect truth split | `NOT_MEASURED`，未接入异常后端 |
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

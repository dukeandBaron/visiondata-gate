# 行业场景价值｜GOAI 25% 证据合同

更新时间：2026-08-30

本文件只回答三个问题：问题是否真实且具有代表性、谁会使用以及价值如何测量、能力是否可以迁移。它不是官方评分，也不把本地运行、公开论文或合成基准升级为客户验收。

## 1. 当前裁决

```text
INDUSTRY_PROBLEM_DEFINITION       = PASS_LOCAL
PROBLEM_CLASS_REPRESENTATIVENESS  = PASS_EXTERNAL_SOURCES_BOUNDED
AUTHORIZED_PRIVATE_PILOT          = PASS_LOCAL_BOUNDED
TARGET_USER_AND_WORKFLOW          = PASS_LOCAL
CUSTOMER_VALUE_METRICS            = PARTIAL_MEASUREMENT
CUSTOMER_SHADOW_VALIDATION        = HOLD_PENDING_ADJUDICATION
LOCAL_PORTABILITY_CONTRACTS       = PASS_LOCAL
EXTERNAL_REPLICATION              = HOLD
PRODUCTION_RELEASE_ALLOWED        = false
```

公开标准、官方数据集与同行评审研究足以证明：采集条件、训练数据质量、标签噪声、跨划分泄漏、数据漂移、验收指标和血缘追溯都是机器视觉与机器学习系统中的真实问题类别。它们不能证明这些问题在某一客户现场的发生频率、损失金额或 VisionData Gate 已带来的 ROI。

项目当前最准确的产品定义是：

> VisionData Gate 是工业视觉训练与验证数据进入实验池或发布流程前的证据门禁。它在换型、相机/光源变化、标注更新或数据版本变化后，把图像、标注、划分、metadata、工艺与视觉方案组织为一个可追溯案件，并完成 Gate → CAPA → 私有派生版本 → Child Run 复验。它不是缺陷检测模型本身，也不替代质量负责人作最终生产决定。

## 2. Q1｜问题是否真实、明确且具有代表性

### 2.1 真实任务边界

```text
触发事件
  产品换型 / 相机或光源变化 / 标注更新 / 数据版本变化 / NG 异常调查

受控对象
  工业视觉训练、验证或发布候选数据批次

核心风险
  采集质量不合格 / Train-Val-Test 泄漏 / 标签或几何错误 /
  覆盖缺口 / metadata 与工艺证据冲突 / 整改后未经独立复验

交付物
  GateResult / ToolTrace / 风险处置流 / CAPA 方案 /
  私有派生版本 / Child Run / 责任队列 / 审计封套
```

### 2.2 外部问题证据与项目映射

| 问题类别 | 外部权威依据 | 本项目对应能力 | 可以声明 | 不得外推 |
|---|---|---|---|---|
| 机器视觉项目受现场影响因素约束 | VDI/VDE/VDMA 2632 Blatt 2 要求在机器视觉需求与系统规格中描述影响因素及其效果 | Batch Contract、Site Pack、Source Profile、Rule Pack | 项目围绕机器视觉影响变量建立显式合同 | 已通过 VDI 验收、影响因素在客户现场的发生率 |
| 分类性能需要量化验收 | VDI/VDE/VDMA 2632 Blatt 3.1 描述分类能力指标与验收方法 | 案件级误放行、误拦截、固定分母和独立真值协议 | 项目具备量化验收所需的评测合同 | 数据门禁等于视觉分类器验收、已符合该标准 |
| ML 数据质量需要模型、度量与报告 | ISO/IEC 5259-2:2024 规定 analytics/ML 数据质量模型、度量及报告指南 | 五类确定性工具、Governance Effectiveness v2、Evidence Package | 数据质量门禁是标准化治理问题 | 项目获得 ISO 认证或阈值天然适用于所有工厂 |
| 训练数据质量、代表性与漂移必须持续测量 | NIST AI RMF Playbook Measure 要求记录不可测风险、监控训练数据等外部输入、评估漂移与外部有效性 | `NOT_MEASURED` 状态、来源/合同漂移阻断、Shadow Evaluation、Child Run | 缺真值时保持未测量是正确治理行为 | NIST 为项目背书、项目已具备客户效果 |
| 相机与传感器性能需要客观测量 | EMVA 1288 是机器视觉传感器和相机规格测量与呈现标准 | 清晰度、曝光、分辨率、解码与 metadata 检查 | 工业采集质量应由测量而非语言模型猜测 | 项目方法已获 EMVA 合规认证、Laplacian 阈值是通用标准 |
| 工业视觉存在未覆盖照明与现实域变化 | MVTec AD 2 含 8 个工业场景、8,000+ 高分辨率图像，测试包含训练集中未必覆盖的照明条件；Real-IAD 含 150K 图像、30 类对象与多视角拍摄 | 光照/清晰度门禁、来源画像、物理样本/视角/相机/批次覆盖审计 | 工业视觉数据存在照明、视角和场景覆盖挑战 | 项目在这些数据集上的模型成绩或客户效果 |
| 真实训练数据可能含噪声 | NeurIPS 2022 SoftPatch 明确指出“干净训练数据”是理想假设，现实异常检测中的噪声不可避免 | 重复泄漏、标注、覆盖和异常候选治理 | 训练数据污染值得在模型训练前治理 | 论文中的效果数字等于本项目效果 |
| 标签错误和边界错误会影响评测 | NeurIPS Datasets and Benchmarks 2021、JAIR 2021 研究测试集标签错误与标签质量 | 缺标注、错误尺寸、BBox/Mask 几何一致性、人工复核 | 标签质量是独立于模型架构的治理对象 | 公共数据集错误率等于工业数据错误率 |
| Train/Test 泄漏会造成过度乐观估计 | scikit-learn 官方文档及 Kapoor & Narayanan 2023 说明数据泄漏会产生过度乐观评估并削弱新数据/生产表现 | dHash/MAE 近重复与跨 split 泄漏检查 | 跨划分泄漏应在训练前拦截 | CIFAR 或科研案例中的泄漏率等于客户泄漏率 |
| 血缘可用于判断质量与可信度 | W3C PROV-DM 将 entity、activity、agent 及 derivation 组织为可扩展的 provenance 模型 | Parent/Child Case、派生版本、具名批准、lineage 和审计封套 | 项目采用实体—活动—责任—派生的血缘思路 | 已通过 W3C 一致性认证 |

### 2.3 当前项目证据

| 证据轨 | 当前事实 | 只回答什么 |
|---|---|---|
| Synthetic-v3 | 12 个冻结注入问题 | 工具、Gate、整改和同合同复验能否闭环 |
| DynamicBench-v3 | 当前文件 SHA-256 `424be5fc8f51d55bf412b6e73c88a4943bc2d403b1e2d85817b7eb7de9e36d21`；8 个冻结合成夹具 | 冲突、故障、不确定性和正常输入上的编排差异；不回答工厂效果 |
| 授权 Omni 私域 Pilot | 本地离线只读 Source Profile 与固定 180 Gate、CAPA 和 Child Run | 产品链能否处理真实字节并正确失败关闭；不回答客户验收 |
| Omni Governance v2 | 文件 SHA-256 `d4f4ca6bcdfc4e130ca165846fae7f0446c37869ddb2e4eb63e9ec44e4563a3a`；内部域分离 Report SHA-256 `28aad63b274e657178938442c8e12e39992da742a39d3b757c05619715d1a542` | 当前私域评测分子、分母、状态和声明边界 |

两种 SHA 的语义不同：文件 SHA 绑定保存字节；Report SHA 绑定 JCS 规范化后的报告语义。二者不能互相替代。

## 3. Q2｜目标用户、痛点、现实需求和价值收益

### 3.1 目标用户与待办任务

| 角色 | 当前工作中的摩擦 | VisionData Gate 交付 | 最终权限 |
|---|---|---|---|
| 工业视觉算法工程师 | 多个脚本输出分散，难以判断某一版本是否可以进入训练或验证 | 单一案件、工具证据、Gate 决定、可复算 Evidence Package | 处理技术整改，不拥有生产放行权 |
| 质量负责人 | 数据风险、模型风险与现场责任难以对齐，整改后缺少独立复验 | 风险处置流、候选 CAPA、具名批准、责任队列和 Child Run | 确立现场质量决定与批准阈值 |
| 数据/标注负责人 | 样本、标注、划分和工单无法一一回溯 | 原子 finding、evidence span、修订建议与复验状态 | 执行授权的数据与标注整改 |
| MLOps/平台负责人 | 数据版本、规则版本和运行证据分离，旧结果容易被误复用 | API、Site/Rule/Adapter 合同、版本与 SHA 绑定 | 管理集成、身份和部署边界 |

### 3.2 价值不是一个虚构 ROI，而是四组可测结果

| 价值维度 | 冻结指标 | 当前状态 | 需要的外部证据 |
|---|---|---|---|
| 决策安全 | `false_release_rate` | `NOT_MEASURED_PENDING_ADJUDICATION`，`0/0` | `BLOCK_REQUIRED` 案件的独立 QMS/双人真值 |
| 决策负担 | `false_block_rate` 与建议新增的 `human_review_rate` | `false_block_rate=NOT_MEASURED_PENDING_ADJUDICATION` | `RELEASE_ALLOWED` 案件的独立真值，并把转人工与纯误拦截分开 |
| 整改闭环 | `verified_remediation_pass_rate` | `0/1`，Wilson 95% `[0, 0.7934506856]` | 更多独立同合同 Child Run |
| 真值覆盖 | `adjudication_coverage_rate` | `0/1 = 0%` | 所有纳入 shadow 的案件完成外部裁决 |
| 取证速度 | `evidence_lead_time_seconds` | `NOT_IMPLEMENTED / NOT_MEASURED` | `evidence_intake_admitted_at` 与 `decision_packet_sealed_at` 可信事件 |
| 人工负担 | `manual_review_time_seconds` | `NOT_IMPLEMENTED / NOT_MEASURED` | 具名 reviewer 的 start/pause/resume/submit 活跃区间 |
| 返工次数 | `rework_count` | `OBSERVED_ONLY = 1 approved CAPA cycle` | 预注册观察窗内所有成功、失败和未决整改循环 |
| 经济收益 | ROI / avoided loss | `NOT_ESTIMABLE` | 客户签署的历史基线、单位工时、错误放行损失与整改成本 |

`0/1` 不是“系统通过率为 0%”的总体结论，只表示当前唯一完成的同合同复验没有达到 Gate PASS；样本量和区间必须一起展示。

### 3.3 建议冻结的运营指标定义

```text
evidence_lead_time_seconds
= decision_packet_sealed_at - evidence_intake_admitted_at

manual_review_time_seconds
= sum(authenticated active review intervals)

rework_count
= number of uniquely approved CAPA cycles per Parent Case
  before closure or the preregistered observation-window cutoff
```

不得用单次工具 `latency_ms` 冒充取证周期，不得用页面停留时间冒充人工工时，也不得只统计成功的整改循环。

### 3.4 ROI 只能由客户基线计算

```text
annual_avoided_false_release_loss
= (baseline_false_release_rate - shadow_false_release_rate)
  * eligible_case_count
  * customer_signed_loss_per_false_release

annual_review_labor_delta
= (baseline_manual_review_seconds - shadow_manual_review_seconds)
  * eligible_case_count
  * customer_signed_loaded_labor_rate

net_value
= avoided_loss + labor_delta - integration_cost - operating_cost - remediation_cost
```

任何一项基线或成本未经客户责任人签署时，ROI 必须保持 `NOT_ESTIMABLE`。

## 4. Q3｜复制、迁移与推广潜力

### 4.1 应保持稳定与必须现场配置的部分

| 稳定内核 | 现场变量 |
|---|---|
| Tool/Observation Contract | 相机、产线、工位、产品族与采集条件 |
| Frozen Policy Judge 与 fail-closed precedence | 现场阈值、容忍区间与责任人 |
| Evidence/Lineage/Audit Envelope | 数据来源、格式映射、QMS/MES/CVAT 身份 |
| Parent → Derived Version → Child Run | 审批流程、IAM 与保留期限 |
| 案件级治理评测协议 | 客户真值、业务基线和验收阈值 |

### 4.2 当前迁移能力的真实状态

| 能力 | 当前状态 | 可声明边界 |
|---|---|---|
| Site Pack | `INTEGRATED_LOCAL` | 两个本地 fixture 证明现场参数可分离；不是两个真实工厂 |
| Rule Pack | `INTEGRATED_LOCAL` | 可冻结规则和动态触发；不是工厂阈值认证 |
| Adapter SDK | `OFFLINE_CONFORMANCE_ONLY` | 可校验 manifest/observation/只读边界；尚未执行任意第三方 entrypoint |
| Industrial Skill | `BUILTIN_INTEGRATED_LOCAL` | 内置 Metadata Skill 已由固定 Worker 证据触发；没有任意插件自动发现或 OS 沙箱 |
| BYOD | `OMNI_AND_OPERATOR_SNAPSHOT_ONLY` | 当前授权产品入口不是通用任意数据源接入 |
| BYOM/BYOK | `LOCAL_BYOK_READY` | 可配置兼容网关；无客户运行、生产 IAM 或 SLA |
| CVAT/FiftyOne | `LOCAL_ROUNDTRIP_CONTRACT` | 本地导入、导出与复验合同；真实服务仍未连接 |
| REST API | `INTEGRATED_LOCAL` | 单机产品 API；不是公网多租户 SaaS |
| JSON Schema | `PUBLISHED_LOCAL` | 本地文件和测试存在；第三方 clean-clone 复现仍待完成 |

CVAT 官方文档证明 COCO、CVAT、Datumaro、LabelMe、PASCAL VOC、YOLO/Ultralytics 等格式属于现有标注生态；它不证明 VisionData Gate 已原生支持每一种格式。项目只能按已执行的 Adapter 或 roundtrip 回执逐项声明。

### 4.3 迁移验收梯度

```text
L0  Frozen Fixture
    本地合成合同、失败路径和确定性重放

L1  Authorized Offline Pilot               <- 当前最强真实边界
    授权离线字节、只读来源、固定分母、CAPA/Child Run

L2  Independent Two-Environment Clean Run
    相同内核版本 + 两个独立 Site Pack + clean clone + 相同验收脚本

L3  Customer Shadow Validation
    连续或预注册抽样 + 独立双人/QMS真值 + 现场 KPI + 责任人签署

L4  Governed Production Integration
    企业 IAM、SLO、回滚、现场安全审查与最终生产批准
```

当前可以声明 L1；L2 只有合同和本地 fixture，不能写成外部复现；L3–L4 保持 `HOLD`。

## 5. 客户 Shadow Test 的最小验收协议

1. 书面确认数据权利、用途、驻留、保留期限和公开边界。
2. 预注册观察窗、案件粒度、站点/产线/工位、产品族、规则包、合同版本和纳入/排除规则。
3. 使用连续批次或预先定义的分层随机样本，不能看到 Agent 结果后挑选案例。
4. Agent 先独立运行并封存 Decision Receipt；真值不得进入 Planner、Worker 或 Judge。
5. 两位复核人独立盲审，给出 `BLOCK_REQUIRED` 或 `RELEASE_ALLOWED`；分歧由第三位质量责任人或既有 QMS disposition 仲裁。
6. 每个案件绑定 Input Contract SHA、Manifest SHA、Gate Receipt SHA、两份复核标签、仲裁回执和最终 Truth Receipt SHA。
7. Fixed 与 Dynamic 必须使用相同案件、工具、预算、规则包和真值，按案件配对比较。
8. 分站点、产品族、规则包、合同版本和观察窗报告，Synthetic、公开代理和私域客户指标不得池化。
9. 比例同时展示分子、分母和 95% 区间；时间与返工展示 p50、IQR、p95。
10. 阈值由客户质量负责人预先批准；未过阈值时保持 `PARTIAL_MEASUREMENT`，不得改写为上线成功。

若近似独立且观察到零错误，双侧 Wilson 95% 上界低于 5%、2%、1% 分别至少需要 73、189、381 个对应真值类别案件。误放行与误拦截的分母必须分别满足；同一批次内相关性会进一步增加所需样本。

## 6. 评委展示口径

### 30 秒行业价值陈述

> 工业视觉团队在换型后通常面对的不是一个模型问题，而是一组相互关联的数据风险：采集条件变化、跨划分重复、标注错误、覆盖缺口和 metadata 冲突。VisionData Gate 把这些风险放进同一个版本化案件，先由确定性工具测量，再由 Agent 只在证据改变下一步时补证，最后通过具名 CAPA、私有派生版本和 Child Run 独立复验完成闭环。当前我们已完成本地授权离线 Pilot；客户误放行、误拦截和 ROI 仍等待独立 shadow 真值，不提前宣称。

### 90 秒证明顺序

```text
真实异常图与 metadata
→ 五类确定性测量
→ 跨工具冲突 / 工具故障触发补证
→ Gate 失败关闭
→ 三类风险流与 CAPA 方案
→ 具名批准和私有派生版本
→ Child Run 仍失败并转调查
→ 指标卡显示 NOT_MEASURED / 0 of 1 / production_release=false
```

失败的 Child Run 是行业价值证据的一部分：它证明系统不会把 finding 减少自动美化为生产恢复。

## 7. 声明白名单与红线

允许：

- “公开标准和同行评审研究证明本项目处理的问题类别真实且具有代表性。”
- “已在操作者声明授权的本地离线工业数据副本上完成有边界的产品 Pilot。”
- “误放行、误拦截和整改通过率的逐案件评测合同已经实现；缺真值时保持未测量。”
- “Site/Rule/Adapter/Skill/API 提供本地迁移合同，外部复制仍需 clean-run 回执。”

禁止：

- “已被工厂采用”“已经客户验收”“已减少数万元损失”。
- “Omni/Synthetic/DynamicBench 的结果等于真实工厂准确率。”
- “finding 下降等于整改成功、根因成立或生产恢复。”
- “CVAT、FiftyOne、MLflow、DVC、GenICam、MES 或 QMS 已连接”，除非存在对应身份、探测和运行回执。
- “符合 ISO、VDI、EMVA 或 W3C 标准”，除非完成对应的一致性/认证程序。

## 8. 外部来源

以下页面于 2026-08-30 核验；仅使用其明确陈述，不使用营销性 ROI 数字。

1. [ISO/IEC 5259-2:2024｜IEC Webstore](https://webstore.iec.ch/en/publication/103155)
2. [NIST AI RMF Playbook｜Measure](https://airc.nist.gov/AI_RMF_Knowledge_Base/Playbook/Measure)
3. [VDI/VDE/VDMA 2632 Blatt 2｜Requirement and system specification](https://www.vdi.de/en/home/vdi-standards/details/vdivdevdma-2632-blatt-2-machine-vision-preparation-of-a-requirement-specification-and-a-system-specification)
4. [VDI/VDE/VDMA 2632 Blatt 3.1｜Classification performance acceptance](https://www.vdi.de/en/home/vdi-standards/details/vdivdevdma-2632-blatt-31-machine-visionindustrial-image-processing-acceptance-test-of-classifying-machine-vision-systems-test-of-classification-performance)
5. [EMVA 1288｜Machine vision sensors and cameras](https://www.emva.org/standards-technology/emva-1288/)
6. [MVTec AD 2｜Advanced industrial anomaly detection dataset](https://www.mvtec.com/company/research/datasets/mvtec-ad-2)
7. [Real-IAD｜CVPR 2024 Open Access](https://openaccess.thecvf.com/content/CVPR2024/html/Wang_Real-IAD_A_Real-World_Multi-View_Dataset_for_Benchmarking_Versatile_Industrial_Anomaly_CVPR_2024_paper.html)
8. [SoftPatch｜NeurIPS 2022](https://proceedings.neurips.cc/paper_files/paper/2022/hash/637a456d89289769ac1ab29617ef7213-Abstract-Conference.html)
9. [Pervasive Label Errors in Test Sets｜NeurIPS Datasets and Benchmarks 2021](https://datasets-benchmarks-proceedings.neurips.cc/paper_files/paper/2021/hash/f2217062e9a397a1dca429e7d70bc6ca-Abstract-round1.html)
10. [Confident Learning｜JAIR 2021](https://jair.org/index.php/jair/article/view/12125)
11. [scikit-learn｜Data leakage](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage)
12. [Leakage and the reproducibility crisis｜Patterns 2023](https://doi.org/10.1016/j.patter.2023.100804)
13. [W3C PROV-DM](https://www.w3.org/TR/prov-dm/)
14. [CVAT｜Dataset formats](https://docs.cvat.ai/docs/dataset_management/formats/)

## 9. 内部评分预估

为便于排优先级，采用项目内部工作拆分 `Q1 9 分 + Q2 8 分 + Q3 8 分`；这不是官方子项权重或排名预测。

| 子项 | 当前内部就绪度 | 主要扣分原因 |
|---|---:|---|
| Q1 问题真实、明确、代表性 | 7–8 / 9 | 外部问题类别成立，但客户发生频率、损失与现场样本仍未测量 |
| Q2 用户、痛点、需求、收益 | 5–6 / 8 | 角色和流程清楚，治理指标协议已实现；人工工时、取证周期、返工和 ROI 未闭合 |
| Q3 复制、迁移、推广 | 5 / 8 | 本地合同强；第三方 Adapter 执行、双环境 clean-run 与客户复制回执缺失 |
| 合计 | **17–19 / 25** | `PARTIAL_STRONG`，不是官方得分 |

提升这部分分数的最短路径不是再堆 Agent 概念，而是完成一轮预注册客户 shadow、补齐三项运营埋点，并让相同内核在两个独立环境用不同 Site Pack 完成 clean-run。

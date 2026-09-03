# VisionData Gate｜Evidence & Benchmarks

不同实验 namespace 使用不同输入、分母和结论，不能合并成一个总准确率。

| Namespace | 固定输入 / 分母 | 已观察结果 | 只能证明 |
|---|---:|---|---|
| Synthetic-v3 | 12 个注入真值问题 | 初始 `RECAPTURE`，修复后 `PASS`，F1 1.00 | 合成工程闭环；不是工厂效果 |
| ArchBench-v2 | 3 架构 × 96 = 288 records | 固定 SOP 下三架构质量持平 | 固定 SOP 下多 Agent 必要性未被支持 |
| Omni-180-v1 / RC2 | 本地离线副本中 180 张冻结样本 | 45 findings / 45 工单，1 次 replan，3 个 Workers，`RECAPTURE` | 冻结脱敏证据快照；不证明原图可再分发，不能替代 RC3 |
| DynamicBench-v1 | 4 架构 × 24 fixtures × 3 repeats = 288 | Dynamic P/R 1.0/1.0；比固定多 Agent少 57 次无效补证；质量与单 Agent 持平且本机 P95 更慢 | 确定性触发语义；实际模型调用为 0 |
| DynamicBench-v2 | 24 优先级 fixtures × 4 输入顺序 × 3 repeats = 288 | 288/288 选择符合冻结字典序；24/24 输入顺序不变；24/24 重复回执稳定 | 确定性 Worker 排序语义；不是 Active Sensing 校准、工业准确率或端到端性能 |
| DynamicBench-v3 | 8 个冻结冲突/故障/不确定性/正常夹具 | Dynamic 终态正确 `8/8`，Fixed `4/8`；调用 `14 vs 24`；故障恢复 `2/2 vs 0/2` | 合成编排差异；不是工业效果 |
| IndustrialIncidentBench v1 | 12 个固定本地 fixture 场景 | 人工闸门、陌生/对抗输入、Worker 失败、预算耗尽、授权撤销、CAPA/Child Run 均失败关闭；外部模型调用 0 | Incident 合同与闭环安全性；不是工厂效果、客户验收或生产 SLO |
| Omni RC3 `_03` | 4,464 图像 / 1,439 masks 只读 profile；固定 180 Gate | 48→49 findings，5→8 ToolTrace，3 风险流，3 方案，`RECAPTURE` | 当前本地授权运行；不是 4,464 张全量认证 |
| Omni RC3 `_05` | 49/49 方案；派生 180 图像 / 60 masks；独立 Child Run | 49→33 findings；6 关闭 / 43 打开；`TRANSFERRED_TO_INVESTIGATION` | 整改与复验已执行；不是恢复成功 |
| CAPA assessment `_06` | 三套冻结方案 + `_05` 唯一实跑结果 | 当前授权候选池未观察到可发布方案；最小成本 `NOT_ESTIMABLE` | 未执行方案没有成功率、金额或 ROI |
| VisA 公开工业代理 RC5 正式复验 | 300 clean + 300 programmatic block = 600 episodes | Dynamic / Fixed 正确终态均 `525/600`；unsafe release 均为 `0`；瞬时恢复均 `150/150`；调用 `2,550 vs 2,700`；不可恢复故障冗余重试 `0 vs 150` | 2026-09-03 RC5 当前环境 `PASS`；只证明程序化治理真值下的合同感知效率，不证明 Worker replanning、工厂指标、自然缺陷精度、真实故障分布或客户 ROI |

## 关键负结论

ArchBench-v2 没有证明“多 Agent 普遍更强”。在固定 SOP 下，传统流水线、单 Agent 与多 Agent 的质量相同。项目因此只在中间证据确实改变下一步任务时启用动态 Worker。

Omni RC3 `_05` 也没有证明生产恢复。Findings 减少 16，但只有 6 条责任项满足关闭条件，43 条仍然打开，因此继续 HOLD 并转人工调查。

VisA RC5 的 Dynamic 与 Fixed 正确终态同为 `525/600`，因此没有“动态策略更准确”的结论；可支持的差异只是 Dynamic 在相同终态质量和 unsafe release 为 0 的前提下少做 150 次不可恢复故障冗余重试。report semantic SHA-256 为 `1e332d3852100c00db60ed739fa5219b198c6e608ecb3e3a977c8aa9dc5cfa2c`，implementation receipt semantic SHA-256 为 `7966b61b18bafd7a17f23427e6b50bd0ee30849ab7e60343dcc54b9a408896bf`；原始 VisA 字节与本机报告路径不公开。

## Governed Audit Envelope

普通 checksum 只回答文件有没有变化。Governed Audit Envelope 进一步把以下材料纳入规范化摘要：

```text
JCS canonical payload
  + fixed hash-domain separation
  + parent / child lineage
  + named-human decision
  + Worker receipts and authority epoch
  + runtime profile and production boundary
  → component digests
  → Case Audit Root
```

当前能力是 tamper-evident 的确定性血缘复核。数字签名、可信时间戳和外部锚定必须按实际配置声明；仅有 SHA-256 不等于法律电子签名或物理不可篡改。

协议细节见 [GOVERNED_AUDIT_ENVELOPE.md](GOVERNED_AUDIT_ENVELOPE.md)。跨基准分母与声明边界见 [GOAI 评分证据索引](GOAI_SCORE_EVIDENCE_INDEX.md)。

## Governed Outcome Envelope

Case Audit Root 回答单个 Incident 是否保持完整；`GovernedOutcomeEnvelope v1` 进一步把业务闭环投影到一个固定顺序的评委入口：父 Gate、Incident Case、Incident Audit Root、具名人工决定、CAPA 选择/批准、派生版本、CAPA 执行、Child Gate、最终责任队列、Recovery 和 Outcome Assessment。每个绑定同时保留上游自校验摘要和新的 JCS 域分离内容摘要，Envelope 根不能替代源工件。

服务读取 Envelope 时会重新验证全部源工件和跨工件关系，并与已落盘 Envelope 逐字节规范化比较。因此“修改结论后同时重算本地 Envelope 根”仍会失败。该机制依然只是本地 tamper-evident 完整性投影；`signature.status=NOT_CONFIGURED`，没有可信时间戳、签名者身份或外部锚。

CAPA 派生版本 v2 使用同一文件系统内的 staging 树，先回读校验 manifest 和 receipt，再以不覆盖目标的目录重命名发布。故障注入证明复制中断不暴露最终版本目录且可重试；该结论仅覆盖派生目录发布，不扩大为跨数据库、来源授权、Child Run 和全部回执的全局 ACID 事务。协议细节见 [GOVERNED_OUTCOME_ENVELOPE.md](GOVERNED_OUTCOME_ENVELOPE.md)。

## 发布边界

当前 checkout 同时保留冻结 RC2 历史复验能力，并已形成 RC3 严格 evidence namespace、字节一致双构包、clean-extract 文件审计与 detached Attestation。RC3 状态只有在 detached namespace、匹配 clean checkout 与声明 toolchain 组成的完整本地验证集由 verifier 返回 `PASS_LOCAL_INTEGRITY` 时才升级为 `PASS_LOCAL_RC3_RELEASE_CANDIDATE`；任一旁车或对账项缺失、漂移即按 [PROJECT_STATUS.md](PROJECT_STATUS.md) 退回 HOLD。

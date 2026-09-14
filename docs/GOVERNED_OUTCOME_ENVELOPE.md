# Governed Outcome Envelope v1

## 目的

`GovernedOutcomeEnvelope` 是完整 Incident/CAPA 闭环的单一只读投影。它不复制或改写源结论，只引用已经通过各自合同校验的工件，并把跨工件关系封装为一个可复算根。

评委入口：

```http
GET /v1/tasks/{task_id}/capa-cases/{case_id}/governed-outcome-envelope
```

响应包含 `ETag`、`X-Content-SHA256` 和 `Cache-Control: private, no-store`。该接口只对“一个 Incident 的具名决定精确绑定一个已完成 CAPA/Child Run”的案件开放；直接创建但未绑定 Incident 的 CAPA 不会伪造缺失链路。

## 固定工件集合

Envelope v1 按以下顺序绑定且只能绑定 12 类工件：

1. Parent `GateResult`；
2. `IndustrialIncidentCase`；
3. `GovernedAuditEnvelope` / Case Audit Root；
4. 具名 `IndustrialIncidentDecisionReceipt`；
5. CAPA selection；
6. CAPA approval binding；
7. private derived-data version receipt；
8. CAPA execution receipt；
9. Child `GateResult`；
10. final responsibility queue；
11. CAPA recovery receipt；
12. CAPA outcome assessment。

每项同时记录：资源 ID、schema version、上游完整性摘要类型、上游 SHA-256，以及该工件在 Outcome 专用 hash domain 下的 JCS 内容摘要。固定顺序、固定集合和固定 domain 可阻止删项、换位和跨类型摘要复用。

## 摘要协议

```text
RFC 8785 JCS payload
  → magic || uint16be(domain_length) || domain
          || uint64be(payload_length) || payload
  → SHA-256
```

Outcome 使用独立的 `visiondata-gate.outcome-frame.v1\u0000` magic 和封闭 domain 集。最终 `outcome_root` 覆盖协议、发行者、本地身份边界、Subject、12 项绑定、人工权限、结果边界、签名状态和 claim boundary。

## 读取时的失败关闭

服务不会只检查 Envelope 自报哈希。每次读取都重新执行：

- Parent/Child Evidence ZIP 文件 SHA-256 核验；
- Incident Case、Decision、CAPA 各回执自身 seal 核验；
- Incident Audit Root 与 Case 绑定核验；
- Incident Decision → CAPA Case/Plan 精确绑定；
- Parent Evidence 在 selection、approval、execution、recovery 中的一致性；
- Child task、lineage、Evidence、Gate decision 的一致性；
- final queue、recovery、outcome assessment 的交叉摘要一致性；
- 重新构建 Envelope，并与已持久化版本作 JCS 字节比较。

因此，单独修改 Envelope 后重新计算本地 `outcome_root` 仍不能替换源工件。若源工件或跨工件关系漂移，接口返回失败关闭状态，不提供一个看似完整的新结论。

## CAPA 派生目录发布

Derived-data version v2 在最终版本目录的同一父目录创建唯一 staging 树。资产复制、metadata、private manifest、source profile 和 receipt 全部完成后，系统回读 manifest/receipt 并校验 seal，最后以不覆盖现有目标的同文件系统目录重命名发布。

该机制保证：

- 复制工具中途失败时，最终版本目录不可见；
- 临时 staging 只清理本次 `mkdtemp` 创建且仍位于已解析 publish parent 内的精确目录；
- 故障解除后，同一 CAPA 可重新执行派生构建；
- 已存在的最终版本不会被覆盖。

原子性范围为 `DERIVED_VERSION_DIRECTORY_NAMESPACE_ONLY`。来源授权数据库记录、Child Task、模型/工具执行和后续 CAPA 回执属于独立的 write-once 阶段，不声明跨系统 ACID 事务。

## 安全与声明边界

```text
signature.status=NOT_CONFIGURED
production_release_allowed=false
machine_write_permitted=false
direct_equipment_control_permitted=false
root_cause_status=NOT_ESTABLISHED
```

允许表述：本地 tamper-evident、确定性、可复算的闭环完整性投影。

禁止表述：数字签名、可信时间戳、不可否认性、外部不可篡改存证、根因证明、客户验收、安全认证或生产放行。

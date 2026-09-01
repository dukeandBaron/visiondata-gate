# Governed Audit Envelope v1

## 结论与兼容边界

当前升级采用“历史摘要合同不动、新增工业审计 Sidecar”的兼容路线：

```text
v1 / v2 / v3 case_sha256       PRESERVED
v1 phase-event / receipt SHA   PRESERVED
Governed Audit Envelope v1     ADDED
RFC 8785 JCS                    NEW SIDECAR ONLY
Digital signature              NOT_CONFIGURED
Trusted timestamp              NOT_CONFIGURED
```

因此，已有 v1/v2/v3 Golden Fixture 的原始 `case_sha256` 不会因升级漂移；新案件额外生成
一个可独立复核的 `Case Audit Root`。JCS 在这里提供跨实现确定性序列化，不代表单位换算、
字段别名、默认值或不同业务对象之间的“语义等价”。

## 固定摘要协议

协议参数由代码固定，客户端不能选择算法、规范化方式或 Hash Domain：

```text
protocol_id             visiondata-gate.governed-audit-envelope.v1
digest_algorithm        sha256
canonicalization        rfc8785-jcs-v1
framing                 visiondata-gate-domain-frame-v1
```

每个摘要的 preimage 使用无歧义长度前缀：

```text
magic
|| uint16be(domain_length)
|| domain_utf8
|| uint64be(jcs_payload_length)
|| rfc8785_jcs_payload
```

域集合是服务端枚举，分别覆盖 Case、Parent Case、Human Decision、Phase Event、Worker
Receipt、Runtime Profile Binding、Site Pack、Governed Context、Control Plane、Policy
Contract 和最终 Audit Root。相同 JSON 内容处于不同对象域时会得到不同摘要。

## Audit Root 实际绑定的内容

每个新案件的 Envelope 绑定：

- 历史 `case_sha256` 与新的 Case JCS 域摘要；
- 严格有序、序号连续的 Phase Event 列表，同时保留每条历史 `event_sha256`；
- child Case 的 Parent Case 与授权 Human Decision；root Case 对这两项标记为不适用；
- 每个实际 Worker Receipt 的历史摘要与 JCS 域摘要；
- Runtime Profile Binding，以及适用时的 Site Pack 和 Governed Context；
- Control Plane Bundle；
- 当前案件状态、建议、`root_cause_status=NOT_ESTABLISHED` 和全部生产禁止权限；
- 本地产品服务记录的 Actor、Workspace、Project 与明确的身份保证级别；
- `signature.status=NOT_CONFIGURED` 及其保证边界。

Envelope 使用 RFC 8785 字节直接持久化：

```text
<case-dir>/audit/governed_audit_envelope.json
```

若 Sidecar 存在，案件每次读取都会重算并交叉核验所有上述材料；任何内容、顺序、对象域或
Audit Root 漂移都会失败关闭。升级前没有 Sidecar 的历史案件仍可按原 SHA 合同读取，API
不会伪造一份事后 Envelope。

## API 与独立验证

读取已经验证的 Envelope：

```http
GET /v1/tasks/{task_id}/industrial-incidents/{case_id}/audit-envelope
X-Actor-User-Id: <workspace member>
```

不启动 API 或数据库时，可直接验证一个完整案件目录：

```powershell
visiondata-gate incident-audit-verify --case-dir <absolute-case-directory>
```

成功输出包含：

```text
verification_status       PASS
canonical_payloads        PASS
event_chain               PASS
parent_child_binding      PASS | NOT_APPLICABLE
worker_receipts           PASS
governance_bindings       PASS
audit_root_sha256          <64-hex>
signature                 NOT_CONFIGURED
```

失败返回码为 `2`，并输出机器可读的 `verification_status=FAIL` 与错误信息。

## 安全与声明边界

当前实现允许使用以下表述：

```text
tamper-evident
deterministic lineage verification
RFC 8785 canonicalized, domain-separated SHA-256 audit root
```

当前实现不允许声称：

```text
tamper-proof
数字签名已配置
签发人身份已由 PKI/KMS 认证
可信时间戳
Merkle inclusion proof
业务逻辑等价证明
物理因果证明
SLSA L3、IATF 16949、GAMP 5 或第三方认证
```

没有外部签名或透明日志时，拥有全部本地文件写权限的人仍可重写材料并重新计算摘要。要把
“篡改可检测”提升为可验证的签发人身份和时间保证，后续版本需要 KMS/PKI 或 OIDC 签名、密钥
轮换、可信时间戳，以及把 Audit Root 发布到独立保管介质。当前 `NOT_CONFIGURED` 状态不会被
摘要本身掩盖。

当前 Audit Root 是对完整清单的确定性聚合摘要，不是二叉 Merkle Tree；它适合当前案件规模的
全量复验，但尚不提供无需下载全部事件的局部 inclusion proof。

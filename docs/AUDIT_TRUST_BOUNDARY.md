# JCS / SHA-256 审计与可信时间边界

状态快照：2026-09-12。本文明确当前审计链能检测什么、不能证明什么。它补充现有
`GOVERNED_AUDIT_ENVELOPE.md` 与 `RELEASE_ATTESTATION_V1.md`，不改变任何摘要字节。

## 结论

当前系统实现的是：

```text
RFC 8785 JCS canonicalization                 IMPLEMENTED
length-prefixed hash-domain separation        IMPLEMENTED
SHA-256 content and lineage binding            IMPLEMENTED
task-level local audit anchor                   IMPLEMENTED
deterministic rebuild / replay verification    IMPLEMENTED
digital signature                              NOT_CONFIGURED
trusted timestamp                              NOT_CONFIGURED
external transparency anchor                   NOT_CONFIGURED
independent signer identity                    NOT_CONFIGURED
```

因此，`audit_root`、`created_at` 或本地 anchor 的存在都不能被描述为 RFC 3161
可信时间戳，也不能证明“这份记录在某个外部可验证时间之前已经存在”。

## 三层本地完整性能力

| 层 | 已实现能力 | 边界 |
|---|---|---|
| 工件摘要 | JCS 将同一 JSON 语义规范化，再用域分离 SHA-256 绑定 | 无密钥，任何能重写全部材料的人都能重算 |
| Case Audit Envelope | 绑定 Case、事件、Worker 回执、治理材料、安全结果与 lineage | 只有保留原 root 或有可信副本时才能发现替换 |
| Task-level Audit Anchor | 在 Case sidecar 目录之外绑定 Case SHA 与 Audit Root | 能阻止只替换 sidecar；仍和产品根位于同一管理域 |
| Release Attestation | 绑定 Git、锁文件、测试、双构包与候选 ZIP | 当前未签名、无可信时间、无外部日志，且 dirty tree 不能成为通过候选 |

本地 task-level anchor 不是“外部锚定”。如果攻击者可以同时改写 Case、事件、Envelope、
task-level anchor、数据库和验证程序，随后重算所有摘要，单机材料本身无法证明旧版本曾经
存在，也无法证明攻击发生在何时。

## 威胁与检测矩阵

| 行为 | 当前能否检测 | 成立条件 |
|---|---|---|
| 修改一条事件但不更新摘要 | 能 | 使用现有验证器 |
| 调换、删除或重复事件 | 能 | 连续序号、固定集合和 Audit Root 均被复核 |
| 把一种工件摘要复用到另一种工件 | 能 | hash domain 与长度前缀固定 |
| 只替换 Case sidecar Envelope | 能 | task-level anchor 仍可信且未被同步替换 |
| 修改 JSON 空白或键顺序 | 不视为语义篡改 | JCS 规范化会得到相同语义字节 |
| 修改全部本地材料并重算整链 | 不能独立证明 | 没有独立保管的旧 root、签名或透明日志 |
| 伪造签发人身份 | 不能防止 | 当前无 PKI/KMS/OIDC 签名 |
| 伪造本地 `created_at` | 不能防止 | 字段由本机生成并被摘要绑定，但不是可信时钟证明 |
| 证明记录在指定时间前存在 | 不能 | 当前无 RFC 3161 TSA 或独立公开日志 |
| 证明业务结论真实 | 不能 | 完整性不等于来源真实性、因果性或法律权属 |

## 时间字段的正确语义

当前各回执中的 `created_at`、`recorded_at`、`decided_at` 或类似字段只能解释为：

> 该字符串是被当前摘要绑定的本地声明值；验证器可以发现值被单独修改，但不能认证
> 产生它的时钟、主体或真实发生时间。

允许写“摘要绑定的本地记录时间”，不允许写“可信时间戳”“公证时间”“不可抵赖签发
时间”或“第三方证明的存在时间”。

## 当前允许和禁止的表述

允许：

```text
tamper-evident under retained-root assumptions
RFC 8785 canonicalized, domain-separated SHA-256
deterministic local lineage verification
task-level local anchor against Sidecar-only replacement
```

禁止：

```text
tamper-proof
cryptographically signed
RFC 3161 timestamped
externally anchored
non-repudiable signer identity
immutable against a full local administrator
```

## 提升为可信外部锚定的后续路线

以下均为 `NOT_IMPLEMENTED`，不得提前写进能力表：

1. 使用 KMS/HSM、Sigstore/OIDC 或企业 PKI 对 Audit Root 签名，并提供 key ID、证书链、
   撤销与轮换策略；
2. 把已签名 root 提交给 RFC 3161 TSA，保存时间戳 token 与 TSA 证书验证材料；
3. 或将 root 发布到独立透明日志/WORM 介质，保存 inclusion proof、checkpoint 和独立
   见证者信息；
4. 验证器必须同时验证内容摘要、签名、可信时间、外部 inclusion 和撤销状态；
5. 外部服务不可用时必须返回 `NOT_CONFIGURED / NOT_VERIFIED / HOLD`，不能回退成“本地
   SHA 等价于可信时间”。

在上述链路真正实跑并留下第三方回执之前，当前保证级别保持：

```text
DIGEST_INTEGRITY_ONLY_NO_SIGNER_IDENTITY_OR_TRUSTED_TIME
```


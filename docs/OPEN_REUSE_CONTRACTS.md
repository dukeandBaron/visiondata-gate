# 开放复用合同｜Rule Pack、Evidence Schema 与 Adapter SDK

状态：`PUBLIC_SOURCE_AVAILABLE / EXTERNAL_CLEAN_CLONE_REPRO_PENDING`

项目采用“私有权威仓 + 隐私安全公共镜像”。公共镜像已经提供可复用源码、锁文件、Schema、Rule Pack、Skills、Adapter、示例和文档；在取得第三方 clean-clone 回执前，仍不能把“代码公开”写成“外部评委已复现”。

## 1. 可复用资产

| 资产 | 入口 | 用途 |
|---|---|---|
| Industrial Rule Pack v1 | `rulepacks/industrial-v1.json` | 冻结五类规则、三类动态触发和默认失败关闭边界 |
| Rule Pack Schema | `schemas/rulepack.schema.json` | 校验规则 ID、版本、优先级、动作和发布边界 |
| Evidence Finding Schema | `schemas/evidence-finding.schema.json` | 统一 finding、evidence span、reason trace 和 source refs |
| Adapter Manifest Schema | `schemas/adapter-manifest.schema.json` | 声明 adapter 身份、能力、只读和数据边界 |
| Adapter Observation Schema | `schemas/adapter-observation.schema.json` | 绑定输入快照、观察结果和证据 lineage |
| Adapter SDK | `src/visiondata_gate/adapter_sdk.py` | 离线 conformance、路径/密钥扫描和身份绑定 |
| 示例 Adapter | `adapters/examples/omni-readonly-*.json` | 最小只读接入模板，不含原始 Omni 字节 |
| Industrial Skill SDK | `src/visiondata_gate/industrial_skills.py` | 强类型、版本锁定、只读的显式实例注册与调用 |
| Skill 接入说明 | `docs/INDUSTRIAL_SKILL_SDK.md` | 证据绑定、失败关闭、确定性示例与安全边界 |

## 2. 当前验证

Rule Pack：

- 5 条规则、3 类动态触发；
- `production_release_allowed_by_default=false`；
- `raw_redistribution_allowed=false`；
- source file SHA-256：`dcf05a1ccdb7053c9ab7a11eb78f20d3087a79ef046198fe42018a785523a70b`；
- 状态 `PASS` 只证明 Schema、唯一性、摘要与失败关闭排序。

Adapter example：

- 7/7 离线检查通过；
- 覆盖 manifest / observation Schema、路径与密钥脱敏、adapter 身份、只读边界、finding lineage 和输入快照绑定；
- 文件 SHA-256：`cae357945a2f2bbc73b83be9be0a094e3d9904edf9b35d5f4a5820ee05e96cec`；内嵌 canonical receipt SHA-256：`92848901e1ac46f3ffd22e0e2398571273d8b313a8f54dc2617e3c8abbe5a16e`；
- `actual_model_call_count=0`、`network_probe_performed=false`。

Industrial Skill example：

- 内置 `MetadataCountDriftSkill` 对两项独立图像计数执行确定性绝对差对账；
- 每个 Observation 绑定 source ID、source version、snapshot SHA-256、evidence
  selector、Skill version 与 algorithm version；
- Registry 只接受显式构造的实例和精确版本，不扫描插件目录、不动态 import；
- 缺输入、manifest 漂移、异常或输出证据越界均失败关闭为 `DEFER`；
- 当前为受信 host 的 in-process 合同，不是非受信 Python 代码安全沙箱；首个内置
  Metadata Skill 已由 Dynamic Leader 的固定 Worker 证据触发调度。

## 3. 复验命令

```powershell
.\.venv\Scripts\python.exe -m visiondata_gate.cli rulepack-verify `
  --rulepack rulepacks\industrial-v1.json `
  --output output\reuse\rulepack_receipt.json

.\.venv\Scripts\python.exe -m visiondata_gate.cli adapter-conformance `
  --manifest adapters\examples\omni-readonly-manifest.json `
  --observation adapters\examples\omni-readonly-observation.json `
  --output output\reuse\adapter_conformance_receipt.json

uv run --frozen pytest -q tests\test_industrial_skills.py
```

## 4. 复用边界

- Rule Pack 不是具体工厂阈值认证；迁移场景必须重新确认规则、测量合同和责任人。
- Adapter conformance 不证明数据授权、准确率、Hosted 连接或生产安全。
- 外部工具只能返回 Observation；Frozen Policy Judge 和生产批准权限不能下放给 Adapter。
- Industrial Skill Registry 不提供任意代码沙箱；第三方实现必须经过审查，非受信代码
  需要独立进程或容器隔离。
- 当前 Registry 是显式调用扩展点；只有内置 Metadata Skill 存在固定 Worker 集成，
  不声称任意第三方 Skill 会被 Dynamic Leader 自动发现或安全调度。
- 原始数据、密钥、绝对路径、模型权重和私有运行数据库不进入示例或开源包。
- 公共镜像必须通过完整历史隐私扫描、Pages 构建扫描和 source commit/tree 绑定；仍需独立 clean-clone 与第三方复验，才能把开放贡献状态从“已公开”升级为“外部已复现”。

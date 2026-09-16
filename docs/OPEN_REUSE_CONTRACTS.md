# 开放复用｜核心代码、Skill、Schema 与 Adapter

状态：`PUBLIC_SOURCE_AVAILABLE / EXTERNAL_CLEAN_CLONE_PENDING`

项目只维护一个 canonical GitHub 仓 `dukeandBaron/visiondata-gate`，本地工作区保留不可公开的数据和回执。本次核验仓库为 Public，项目自有源码已有复用合同与许可证；但公开可读不等于第三方已经 clean-clone、部署或验证成功，也不授权公开客户数据和私域回执。

## 1. 可复用资产

| 资产 | 入口 | 用途 |
|---|---|---|
| 核心代码地图 | [`src/visiondata_gate/README.md`](../src/visiondata_gate/README.md) | 按数据合同、检查、编排、整改、学习和服务层选择入口 |
| 文本 Skill 规范 | [`skills/README.md`](../skills/README.md) | 5 份版本化工作流说明；不是一键安装插件 |
| Schema 目录 | [`schemas/README.md`](../schemas/README.md) | 区分独立 JSON Schema、生成模型 Schema 和 Schema 集合 |
| 可执行 SDK 示例 | [`examples/reuse/`](../examples/reuse/README.md) | 无模型、无网络的真实 Skill 注册/调用/回执验证 |
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

先运行一个真实 SDK 示例：

```text
uv run --no-sync python examples/reuse/metadata_skill.py --metadata-count 12 --observed-count 14
```

它使用合成计数，实际调用 `visiondata-gate.metadata-count-drift@1.0.0` 并验证回执；不读取图像、模型或工厂数据。

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
- 若开放仓库或导出快照，必须分别通过历史隐私、当前树、Pages 和 source commit/tree 绑定；仍需独立 clean-clone/部署回执才能声明外部复现。

[版本兼容](VERSIONING.md) · [许可证范围](LICENSING.md) · [贡献指南](../CONTRIBUTING.md)

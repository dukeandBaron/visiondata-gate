# Schema 与请求合同

Schema 描述数据形状，不替代身份鉴权、来源授权、摘要复核、状态机或生产批准。JSON 校验通过不等于请求可以执行。

| 文件 | 类型 | 实现与用途 |
| --- | --- | --- |
| [rulepack.schema.json](rulepack.schema.json) | 独立 JSON Schema | [rulepack.py](../src/visiondata_gate/rulepack.py)，规则包版本和决策边界 |
| [evidence-finding.schema.json](evidence-finding.schema.json) | 独立 JSON Schema | Finding 的证据引用、摘要和建议 |
| [adapter-manifest.schema.json](adapter-manifest.schema.json) | 独立 JSON Schema | [adapter_sdk.py](../src/visiondata_gate/adapter_sdk.py)，适配器身份与权限声明 |
| [adapter-observation.schema.json](adapter-observation.schema.json) | 独立 JSON Schema | 适配器观察结果和输入快照绑定 |
| [operator_acceptance_requirements.v1.json](operator_acceptance_requirements.v1.json) | 导出的请求模型 Schema | [contracts.py](../src/visiondata_gate/contracts.py) 中的 `OperatorAcceptanceRequirements` |
| [compute_handoff_request.v1.json](compute_handoff_request.v1.json) | 导出的请求模型 Schema | [compute_handoff.py](../src/visiondata_gate/compute_handoff.py) 中的 `ComputeHandoffRequest` |
| [vision_model_requests.v1.json](vision_model_requests.v1.json) | **Schema 集合，不是单个请求 Schema** | `requests` 中的具名请求和 `detection_manifest`；对应 [local_model_registry.py](../src/visiondata_gate/local_model_registry.py) |

独立 Schema 按其 `$schema` 声明使用。生成的 Pydantic 模型 Schema 可能没有 `$schema`；消费方需固定模型和验证器版本。

`vision_model_requests.v1.json` 的 `schema_version=visiondata-gate.vision-model-api-schemas.v1` 标识集合格式。验证具体请求时选择 `requests` 内对应项；不能把整个集合交给普通 JSON Schema validator，再把空约束的接受误当成请求有效。服务端模型、工作空间权限和业务校验仍是执行入口。

## 验证一个规则包

在锁定依赖的源码根目录使用新输出路径：

```text
uv run --no-sync visiondata-gate rulepack-verify --rulepack rulepacks/industrial-v1.json --output output/reuse-rulepack-first.json
```

它验证规则包自身，不证明阈值适合某一工厂。应用真实数据前仍需明确图像规格、类别、划分、用途和复核要求。

[版本与兼容](../docs/VERSIONING.md) · [复用指南](../docs/OPEN_REUSE_CONTRACTS.md) · [许可证](../docs/LICENSING.md)

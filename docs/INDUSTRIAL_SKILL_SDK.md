# Industrial Skill SDK｜只读、版本锁定的工业测量插件契约

状态：`LOCAL_EXECUTABLE_CONTRACT / REVIEWED_IN_PROCESS_ONLY`

`visiondata_gate.industrial_skills` 提供可注册、可调用、可复验的工业测量
Skill 契约。它用于接入确定性测量算法，不赋予插件生产判断权或机台控制权。

## 1. 执行边界

- Registry 只接受调用方显式构造的 `BaseIndustrialSkill` 实例；不读取字符串
  entrypoint、不动态 import、不执行表达式。
- Skill 只收到 `IndustrialSkillInvocation`：已授权源的脱敏 ID、源版本、快照
  SHA-256，以及数值测量和 JSON Pointer 证据定位。接口不包含本地路径、原始图像
  字节、网络客户端或机台控制句柄。
- Manifest 将 `read_only=true`、`raw_bytes_available=false`、
  `network_access_permitted=false`、`machine_write_permitted=false` 和
  `production_decision_authority=false` 固化为 `Literal`。
- 每个 Observation 必须绑定注册时的 Skill/算法版本，并逐条引用本次 Invocation
  已提供的 `source_id + source_version + snapshot_sha256 + evidence selector`。
- Registry 对输出进行第二次严格解析与绑定核验。缺失输入、manifest 漂移、异常、
  伪造 source 或引用 Invocation 之外的 span 均失败关闭为 `DEFER`。
- 回执包含 manifest、invocation、outcome 及各自 SHA-256；
  `verify_industrial_skill_receipt()` 可离线复核内容和绑定关系。

## 2. 内置确定性示例

`MetadataCountDriftSkill` 比较两项独立计数：

1. `metadata_image_count`：冻结元数据声明的图像数；
2. `tree_image_count`：独立目录清点流程产生的图像数。

算法只计算绝对差值，并与 manifest 中冻结的 `max_allowed_delta` 比较。默认阈值为
0；任何非零差值形成 `METADATA_COUNT_DRIFT` Observation。该结果只是只读对账证据，
不证明数据完整、数据授权、客户验收或生产放行。

Omni Dynamic Leader 在首轮证据出现 `METADATA_COUNT_DRIFT` 时，会向固定的
`worker.metadata-reconciliation` 派发二次扫描，并由该 Worker 显式构造上述强类型
Invocation、精确调用 `visiondata-gate.metadata-count-drift@1.0.0`。动态任务输出保存
完整脱敏回执、Skill/算法版本、计数差值、回执 SHA-256 和核验状态。Skill 返回
`DEFER`、回执核验失败或 Observation 未绑定本次差值时，该 Worker 以失败状态结束，
Frozen Judge 保持失败关闭；不会自动修复源数据或授予生产放行。

## 3. 最小调用

```python
from visiondata_gate.industrial_skills import (
    IndustrialEvidenceSpan,
    IndustrialMeasurement,
    IndustrialSkillInvocation,
    IndustrialSourceSnapshot,
    build_default_industrial_skill_registry,
)

source = IndustrialSourceSnapshot(
    source_id="omni-180-redacted",
    source_kind="authorized_metadata_snapshot",
    source_version="omni-profile-2026.08.28",
    snapshot_sha256="a" * 64,
)

def count(name: str, value: int) -> IndustrialMeasurement:
    return IndustrialMeasurement(
        name=name,
        value=value,
        unit="images",
        measurement_version="1.0.0",
        evidence_span=IndustrialEvidenceSpan(
            source_id=source.source_id,
            source_version=source.source_version,
            snapshot_sha256=source.snapshot_sha256,
            span_kind="metric",
            selector=f"/metrics/{name}",
        ),
    )

invocation = IndustrialSkillInvocation(
    invocation_id="count-audit-001",
    source=source,
    measurements=(
        count("metadata_image_count", 180),
        count("tree_image_count", 183),
    ),
)
receipt = build_default_industrial_skill_registry().invoke(
    "visiondata-gate.metadata-count-drift",
    "1.0.0",
    invocation,
)
assert receipt.outcome.status == "OK"
assert receipt.outcome.observations[0].decision.is_anomaly is True
```

调用必须写明精确 `skill_version`。Registry 不采用“最新版本”别名，避免同一个请求
随安装环境漂移到另一套算法合同。

## 4. 新增一个 Skill

接入步骤不是“只写一个函数”这么简单；至少需要完成以下审查面：

1. 继承 `BaseIndustrialSkill`，返回完整 `IndustrialSkillManifest`，冻结算法版本、
   所需测量、阈值、许可证和声明边界；
2. 实现 `inspect(invocation)`，只从强类型 Measurements 计算
   `IndustrialSkillOutcome`，并把每个 Observation 绑定到输入 evidence span；
3. 在应用组合根中构造实例并调用 `IndustrialSkillRegistry.register(instance)`；
4. 用固定 Invocation 验证确定性、错误降级、版本漂移和回执复核。

项目不提供任意插件目录扫描或 entrypoint 自动发现。生产部署若允许非受信第三方代码，
应在独立进程/容器中增加 OS 权限、网络和资源隔离；本 Python ABC/Registry 是合同
校验层，不是恶意代码安全沙箱。

## 5. 当前集成状态

```text
强类型 manifest / invocation / observation = LOCAL PASS
显式实例注册与精确版本调用              = LOCAL PASS
内置 MetadataCountDrift 确定性示例       = LOCAL PASS
失败关闭与离线回执自校验                 = LOCAL PASS
Dynamic Leader 调度内置 Metadata Skill   = LOCAL PASS
任意第三方 Skill 自动发现/自动调度       = NOT PROVIDED
非受信插件 OS 级沙箱                     = NOT PROVIDED
Hosted / 客户 / 生产验证                  = HOLD
```

因此，当前只能声明“首个内置 Metadata Skill 已由 Dynamic Leader 的固定 Worker
证据触发调度”。不能写成“任意第三方 Skill 放进目录就会被自动发现和安全执行”，也
不能把 Python 层 `read_only` 声明描述成操作系统级隔离。

## 6. 定向复验

```powershell
uv run --frozen pytest -q tests/test_industrial_skills.py tests/test_omni_adapter.py
uv run --frozen ruff check src/visiondata_gate/industrial_skills.py src/visiondata_gate/omni_adapter.py tests/test_industrial_skills.py tests/test_omni_adapter.py
uv run --frozen ruff format --check src/visiondata_gate/industrial_skills.py src/visiondata_gate/omni_adapter.py tests/test_industrial_skills.py tests/test_omni_adapter.py
```

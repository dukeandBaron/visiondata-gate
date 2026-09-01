# Agent Runtime：生产内核、Demo 与验证边界

> 本文只描述当前本地实现。它不代表 Hosted AgentTeams 已成为执行后端，也不代表客户验收、
> 工厂部署、安全认证、生产放行或赛事官方评测。

## 一句话结论

VisionData Gate 现在有三条物理与语义上分开的路径：

```text
生产内核      授权本地来源 -> ProductService -> Agent Core -> ProductKernel 回执
Synthetic Demo 固定合成 fixture -> 演示运行时 -> Demo 证据
Validation     已保存的运行产物 -> 变异/故障/重放评测 -> 独立验证回执
```

生产任务的完成不依赖 pytest、fixture、Fake runner、轨迹变异、故障注入、消融或 benchmark。
Validation 只能观察或复制已保存产物，不能参与生产任务的规划、工具执行、裁决和证据生成。

## 1. 授权本地生产内核

正式本地入口是 `visiondata-gate product-run`。它只通过 `ProductService` 公开接口创建租户、
工作区、项目、来源授权与任务，然后执行同一个产品生命周期；不会绕过服务直接调用工具。

```text
显式来源授权
  -> 来源 allowlist / 只读画像 / 授权回执
  -> Intake
  -> Deterministic Planner
  -> Read-only Tool Workers
  -> Deterministic Evidence Council
  -> Frozen Policy Judge
  -> Evidence Delivery
  -> AgentCoreExecutionReceipt
  -> ProductKernelRunReceipt
  -> SHA 校验后的证据 ZIP
```

当前生产内核是本地确定性 Agent Core：

- **Intake**：验证授权来源、冻结只读选择和来源画像；源资产不复制到产品目录。
- **Planner**：规划首轮证据工具，并按已产生的 finding、预算和白名单决定动态补证任务。
- **Tool Workers**：实际执行图像质量、重复/泄漏、标注完整性、覆盖与 metadata 等确定性测量。
- **Evidence Council**：交叉解释 typed finding、ToolTrace 和测量值。当前后端明确标记为
  `Deterministic Evidence Council`，不是五个独立外部模型。
- **Policy Judge**：只使用冻结规则签发 `PASS / QUARANTINE / RECAPTURE / DEFER` 等业务裁决；
  缺证、工具错误和合同漂移时失败关闭。
- **Evidence Delivery**：封存脱敏 GateResult、动态计划、运行轨迹、工单和完成回执。

模型调用数在这条入口中固定为 0；Hosted、OpenToken 和其他外部网络传输固定关闭。确定性并不
等于“没有 Agent”：规划、动态任务选择、工具权限、证据解释、裁决和交付仍是分阶段的受控任务
闭环；但文档不会把确定性角色冒充成真实 LLM 或 hosted Worker。

## 2. Live 事件与最终轨迹

Adapter 在对应阶段真正执行期间发出 `AgentRuntimeSignal`，ProductService 的 event sink 同步
持久化这些事件。最终 `RuntimeTrace` 在执行完成后由已捕获事件和 typed 执行结果物化，因此回执
使用以下准确措辞：

```text
signal_capture_mode=LIVE_CORE_SIGNALS
posthoc_event_synthesis=false
trace_materialization_mode=POST_EXECUTION_FROM_LIVE_SIGNALS
```

也就是说，事件不是门禁结束后凭空补写的；但最终 JSON 文件确实在运行结束时封存。任务 DAG 是
从已执行任务、依赖和回执生成的 provenance graph，不宣传为通用分布式 DAG 调度器。

`AgentCoreExecutionReceipt v2` 强制包含 Intake、Planner、Tool、Council、Judge、Delivery 六阶段，
并绑定：

- live event 数量、从 1 连续的序号、必需阶段首次出现顺序、阶段序列和 event-chain SHA-256；
- RuntimeTrace SHA-256；
- 首轮与最终 GateResult SHA-256，以及最终 Gate 决定；
- Dynamic Leader Plan SHA-256；
- Planner/Council 后端、工具调用数、动态任务数、模型调用数与 Tool ERROR 计数；
- Intake、Planner、Judge、Delivery 必须以成功终态收口；Tool/Council 可以记录失败，但 Tool ERROR 与最终 `PASS` 不得同时封存；
- `production_decision_authority=human_only`。

`ProductKernelRunReceipt` 再绑定 RuntimeTrace、typed GateResult、所有必需内核文件及其 SHA-256。
ProductService 在产品侧补充工单/时间线之前和打包之前各验证一次。任务来源与 runtime kind 也被
强制对应：synthetic 任务不能冒充 `authorized_local_readonly`，反之亦然。

## 3. 完成与业务裁决是两件事

`task_execution_status=COMPLETED` 只表示本次内核阶段、typed 结果和证据交付合同完整，不表示
`final_decision=PASS`。同理，即使 GateResult 为 `PASS`，也不会自动得到生产放行：

```text
production_approval_status=pending
production_release_allowed=false
production_decision_authority=human_only
```

业务裁决和执行状态必须分别读取；任何代码、README 或 UI 都不得把二者合并为一个绿色状态。

## 4. Synthetic Demo

`agent-demo` 与默认演示项目使用固定合成数据、隐藏 reserve 和演示用修复闭环。它用于离线展示、
UI 排练和回归，不是授权来源生产内核。Synthetic 路径也必须返回 typed `AgenticDemoRun`，再由
`seal_product_task_run(runtime_kind="synthetic_demo")` 形成强类型完成回执；旧
`SimpleNamespace` 或 `schema_version=test` 无法把任务推进到 `COMPLETED`。

Demo 内的固定标签指标只描述该 fixture 自身，不是客户数据精度、现场效果或生产 SLO。

## 5. 独立 Validation Harness

以下命令属于显式验证阶段，不在普通产品运行中自动执行：

- `agent-eval`：复制并变异已保存轨迹，检查一致性 verifier 的检测能力；
- `tool-fault-eval`：注入 timeout、stale response 等工具故障，验证 fail-closed；
- `network-resilience-eval`、`prompt-injection-eval`、`backend-contract-eval`：运行各自固定分母
  的本地评测；
- architecture/dynamic benchmark：比较冻结 fixture 上的策略，不改变任何生产任务结果。

这些回执可以进入后续 QA 报告，但不得成为 ProductKernel 完成条件，也不得被表述为真实工厂、
真实 hosted 或外部模型效果。

## 6. Incident governed memory

工业异常案件使用另一条受控工作流。治理记忆在 Planner 之前召回，并通过 retrieval receipt、
planning input、Planner receipt、Case 和 Runtime Profile Binding 绑定同一 SHA-256。被接受的历史
卡片只能作为调查参考或反证提示：

```text
historical_reference_only=true
may_set_current_case_fact=false
policy_judge_input=false
```

被拒绝的跨站点、跨产线、跨工位、跨相机、过期、撤销或超出 rank limit 的卡片仍保留在 retrieval
receipt 中，不能静默消失。当前案件事实只能来自本次权威请求与工具证据。

## 7. Hosted AgentTeams 边界

当前 Hosted AgentTeams 实现是受控 submission/probe gateway，具备本地协议、幂等、重试、熔断、
凭据脱敏和回执校验；它不是 `ProductService` 的 Agent 执行后端。

```text
HOSTED_SUBMISSION_GATEWAY=IMPLEMENTED_LOCAL
HOSTED_AGENT_EXECUTION_BACKEND=NOT_IMPLEMENTED
REAL_HOSTED_CONNECTION=NOT_PROBED
```

因此本地 transport 测试通过不能被写成 9 个远程 Worker 已运行，也不能写成真实 Matrix/Controller
已连接。

## 8. 可执行入口

- 生产内核：[Product Kernel CLI](PRODUCT_KERNEL_CLI.md)
- 本地运行：[Running](RUNNING.md)
- API 生命周期：[API Quick Start](API_QUICKSTART.md)
- 声明边界：[Claim Scope](CLAIM_SCOPE.md)

本轮工程验收应分别报告 production core、Synthetic Demo、Validation Harness、Hosted gateway 和
真实外部连接状态，不再用一个模糊的“Agent tests passed”概括全部能力。

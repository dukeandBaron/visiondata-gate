# 数据来源与合规说明｜GOAI 复赛 RC3

作品：VisionData Gate｜工业视觉数据治理与发布 Agent
官方排期方向：AI+其他；应用场景：工业视觉数据治理 / 制造业
状态：`PASS_LOCAL_BOUNDARY / OWNER_SOURCE_URL_ACTION_REQUIRED`

本文件对应官方参赛手册第 8、10-14 页要求。它记录当前本地处理事实和边界，不构成法律意见、数据所有权证明、赛事方背书、客户验收或生产批准。

## 1. 数据身份

| 字段 | 当前证据 |
|---|---|
| 本地名称 | `Omni-AD-30-release` |
| 本地 ReadMe 描述 | “Omni-AD-30 数据集为 Omni-AD 数据集的子集，包含 30 个类别，用于浙江省人工智能比赛”；公开部分含全部训练集和约 40% 测试集 |
| 取得/落盘时间证据 | 本地文件时间 2026-08-13；不把文件时间单独当作官方下载回执 |
| 原始来源 URL | `NOT_CAPTURED_IN_LOCAL_SOURCE / OWNER_ACTION_REQUIRED` |
| 明确数据许可证 | `NO_EXPLICIT_REDISTRIBUTION_LICENSE_FOUND` |
| 操作者权利声明 | 本地只读竞赛开发验证，禁止原始数据再分发 |
| 来源归档 SHA-256 | `773B089C120238599CF5D03D80445130EDA63DA66750F32555F7AD526B372851` |
| source tree manifest SHA-256 | `6F19DAC0EE336B723B16B4377F6ECBCCD9A66BDB0D041C6E5EF47E69E2CA32E8` |
| 脱敏 profile SHA-256 | `8F6086AE8CE1E3B2A3DF234CDCD52357886BAACE4DBCC5568E6A727982BD83A1` |

项目同时参考 Omni-AD 方法的公开代码仓库 <https://github.com/easyoo/Omni-AD> 与论文信息，但代码仓库/论文不是本地 `Omni-AD-30-release` 数据子集的许可证证明，二者不得混用。

在本次复赛材料上传前，账号持有人应从原下载页面、赛事平台下载记录或组委会说明补填准确来源 URL、取得方式与允许使用范围。若无法补齐，材料必须继续保留 `OWNER_SOURCE_URL_ACTION_REQUIRED` / `NO_EXPLICIT_REDISTRIBUTION_LICENSE_FOUND`，且不得把原始数据随公共源码镜像或附件包提交。

## 2. 授权与访问控制

系统只有在以下条件全部满足时才接受本地源：

1. 服务端配置明确 allowlist 根目录；
2. 操作者主动填写使用目的与实际权利依据；权利依据默认留空，系统不自动代填；
3. 操作者确认用途已获授权、只读、禁止原始数据再分发；
4. 归档 SHA-256、路径摘要与脱敏 source profile 进入授权回执；
5. 创建任务前再次计算 source profile；数量、哈希、状态或驻留漂移即失败关闭；
6. 用户、工作区、项目和任务必须在同一逻辑作用域内。

当前 `X-Actor-User-Id` 和 SQLite 成员关系只用于本地逻辑隔离，不是登录认证、API Key 或生产 IAM。操作者声明是 `operator-attested`，不等于系统独立完成权属核验。

## 3. 实际处理范围

| 范围 | 已执行事实 | 不允许外推 |
|---|---|---|
| source profile | 4,464 张图像、1,439 个 masks、30 类；metadata 记录 4,449，数量漂移合计 15、涉及 3 类 | 4,464 张全部经过 Policy Gate |
| Policy Gate | 固定选择 180 张；首次 48 findings/原子记录、5 ToolTrace；最终 49 findings/原子记录、8 ToolTrace；聚合为 3 个风险流和 3 套候选方案 | 模型精度、全量数据认证、客户数据效果、49 个独立 Agent 任务 |
| Dynamic Leader | 1 replan、3 个 evidence-triggered Worker、18 个产品事件 | 任意任务都需要多 Agent |
| CAPA `_05` | 执行 49/49 最高覆盖方案；产品私有派生版本含 180 图像/60 masks；独立 child Run findings 49→33；6 条责任项关闭、43 条仍开 | finding 下降等于恢复成功、物理重采或生产放行 |
| 可行性 `_06` | 当前授权候选池未观察到可发布方案；最小恢复成本 `NOT_ESTIMABLE` | 未执行方案存在成功率、工时、金额或 ROI |
| 决策 | 父 Run `RECAPTURE`；child Run `RECAPTURE`；CAPA `TRANSFERRED_TO_INVESTIGATION`；生产授权 `pending` | 批次已获生产放行 |

系统仅做只读检查、生成风险处置流、候选方案、原子底账和证据交付；不直接控制工业设备，不替代现场专业人员、数据责任人和企业安全规范。

## 4. 最小化、驻留与脱敏

- 父来源原始图像、mask 和源目录保持服务器本地原位驻留；`_03` 父产品任务和 Evidence ZIP 为 `source_assets_copied_into_product=false`；
- 经具名操作者批准的 `_05` CAPA 只在产品私有 `derived_versions` 目录复制固定 Gate 的 180 图像/60 masks；该副本绑定批准、来源授权事件、父 Evidence、方案和回滚点，`raw_redistribution_allowed=false`、`public_export_allowed=false`；
- SQLite、Git、公开仓库和公开/复赛 Evidence ZIP 不包含上述派生原始资产；回滚方式是丢弃派生版本，不删除或改写父来源；
- 公开/交付证据只包含脱敏 sample ID、对象引用、聚合计数、规则结果、工单、trace 和哈希；
- 不输出类别名、原文件名、源绝对路径或本地用户名；
- 路径作为密码输入，业务界面只显示 source ID 与 profile 哈希；
- 当前未发现个人信息字段；若后续接入含个人或企业敏感信息的数据，需重新完成数据分类、最小化、授权、删除机制和访问控制评估，本回执不能自动沿用。

## 5. 交付包泄漏验证

2026-08-25 `_03` 计划审批与方案版父 Run 生成的脱敏 Evidence ZIP：

- SHA-256：`17631D2F9FA51E58D8DECDB13E4E9EF91F9D2119E2BBA344E51DB78F5F455098`；
- 18 个成员，ZIP 完整性检查无坏成员；
- 独立 verification 27/27 `PASS`，verification SHA-256 为 `38F14DAB1A6483AABCB77054B6D4A2E82E7780AE0932A38C0799D7AFBC2FB90D`；
- 检查包括：任务/计划/规则/来源审批绑定、source profile/Gate 分母分离、三条动态任务与 ToolTrace 绑定、六类工业来源、49/49 精确 finding 关联、3 个风险流及 3 套方案哈希、child Run 末波、无原始图像/文件名/私有路径/类别名、生产审批保持人工、异常模型/外部 LLM 未连接，以及旧来源注册库 SHA 前后不变。

此前 `_02` 的 18-member ZIP（SHA-256 `D63AAE...523971B`，22/22）与 `_01` 的 15-member ZIP（SHA-256 `ABF400...F18754`，16/16）均保留为历史证据，不覆盖也不冒充当前 `_03` 运行。

该 `PASS` 只证明本地脱敏证据合同，不证明数据许可证、客户验收、工厂部署或模型认证。

`_05` CAPA 与 `_06` assessment 是独立于 `_03` Evidence ZIP 的本地私有回执：

- `_05` CAPA pilot receipt 文件 SHA-256：`EAF897F91BB092C4DCB7A22A3FFB0DEC0982217D4C084D01855CA8EAC27B52B1`；
- `_06` assessment 文件 SHA-256：`35326A027591CD7EB0EA43470B8C50D1D3161FF654EA2F1CF4B9A4D892F00C63`；
- `_06` assessment 内嵌 canonical SHA-256：`18C2AD68B160C716792AEB64811F438488E24D5570648F1D3A6A8FBD8A2F0485`；
- CAPA 回执读取时重算自身 SHA，并交叉验证 selection、approval、derived version、execution、child lineage、recovery 和 final responsibility queue 的绑定；
- 这些回执可证明本地受控派生与失败转调查，不授权原始数据再分发，也不进入最终 RC3 包，除非完成脱敏 namespace 与敏感扫描。

## 6. 模型、第三方服务与外部系统

- 当前 RC3 产品运行使用 `local-deterministic` Runtime，实际外部模型调用为 0；
- LongCat/VGGT/OmniVGGT 仅有本机协议夹具，真实权重/服务/模型效果为 `REAL_BACKEND_NOT_CONNECTED / NOT_TESTED`；
- CVAT/FiftyOne 整改往返合同已实现，本地合同验证不等于外部服务已连接；
- AgentTeams v1.2.2 静态契约为 `PASS`，hosted transport 未连接，状态为 `mapped_not_connected`；
- 若后续接入商业 API 或闭源模型，必须新增调用环节、费用、权限、替代性、锁定风险、迁移成本和可复现性说明。

## 7. 代码、依赖与知识产权

项目自有代码按 Apache-2.0 发布，包含顶层 `LICENSE`、`NOTICE`、CycloneDX SBOM、第三方依赖精确版本与许可证清单。代码许可不扩展到外部数据、模型权重、客户资产或第三方素材。公共源码镜像和 RC4 附件包均不得包含 Python distributions、模型权重或原始 Omni 数据。

## 8. 人工确认与行业边界

- 工具或必需证据缺失：`DEFER`；
- 质量/泄漏/标注/覆盖/治理不满足规则：`RECAPTURE` 或 `QUARANTINE`；
- 跨工具处置冲突：生成 `INVESTIGATE` 工单，不由模型静默覆盖；
- 来源授权事件采用 append-only hash chain；授权撤销或到期后，未来读取、旧 CAPA 批准和执行重放均失败关闭，但系统不会声称已删除操作者原位管理的源字节；
- CAPA 只允许在批准预算内创建私有派生版本；父来源保持只读，父 Evidence 不改写，失败 child Run 必须进入最终责任队列或转调查；
- 本地 `PASS` 仅允许进入 `sandbox_experiment_training_pool`；
- 生产写回、设备控制、客户交付和安全责任人的最终判断始终需要真实授权主体。

## 9. 提交前责任人动作

- [ ] 补全原数据下载页面 URL、平台名称、取得方式和取得日期证据；
- [ ] 确认赛事平台是否允许竞赛用途展示聚合统计与脱敏回执；
- [ ] 在无法确认再分发许可证时，继续排除全部原始数据、截图和类别信息；
- [x] 已核对 RC3 PPT、视频、README、网站和 ZIP 未暗示独立权属认证或 4,464 全量 Gate；后续任一材料变更都必须重新执行同项核对；
- [ ] 保存实际提交材料 SHA-256 与官网回执。

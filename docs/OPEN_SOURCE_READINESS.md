# 开源就绪核验：官方 7 + 8 分证据地图

状态：`NOT_A_GUARANTEED_SCORE`。本页整理可检查的资产、命令和缺口，不是评委打分，
也不以文件数量、维护者自测或一张绿色徽章代替第三方能够实际运行。

依据：用户提供的《GOAI2026 赛道二「无界应用 Boundless Agents」决赛评审规则》
第六部分“二级考核点及评分依据”之“（五）开源价值与复用”：核心组件/Workflow/Skill 开放程度
7 分；文档、部署、复用与第三方验证 8 分。规则重点是第三方能否理解、部署、运行、
复用和继续开发，**不设 Star / Fork 单项分**。独立第三方记录不是另加的参赛准入条件，
但真实外部复现和长期采用能提供比维护者说明更强的证据。内部对应表见
[决赛证据地图](FINALS_EVIDENCE_MAP.md)。此处不公开原始规则文件的私人存储位置，
也不编造未核实的官方网页链接。

## 1. 核心组件、Workflow、Skill 开放程度｜7 分

| 审查对象 | 真实资产及复用接口 | 精确核验入口 | 当前证据边界 |
| --- | --- | --- | --- |
| 核心代码是否开放 | [核心代码地图](../src/visiondata_gate/README.md)、[Python 公共 API](PUBLIC_API.md)；包根稳定入口只有 `GateDecision`，其他调用绑定 commit 和协议 | 下文 L1；G1 查询仓库公开状态 | `PUBLIC_SOURCE_AVAILABLE`；不等于所有 API 已稳定为 1.0 |
| Workflow 是否可理解、继续开发 | [复用合同](OPEN_REUSE_CONTRACTS.md)、[Schema 目录](../schemas/README.md)、Rule Pack/Adapter 的输入输出合同 | 下文 L2；按合同改变合成输入、核对回执与拒绝路径 | 已有可执行合同；不是仅提供截图，也不是工厂规则认证 |
| Skill 是否真正可复用 | [文本 Skill 目录](../skills/README.md)、[可执行 SDK 示例](../examples/reuse/README.md)、[工业 Skill SDK](INDUSTRIAL_SKILL_SDK.md) | 下文 L3 两个不同输入；L4 SDK/复用测试 | Markdown 规范不是安装插件；Registry 只接收显式、受信实例，不提供任意代码沙箱 |
| 关键依赖与许可是否披露 | [LICENSE](../LICENSE)、[NOTICE](../NOTICE)、[许可范围](LICENSING.md)、[第三方声明](THIRD_PARTY_NOTICES.md)、[SBOM](SBOM.cdx.json) | 对照锁文件与实际分发物；下文 L1 检查包 API 边界 | 项目自有内容为 Apache-2.0；第三方组件、数据和模型各自许可 |

**私域数据与未授权权重不开放不是缺陷**。私有图像、标签、数据库、密钥、原始私有
回执以及无再分发授权的权重应留在公开范围之外。公开替代是可再分发的合成示例、
接口/Schema 和足以重新运行的命令，不是为了得分暴露原始材料。可选 Ultralytics 的
AGPL / Enterprise 义务不能由本项目 Apache-2.0 或进程隔离替代；完整桌面分发还须
核对真实内嵌组件，而不是把源码 SBOM 当成全部二进制的合规认证。

## 2. 文档、部署、复用与第三方验证｜8 分

| 审查对象 | 可交付证据 | 核验方法 | 仍需分别裁决 |
| --- | --- | --- | --- |
| 文档与接口 | [README](../README.md)、[采用指南](ADOPTION_GUIDE.md)、[API 接入](API_QUICKSTART.md)、[Python API](PUBLIC_API.md)、Schema、依赖锁 | L0 聚合复用回执和 L1 文档/导入合同；按 API 接入文档完成合法启动能力与账户认证，再创建独立合成任务 | 裸 `X-Actor-User-Id` 不是认证；不能为跑通文档启用测试绕过 |
| 部署与运行 | [跨平台入口](CROSS_PLATFORM_QUICKSTART.md)、[现场复现](LIVE_REPRODUCTION.md)；已存在的 tag、产物和各自摘要 | 使用新的目录、真实账户和合成输入，记录环境、退出码、输出 SHA；G3 查询实际发布资产 | 文档存在不等于新用户已跑通；旧安装器不自动含新源码功能 |
| 版本与继续开发 | [版本策略](VERSIONING.md)、[版本演进](VERSION_EVOLUTION.md)、[CHANGELOG](../CHANGELOG.md)、[软件引用](../CITATION.cff) | 固定完整 commit/tree；软件元数据、Schema、Skill、安装器构建身份分别记录 | `0.1.0`、竞赛 RC、Git commit 和 Windows build 不可互换 |
| 社区入口 | [贡献指南](../CONTRIBUTING.md)、[行为规范](../CODE_OF_CONDUCT.md)、[安全策略](../SECURITY.md)、[复现 Issue 模板](../.github/ISSUE_TEMPLATE/reproduction.md)、[PR 模板](../.github/pull_request_template.md) | L1 检查本地链接与必要字段；G1/G4 查询实际公开配置与反馈 | 模板不是已完成的第三方复现记录；Community profile 也不是比赛得分 |
| 第三方能否运行与复用 | 由实际执行者提交的版本、环境、完整命令、结果和可公开输出摘要 | 使用[复现模板](THIRD_PARTY_REPRODUCTION.md)，明确维护者/同团队/独立第三方身份及未运行步骤 | `EXTERNAL_CLEAN_CLONE_PENDING`；不能由维护者自测、机器人 PR、Stars、Forks 或下载次数替代 |

### 本轮可修与必须另取的证据

- 当前 PR 可以修正文档中的认证/命令漂移，补齐接口示例、版本/迁移说明、许可边界和
  复现模板，并为这些内容增加测试。测试记录仍须标明实际执行的命令和未运行项。
- main、PR、Pages、Release 是不同公开面：本地文档更新或 PR 检查成功不会自动
  合并、部署或发布。仅在相应授权与门禁满足后处理，不能跳过历史隐私审查。
- 独立第三方运行成功、使用中的实际问题、客户采用与持续业务价值必须来自实际
  执行者或使用方。维护者可以提供最小合成示例并解释错误，但不得代写或制造外部
  成功记录；失败和部分成功同样是有效反馈。

## 3. GitHub 公开面：带日期快照，不是自动更新状态

核验快照：**2026-09-19**，来源为只读 GitHub CLI/API 和无下载的 HTTP HEAD。
发布或答辩前必须按 G1–G4 **重新查询**，以下身份不能被复制成另一版本的当前结论。
表内 commit 是本页编辑前的观测快照，不是文档自身的源码身份；当前候选以
`PUBLIC_MIRROR_MANIFEST.json` 和 G2 的实时查询为准，不能循环把文档提交 SHA 写成自身证明。

| 公开面 | 本次观测 | 状态 |
| --- | --- | --- |
| 仓库 | canonical `dukeandBaron/visiondata-gate` 为 PUBLIC，默认分支 main，Apache-2.0；description、topics、homepage 与 Issues 已配置 | `PUBLIC_SOURCE_AVAILABLE` |
| 默认 main | `acc27f34b22a6d2fe883667ffd04a41351c462f8`；落后于当时候选，不能代表本次 TTT/反馈桥接源码 | `MAIN_BEHIND_REVIEWED_PR` |
| PR #37 | 本页首次只读审计时 head 为 `cec9278300fba42ef2b4bd9da6e7a3b173432cab`；OPEN、Draft；发布本轮开放复用补丁后必须用 G2 重新取 head 和 checks | `PR_37_DRAFT_NOT_MERGED`；CI 不是工业效果或外部复现 |
| Pages | 首页 HTTP 200；最近成功部署来自 `9144335fa6bb2b45a5cfae6570f5e5a3a4b7cf2f`；其后两轮在公开树/历史检查步骤失败，deploy 未执行 | `PAGES_SERVING_PREVIOUS_DEPLOYMENT` / `HISTORY_PRIVACY_HOLD` |
| Release | 有真实 prerelease 与附件；最新 Windows 候选仍绑定 `f7f31f7`，源码下载另有 `b604a63` 快照；HEAD 请求能到达附件，不等于本轮重新下载验收 | `NO_STABLE_RELEASE`；当次 `/releases/latest` API 返回 404，因没有非 prerelease 的 stable release |
| 第三方反馈 | 当次 Issues API 中的条目全是 PR；没有实际部署/复现 Issue；有代码作者记录，但不足以证明独立外部部署或采用 | `EXTERNAL_CLEAN_CLONE_PENDING` |

[PR #37](https://github.com/dukeandBaron/visiondata-gate/pull/37) ·
[公开发布列表](https://github.com/dukeandBaron/visiondata-gate/releases) ·
[Pages 门禁失败记录](https://github.com/dukeandBaron/visiondata-gate/actions/runs/35350788304) ·
[此前成功部署](https://github.com/dukeandBaron/visiondata-gate/actions/runs/35074955393)

**不能关闭或放宽历史隐私门禁**来制造 Pages 更新成功；当前树安全、完整历史安全、
源码包完整性、CI、静态部署、安装运行和第三方复现分别保留自己的状态。

## 4. 精确复核命令

### 本地合同（在已按文档安装锁定依赖的仓库根目录）

这些命令是真实入口，不代表本页生成时全部重新执行过；应把当次结果写入自己的
复现记录。测试通过也不意味着 GitHub 已部署或第三方实际采用。

L0：一次运行 Skill、Rule Pack 和 Adapter 三类真实公共合同；不需要模型、网络或私域数据。

```text
uv run --no-sync python -c "from pathlib import Path; Path('output/open-reuse').mkdir(parents=True, exist_ok=True)"
uv run --no-sync python tools/run_open_reuse_smoke.py --output-root output/open-reuse/run-01
```

核对 `OPEN_REUSE_RECEIPT.json` 的 `PASS_OPEN_REUSE_SMOKE`、三个组件字节摘要、
`production_release_allowed=false` 与 `THIRD_PARTY_REPRODUCTION_PENDING`。维护者 CI 从
clean checkout 运行同一入口，仍不是独立第三方采用证据。

L1：文档证据字段、链接、包级公开 API 与版本说明。

```text
uv run --no-sync python -m pytest tests/test_open_source_readiness.py tests/test_adoption_docs.py tests/test_public_api_surface.py -q
```

L2：Rule Pack、Adapter 的复用合同。

```text
uv run --no-sync python -m pytest tests/test_reuse_contracts.py -q
```

L3：真实 SDK 的变化输入和完整自定义 Skill 类，不需要图像、网络或模型。

```text
uv run --no-sync python examples/reuse/metadata_skill.py --metadata-count 12 --observed-count 14
uv run --no-sync python examples/reuse/metadata_skill.py --metadata-count 12 --observed-count 12
uv run --no-sync python examples/reuse/custom_range_skill.py --mean 230 --lower 64 --upper 192
```

L4：SDK 正向、异常、确定性与边界。

```text
uv run --no-sync python -m pytest tests/test_reuse_metadata_example.py tests/test_custom_skill_example.py tests/test_industrial_skills.py -q
```

这些复用示例的范围是合成输入、真实代码和回执验证，`REAL_MODEL_NOT_RUN`。
需要真实模型的测试必须单独提供合法运行环境与权重，跳过项不能写成真实模型 PASS。

### GitHub 当前状态（需要可用的 gh，只读查询）

G1：公开仓库、默认分支与许可证。

```text
gh repo view dukeandBaron/visiondata-gate --json visibility,defaultBranchRef,licenseInfo
gh api repos/dukeandBaron/visiondata-gate/branches/main --jq .commit.sha
gh api repos/dukeandBaron/visiondata-gate/community/profile --jq .files
```

G2：PR 的实际 head、Draft/合并状态与检查；绿色检查不是合并或上线。

```text
gh pr view 37 --repo dukeandBaron/visiondata-gate --json state,isDraft,headRefOid,baseRefName,mergeStateStatus,url
gh pr checks 37 --repo dukeandBaron/visiondata-gate
gh run list --repo dukeandBaron/visiondata-gate --workflow pages.yml --limit 5 --json headSha,status,conclusion,url
```

G3：列出所有发布身份，包括 prerelease；不要假定 `/latest` 一定存在。

```text
gh release list --repo dukeandBaron/visiondata-gate --limit 20
gh api repos/dukeandBaron/visiondata-gate/releases --jq '[.[] | {tag_name,draft,prerelease,html_url,assets:[.assets[] | {name,state,size,browser_download_url}]}]'
```

G4：区分实际 Issue、PR、机器人维护和第三方复现记录。只提交脱敏摘要，不复制
账户凭据、设备/客户身份或私有目录。

```text
gh issue list --repo dukeandBaron/visiondata-gate --state all --limit 100 --json number,title,state,url,labels
gh api repos/dukeandBaron/visiondata-gate/contents/.github/ISSUE_TEMPLATE --jq '[.[] | {name,html_url}]'
gh api repos/dukeandBaron/visiondata-gate/pages --jq '{html_url,build_type,source,https_enforced}'
```

若结果变化，更新本页快照与相应证据，不修改旧报告来伪造一致性。官方评分仍由
评委依据实际开放内容及运行证据决定；本页不保证得到 7、8 或 15 分。

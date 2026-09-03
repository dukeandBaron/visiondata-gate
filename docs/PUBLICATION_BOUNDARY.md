# GitHub 与 GitHub Pages 公开边界

## 结论

VisionData Gate 的公开交付采用“私有权威仓 + 干净公共镜像”双仓边界：

- 私有权威仓保留完整开发历史、本地发布回执和未公开材料，不修改为 Public。
- 公共镜像只接收通过当前树扫描、完整历史扫描和 Pages 构建扫描的快照。
- GitHub Pages 只运行 React 的 **PUBLIC_SYNTHETIC_REPLAY** 模式，不连接 Python API、客户系统或模型网关。
- Pages 部署成功不改变比赛、客户、工厂或生产状态。

之所以不直接公开原仓，是因为 Git 提交元数据本身也属于公开内容；即使当前文件不含密钥，旧提交中的个人邮箱或已删除内容仍会随完整历史公开。公共镜像从审核后的当前快照建立新历史，并使用 GitHub noreply 身份提交。

## 公开内容与排除内容

| 类别 | 公共镜像 | GitHub Pages | 边界 |
|---|---|---|---|
| 产品源代码、测试、Schema、Rule Pack、Adapter | 包含 | 只部署编译后的 Web | Apache-2.0；代码存在不等于外部系统已连接 |
| Synthetic-v3 公开回放清单 | 包含 | 包含 | 固定合成分母；浏览器复算 JCS SHA-256 |
| README、架构、API、合规、SBOM 文档 | 包含 | 通过仓库链接查看 | CycloneDX 同时绑定 uv/npm/Cargo 锁；Rust 只覆盖 Windows 目标可达依赖；文档声明不能替代运行回执 |
| 客户/工厂原图、mask、真实类别名、设备帧 | 排除 | 排除 | 不进入 Git、Pages 或公开下载 |
| 本地数据库、Operator Workspace、绝对数据源路径 | 排除 | 排除 | 仅保留在本机 ProductRoot |
| .env.local、API Key、DPAPI 密文、token file | 排除 | 排除 | 公共页面不提供密钥输入 |
| 浏览器私域回执、调试日志、缓存、构建目录 | 排除 | 排除 | 不把开发态回执写成公开证据 |
| 私有仓完整 Git 历史与个人提交元数据 | 排除 | 排除 | 公共镜像使用新历史与 noreply 身份 |

公开二进制采用逐文件语义白名单：`docs/PUBLIC_BINARY_REVIEW.json` 同时绑定路径、大小和 SHA-256。两张候选工作台截图中，只有不含个人显示名的指挥中心截图进入公共镜像；另一张含审批人显示区域的截图保留在私有仓并明确排除。新增或替换任意 PNG/JPG/WEBP/ICO 都必须重新审查，否则公共仓门禁失败。

## Pages 的真实能力

公开工作台不是静态截图。它保留同一套 React 多页面工作台、路由、画布、筛选和血缘交互，并读取一份可下载的冻结 JSON 清单。页面在显示业务事实前执行：

1. 校验 **visiondata-gate.public-replay.v1** Schema；
2. 确认 **read_only=true**、**backend_connected=false**；
3. 确认客户数据、个人数据、工业原图和 API Key 输入均为 false；
4. 用 Web Crypto 复算去除 manifest_sha256 字段后的 RFC 8785 JCS SHA-256；
5. 摘要不一致或清单缺失时失败关闭，不使用页面内嵌数字补位。

公开模式可展示：

- selected / rejected Workers、选择原因、冻结预算和 triggering evidence；
- 竞争假设与缺失证据；
- Intake → Planner → Tool → Council → Judge → Delivery 六阶段；
- Parent → Human Gate (`REQUIRED`) → Derived → Child 血缘；公开清单不证明具名审批已完成；
- **official_submission=PENDING**、**official_evaluation=NOT_EVALUATED**；
- **production_release_allowed=false**。

公开模式不能：

- 创建项目、上传用户文件、保存标注或执行 CAPA；
- 输入、测试或保存 OpenToken、DeepSeek、OpenAI 等 API Key；
- 调用 Hosted AgentTeams、MES、OPC UA、PLC 或设备写回；
- 建立账户、身份、跨用户工作区或生产 IAM；
- 把合成 PASS_LOCAL 描述为客户验收、工厂效果或生产放行。

## 自动门禁

Pages 工作流在部署前依次执行：

1. 完整 Git 历史与当前 tracked tree 隐私扫描，并逐 SHA 核验公开二进制语义白名单；
2. 公开回放清单 SHA-256 与边界校验；
3. Node 锁文件安装、TypeScript 类型检查和静态构建；
4. 对最终 Web 产物再次扫描密钥、个人路径、个人邮箱、私钥、数据库、日志和 source map；
5. 只有全部通过才上传 GitHub Pages artifact。

任何一步失败都会阻止部署。候选 ZIP 的发布扫描与公共仓扫描是两套独立门禁，不能互相替代。

## 本地 BYOK 与公开页面

本地版本仍支持用户自己的 Provider Profile。Key 只经 loopback API 写入本机服务端，在 Windows 上由 DPAPI secret store 保存；工作空间只持有非秘密的 provider_profile_id。环境型模型和 AgentTeams 凭据仍是本地配置责任，不享受“所有 Key 都由 DPAPI 保护”的更强声明。

公共 Pages 构建在编译期关闭 Provider Center，不读取 .env，不向任何模型端点发送探测请求。

## 状态标签

公开仓与 Pages 可使用：

- **PASS_PUBLIC_REPOSITORY_PRIVACY**
- **PASS_PUBLIC_PAGES_PRIVACY**
- **PUBLIC_SYNTHETIC_REPLAY**
- **FROZEN_RC3_BASELINE / PASS_LOCAL_RC3_RELEASE_CANDIDATE**（只绑定冻结 RC3 commit/tree）
- **CURRENT_RC4_DEFENSE_KIT / PASS_LOCAL_RC4_DEFENSE_KIT_INTEGRITY**（仅表示本地附件内容、隐私与字节完整性通过；公共镜像同步和官网提交独立）

不得因此升级为：

- **official_submission=SUBMITTED**
- **official_evaluation=PASS**
- **customer_acceptance=PASS**
- **production_release_allowed=true**

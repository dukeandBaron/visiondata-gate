# GitHub 与 GitHub Pages 公开边界

## 结论

VisionData Gate 以唯一主仓 `dukeandBaron/visiondata-gate` 对外提供源码与 Pages，不再另建公共镜像仓：

- 本地权威工作区保留未公开材料；对外主仓只接收经审查的代码和公共素材。
- 主仓与 Pages 分别执行当前树、可达历史和构建产物扫描。
- GitHub Pages 只运行 React 的 **PUBLIC_SYNTHETIC_REPLAY** 模式，不连接 Python API、客户系统或模型网关。
- Pages 部署成功不改变比赛、客户、工厂或生产状态。

2026-09-15 经所有者明确授权，完整本地备份后，对副本中 69 个提交进行核对，修正 12 个身份邮箱字段；每个提交的文件树及作者/提交者姓名保持不变。父链或身份变化导致失效的 22 个签名块已移除，不宣称原签名仍然有效。可更新分支/标签已同步，当前树及可达历史扫描通过；没有关闭扫描规则。

GitHub 管理的旧 PR 引用、旧 SHA 页面及缓存可能保留旧对象，普通 Git 推送无法保证清除；需要平台进一步处理时应联系 GitHub Support。不得将分支/标签扫描通过描述为平台已彻底擦除历史。`PUBLIC_MIRROR_MANIFEST.json` 是保留的导出/文件身份合同名称，不表示还存在第二个公开仓库。

## 公开内容与排除内容

| 类别 | 唯一对外主仓 | GitHub Pages | 边界 |
|---|---|---|---|
| 产品源代码、测试、Schema、Rule Pack、Adapter | 包含 | 只部署编译后的 Web | Apache-2.0；代码存在不等于外部系统已连接 |
| Synthetic-v3 公开回放清单 | 包含 | 包含 | 固定合成分母；浏览器复算 JCS SHA-256 |
| README、架构、API、合规、SBOM 文档 | 包含 | 通过仓库链接查看 | CycloneDX 同时绑定 uv/npm/Cargo 锁；Rust 只覆盖 Windows 目标可达依赖；文档声明不能替代运行回执 |
| 客户/工厂原图、mask、真实类别名、设备帧 | 排除 | 排除 | 不进入 Git、Pages 或公开下载 |
| 本地数据库、Operator Workspace、绝对数据源路径 | 排除 | 排除 | 仅保留在本机 ProductRoot |
| .env.local、API Key、DPAPI 密文、token file | 排除 | 排除 | 公共页面不提供密钥输入 |
| 浏览器私域回执、调试日志、缓存、构建目录 | 排除 | 排除 | 不把开发态回执写成公开证据 |
| 本地私域材料、未审查历史与个人元数据 | 排除 | 排除 | 只留在本地权威工作区；公开提交使用 GitHub noreply 身份 |

公开二进制采用逐文件语义白名单：`docs/PUBLIC_BINARY_REVIEW.json` 同时绑定路径、大小和 SHA-256。两张候选工作台截图中，只有不含个人显示名的指挥中心截图进入主仓公开面；另一张含审批人显示区域的截图只保留在本地并明确排除。新增或替换任意 PNG/JPG/WEBP/ICO 都必须重新审查，否则主仓门禁失败。

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
- **CURRENT_RC4_DEFENSE_KIT / HOLD_RC4_DEFENSE_KIT**（附件 QA 完成前）

不得因此升级为：

- **official_submission=SUBMITTED**
- **official_evaluation=PASS**
- **customer_acceptance=PASS**
- **production_release_allowed=true**

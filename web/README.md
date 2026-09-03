# VisionData Gate Web

VisionData Gate Web 是项目的新一代多页面工业工作台。它复用同一套证据合同、案件语义和失败关闭边界，不是单张大屏，也不是聊天框套壳。

```text
ui_implementation=PASS_LOCAL_UI
development_state=RC3_FROZEN_LOCAL
release_state=LOCAL_RELEASE_CANDIDATE
release_candidate_ready=true
submission_eligible=false
local_release_decision=PASS_LOCAL_RC3_RELEASE_CANDIDATE
official_submission=PENDING
official_evaluation=NOT_EVALUATED
production_release_allowed=false
```

本地候选状态只在 detached release namespace、匹配的 clean checkout 与声明 toolchain
共同通过本地 verifier 并返回 `PASS_LOCAL_INTEGRITY` 时成立；候选 ZIP 与 Attestation
两个文件本身不足以完成复验。
它不表示官网已提交、官方已评测或生产已获授权。

## 页面地图

| 路由 | 用途 |
|---|---|
| `/` | 数据集与冻结证据入口 |
| `/workspace` | IDE 式真实图片取证、标注与 Agent 协作工作台 |
| `/command-center` | 案件、动态补证、确定性工具与人工门禁总览 |
| `/cases` | 案件账本与 evidence namespace 筛选 |
| `/cases/:caseId` | 三栏案件工作台与结构化 Decision Packet |
| `/evidence` | 视觉证据、测量值、回执与 SHA-256 封装边界 |
| `/capa` | CAPA 候选、具名人工权限和责任项底账 |
| `/lineage` | Parent、Human CAPA、Private Derived、Child 血缘 |
| `/runs` | 阶段事件、Dynamic Leader 和 Tool Receipts |
| `/integrations` | CVAT、FiftyOne、API、Adapter 与模型合同状态；登记本机 allowlist 内的只读来源 |
| `/governance` | 授权历史批次影子评测、治理效果分母、权限矩阵、审计封套与发布门禁 |
| `/review` | 60 秒只读评委路径 |
| `/settings` | 平台能力与桌面封装准备状态 |

## Windows 快速启动

在仓库根目录执行：

```powershell
# 首次安装锁文件固定的依赖，并同时启动本地 API 与 Web
.\run_workbench.ps1 -Install

# 后续一键启动真实工作台
.\run_workbench.ps1

# 前端开发热更新 + 本地 API
.\run_workbench.ps1 -Mode Dev
```

默认工作台地址：生产预览 `http://127.0.0.1:4173/workspace`，开发服务器 `http://127.0.0.1:5173/workspace`。如果只需要前端，可继续单独使用 `run_web.ps1`；API 仍可通过 `run_api.ps1` 单独启动。

`run_web.ps1` 的生产预览使用进程隔离的不可变构建目录；并行执行普通 `npm run build` 不会替换已经被浏览器引用的分块。预览端口采用 strict-port 语义，占用即报错。

仓库根目录的 [`sample_data`](../sample_data/README.md) 提供 3 张清晰图和 3 张质量异常图，可一次性上传体验完整路径；这些文件是固定 seed 合成 fixture，并附 SHA-256 清单。

## 真实图片 Operator Workbench

`/workspace` 是可写的本地操作界面，不是冻结比赛展示页：

- IDE 式 Activity Bar、Explorer、编辑器标签、图片资源列表、画布和 Inspector；
- 点击选择或拖拽批量上传 JPEG、PNG、BMP、TIFF、WebP，单文件最大 32 MiB；
- 支持框选、选择、平移、滚轮缩放、适应窗口、标签修改和删除；
- “剖面探针”或 `Shift + 拖动` 会从当前本地预览计算真实 `I(x)` 光度曲线与 `|∇I|` 梯度曲线；该结果明确标记为 `LOCAL_PREVIEW`，不冒充原始传感器测量；
- 点击字节重复警告可进入双图卷帘或绝对像素差值模式，并显示预览级 `Δmean`、变化像素比例和最大通道差；
- `Ctrl+S` 保存标注，刷新后按 revision 恢复；并用乐观并发避免覆盖另一编辑器的新版本；
- 右侧 `AGENT` 页签会创建不可变 Analysis Run，编排 SHA-256、图像质量、重复账本、标注账本和工单账本 5 个本地工具，并逐条显示 9 个 Activity Trace 事件与各自 Receipt SHA；
- `EVIDENCE COPILOT` 只回答当前 Trace 可核验的重复、质量、标注、工单和权限事实；未接入供应商或维修数据库时明确拒绝推断，问答 turn 独立持久化并绑定 SHA；
- 这里展示的是可审计活动、工具调用、知识命中和结果交付，不展示或伪造模型私有思维链；当前 `model_call_count=0`，不能写成 OpenToken / Gemini 已接入；
- 在已保存的 BBox 上右键可签发真实本地整改工单；后端从源图生成绑定裁剪图，记录图片 SHA、像素坐标与 annotation revision；
- 工单提交前必须具名并勾选“已完成现场专业复核”；前后端都会拒绝绕过。没有人审证明的 legacy 工单只能驳回，不能继续流转；
- `/capa` 顶部的 `LOCAL OPERATOR QUEUE` 会读取真实工单，可执行 `OPEN -> ACKNOWLEDGED -> IN_CAPA` 或具理由驳回，每次操作生成新的只追加 revision；冻结候选方案与生产放行按钮仍不因此解锁；
- 上传时验证真实图片字节、像素上限和格式，非法内容失败关闭；
- 原图、预览、SHA-256 与标注 revision 只写入本机：

```text
output/product/operator_workspace/usr_local_demo/wsp_local_demo/
```

React 页面不会读取 OpenToken Key，Operator API 也不会把原始图片提交给 OpenToken。光度剖面和孪生差值在浏览器中对本地预览计算；工单裁剪由本地 API 从 SHA 绑定的源图生成。当前 `X-Actor-User-Id` 只是本地工作区作用域，不是生产登录认证；面向公网或多人生产部署前仍需接入真实 IAM、TLS、配额、病毒扫描与备份策略。

## macOS / Linux Web 源码运行

当前 Web 核心不含 Windows 绝对路径，可以直接使用同一份源码：

```bash
cd web
npm ci
npm run dev
```

验证生产构建：

```bash
npm run check
npm run preview
```

这代表 Web 源码可移植，不代表 macOS/Linux 桌面安装包已经构建、签名、公证或完成 clean-machine 验证。

## GitHub Pages 公开合成回放

公开构建使用 HashRouter 和仓库相对资源路径，保留多页面导航，但不启动或探测本地 API：

```powershell
$env:VITE_VISIONDATA_PUBLIC_REPLAY = "true"
$env:VISIONDATA_WEB_BASE_PATH = "/visiondata-gate-public/"
npm run build
python ..\tools\check_public_pages.py --dist dist
```

该模式只读取 public-replay.v1.json。浏览器先复算 JCS SHA-256，再显示 selected/rejected Workers、冻结预算、触发证据、竞争假设和 Parent/Human/Child 血缘。清单失败时不使用组件中的旧 fixture 补位。

公开模式不会渲染 Provider Center，不会读取 .env，不会创建账户、项目或工单，也不会发送业务 API 请求。完整隐私和发布边界见[GitHub 与 Pages 公开边界](../docs/PUBLICATION_BOUNDARY.md)。

## 本地 API 与冻结 fallback

没有配置 API 时，页面使用仓库内的冻结、脱敏 fixture，并明确显示 `FROZEN FIXTURE`。需要连接本地服务时，复制 `.env.example` 为 `.env.local`，只填写本地服务地址：

```text
VITE_VISIONDATA_API_BASE_URL=http://127.0.0.1:8787
VITE_VISIONDATA_REVIEWER_BASE_URL=http://127.0.0.1:8765
VITE_VISIONDATA_ACTOR_USER_ID=usr_local_demo
```

`VITE_VISIONDATA_ACTOR_USER_ID` 只是本地原型的作用域选择，不是身份认证或密钥。生产部署仍需服务端 IAM；不得依赖前端变量授予权限。

## 真实数据传输与治理效果

- `/integrations` 的本地来源表单真实调用 `POST /v1/data-sources/local-authorizations`。服务端只接受显式 allowlist 内的绝对目录，进行只读画像并返回路径脱敏回执；前端不会把路径写入公开 evidence。
- `/governance` 只列出当前项目中 `COMPLETED + local_authorized_directory + evidence_sha256` 的任务，并调用 `GET/POST /v1/tasks/{task_id}/industrial-shadow-evaluations`。
- 每份 Shadow Receipt 独立保存误放行、误拦截、整改复验通过和未决整改的分子、分母、分析单元、标签形成方法及两个外部 Manifest SHA；项目级指标按分子/分母加权，不平均百分比。
- 影子回执位于独立评测 namespace，不修改 Agent Task、RuntimeTrace、Evidence ZIP 或冻结 Judge。没有授权历史批次回执时 UI 明确显示 `NOT MEASURED`。

不要在任何 `VITE_*` 变量中填写 OpenToken Key。Vite 会把这些变量编译进浏览器资源；OpenToken Key 只能留在仓库根目录的本机 `.env.local`，由 Python 开发工具读取，React 页面不读取、不持久化也不显示它。

## 验证

```bash
cd web
npm run check
```

多页面只读路径的浏览器验收覆盖 `1440×900`、`1366×768`、`1036×768`、`390×844` 四种视口，以及 12 个路由模式对应的 15 个实际 URL（含 4 个案件 URL）。另外，Operator Workbench 已在 `1600×1000` 下验证真实上传、缩放/适应窗口、框选保存、刷新恢复、重复图片提示、Agent Trace、Copilot 证据回答与拒答、人工复核 Checkbox，以及工单 `OPEN -> ACKNOWLEDGED -> IN_CAPA`。评委页面的批准、执行和生产放行按钮保持禁用；冻结模式不发送 POST、PUT、PATCH 或 DELETE。

## 桌面端边界

当前已经生成本地 Windows 测试构建，不再是 `NOT_BUILT`：

- Windows：PyInstaller FastAPI sidecar smoke 已通过；Tauri release EXE 与 NSIS test installer
  已生成；`cargo check --locked` 退出码 0。三个 EXE 的 Authenticode 均为 `NotSigned`，干净
  Windows 安装/卸载、SmartScreen、升级覆盖和崩溃恢复均为 `NOT_TESTED`；
- macOS：同一 React 源码可复用；universal build、codesign、notarization 尚未执行。
- Linux：同一 React 源码可复用；AppImage/deb、Wayland/X11 兼容矩阵尚未执行。
- 桌面运行时继续使用服务端环境密钥和显式 allowlist，不把 Key 放进 DOM。

桌面端会复用本目录，不再维护第二套 UI。

当前桌面端、签名、clean-machine 与跨平台边界见
[`PROJECT_STATUS.md`](../docs/PROJECT_STATUS.md)。

# VisionData Gate Windows 本地安装包

VisionData Gate 使用 Windows 10/11 x64 的 NSIS 安装包。**核心工作台**内嵌 Python/FastAPI、精简 Java/Spring 网关和 Tauri/React 运行组件，核心功能不要求目标电脑另装 Python、Java、Node.js、npm、Rust、Cargo 或 Maven。WebView2 是桌面运行前提，安装器携带其引导安装程序；引导程序不等于完整离线 WebView2 运行时。

**可选本地视觉训练不是上述零依赖承诺的一部分。**Torch、torchvision、Ultralytics、预训练权重和外部 Python 不随核心安装包分发。需要使用者在模型中心明确登记并授权兼容的外部运行环境；未配置时保持不可执行状态，不自动下载、安装或连接。

## 版本、构建身份与验收

```text
package version = 0.1.0
build identity = UNIQUE_BUILD_ID + SOURCE_MANIFEST + ARTIFACT_SHA256
current build/packaged checks = SEE_THIS_BUILD_DELIVERY_RECEIPT
core target Python/Java/Node/Rust dependency = EMBEDDED
optional vision training dependency = EXTERNAL_PYTHON_TORCH_ULTRALYTICS
code signing = NOT_SIGNED
clean Windows machine validation = HOLD_UNTIL_INDEPENDENT_VALIDATION
same-version upgrade validation = NOT_VERIFIED
production release = NOT_ALLOWED
```

不同 build ID 可使用同一个包版本 0.1.0；build ID 不是语义版本升级。此前安装包通过的测试不自动适用于新包。必须分开核对源码检查、生产构建、安装器生成、从安装器提取后运行、安装后 GUI、干净机和代码签名。全新隔离目录的 PASS 不证明覆盖旧 0.1.0 安装的升级行为已通过；同版本升级未验证前，应保留旧包和业务数据备份。

## 运行架构

```text
Tauri 2 desktop
  -> Spring Boot WebFlux gateway (127.0.0.1, random port)
       -> FastAPI Agent runtime (127.0.0.1, random private port)
            -> SQLite + local immutable artifacts
```

- React/Tauri：桌面界面和两个本地进程的生命周期。
- Spring Boot：本机反向代理、健康聚合和 FastAPI 故障隔离。
- FastAPI：Agent、视觉工具、证据、Case、CAPA 和审计内核。
- Spring Boot 不直接读取 SQLite，也没有生产放行权。

## 安装

1. 获取 `VisionData Gate_0.1.0_x64-setup.exe` 和同目录的 `SHA256SUMS.txt`。
2. 先核对安装器 SHA-256。
3. 双击安装器，按当前 Windows 用户完成安装。
4. 安装后从开始菜单启动 `VisionData Gate`。

PowerShell 校验命令：

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath '.\VisionData Gate_0.1.0_x64-setup.exe'
```

安装包尚未代码签名。Windows SmartScreen 可能显示未知发布者；只有从可信渠道取得且 SHA-256 与清单一致时才应继续。

### 发布版登录注册验收

发布版不启用 DevTools，不能把开放浏览器调试端口作为安装包验收前提。`tools/smoke_desktop_identity_uia.ps1` 要求 **PowerShell 7**，请用 `pwsh` 运行；Windows PowerShell 5.1 不支持该脚本采用的语法，不能作为验收入口。脚本只在隔离验收进程中向 WebView2 注入 `--force-renderer-accessibility`，通过 Windows UI Automation 操作真实 Tauri 窗口；它不会打开 CDP 端口，也不会改变 Agent、账户权限或生产放行边界。

```powershell
pwsh -NoProfile -File tools/smoke_desktop_identity_uia.ps1 `
  -Application '<absolute-path-to-installed-exe>' `
  -WorkRoot '<fresh-isolated-validation-root>'
```

验收覆盖首个管理员创建、错误密码恢复、普通用户注册、管理员批准、成员登录、关闭重启后再次登录和退出。只有完整流程、后端 HMAC readiness、隔离数据库与应用正常关闭都通过时，才写出 `PASS_REAL_DESKTOP_IDENTITY_UIA`。验收仍是当前 Windows 主机上的本地结果，`clean_machine_validation` 保持 `NOT_RUN`。

`tools/smoke_desktop_identity.mjs` 仅保留给明确启用 DevTools 的内部诊断构建，必须显式设置 `VDG_EXPECT_DEVTOOLS_ENABLED=true`；它不是正式发布包的默认验收入口。

## 本地数据位置

```text
数据：%LOCALAPPDATA%\VisionData Gate\product
日志：%LOCALAPPDATA%\VisionData Gate\logs
配置：%APPDATA%\VisionData Gate\.env.local
```

卸载应用不会被当作删除业务数据的授权。需要清理上述数据目录时，应先备份并单独确认。

## 配置模型服务

首次打开先建立本地管理员账号。后续启动登录该账号；其他用户注册后需要审批，工作区权限由实际 owner 分配，或者由 ACTIVE 用户显式创建自己的新工作区。启动 capability 只用于首次初始化和进程生命周期，不能代替用户 Bearer 读取业务数据。

用户可在模型中心管理自己的 Provider Profile。账户密码和模型 API Key 是不同凭据；不能把模型 Key 当作工作台登录密码。

需要环境型模型配置时，首次启动会从安装资源复制 `.env.local` 模板，路径为：

```text
%APPDATA%\VisionData Gate\.env.local
```

不要把密钥写入 React 的 `VITE_*` 变量，也不要把 `.env.local` 发给其他人。桌面端只向 FastAPI 传递当前 Windows 用户的本地配置；Spring Boot 网关不记录密钥值。

## 可选视觉模型：环境、许可与权重

- 安装包提供运行环境登记、审核数据池、数据冻结、训练请求、验证反馈和人审选模接口；没有配置外部 Python/Torch/Ultralytics 时，接口存在不等于可以训练。
- 外部环境须显式登记解释器与摘要，重新配置后重新验证。当前实现为有界 CPU detect；GPU、NPU/CANN、segmentation 训练和 TTT 没有因此获得支持或执行证明。
- Ultralytics 采用 AGPL-3.0 或适用的 Enterprise 许可。商业使用/分发需核对实际许可义务；独立进程不是许可豁免，本项目 Apache-2.0 声明不替代第三方条款。
- `.pt` 登记只记录字节与摘要，不执行文件。加载需可信来源、精确 SHA 和具名风险确认；SHA 只能确认文件身份，不能证明 pickle 或原生代码安全。不得加载未知权重。
- 不自动下载模型。缺陷检测的业务效果、数据质量或生产放行不能由一次训练成功或流程测试推断；最终批准仍由人完成。

## 网络与权限边界

- 两个服务只绑定 `127.0.0.1`。
- 对外界面只访问 Spring Boot 网关；FastAPI 使用独立随机端口。
- 桌面会话使用随机令牌，FastAPI readiness 使用独立 HMAC challenge。
- 网关或 FastAPI 任一不可用时，健康状态为 `HOLD`，HTTP 状态为 503。
- 应用不包含 PLC、相机、配方或生产设备写入权限。

## 从源码构建安装器

在共享 dirty 工作树中，优先使用审核后的独立 staging 构建器，先冻结，再显式传入现有工具链和依赖缓存：

```powershell
.\.venv\Scripts\python.exe tools\build_learning_installer.py freeze `
  --authority . --staging .\output\windows-build-20260913-01
.\.venv\Scripts\python.exe tools\build_learning_installer.py build --help
```

`build` 必须指定现有核心 Python、Node/npm、实际 Cargo（不是 rustup shim）、Cargo 缓存、JDK、Maven/依赖仓库、Web 依赖和 Tauri 缓存。构建器不主动同步环境、重装依赖或覆盖旧产物。Maven、Cargo、npm 使用离线设置；Tauri/NSIS 工具缓存必须另行预置并验证，它们缺失或未被正确定位时可能尝试联网，不能仅凭前三项离线就声称全程离线。操作顺序：

1. 生成逐文件源清单和 SHA-256，明确哪些 dirty/untracked 文件被纳入；
2. 将已安装依赖复制到独立 staging，隔离配置、缓存、日志和分析数据库；
3. 构建并测试 Spring Boot fat JAR；
4. 使用 jlink 生成精简 Java 运行时；
5. 使用 PyInstaller 构建 FastAPI sidecar；
6. 在 PYZ 中核对账号、数据池、视觉反馈及受控学习模块，并与冻结源码比较；
7. 构建 React、Tauri 和 NSIS；从最终安装器提取并独立验证账号/数据/API/重启流程；
8. 输出新安装器、SHA256SUMS 和本次 JSON 回执，不覆盖旧安装器。

Windows 下工具缓存必须与原生 Known Folder 一致，位于隔离 `USERPROFILE/AppData/Local/tauri`；同时将 `LOCALAPPDATA` 指向同一 Local 目录。否则预复制到另一处的 NSIS 缓存可能不会被 Tauri 使用。实际联网或失败记录应保留在本次构建证据中，不能由后续重试成功抹去。

旧 `build_windows_installer.ps1` 会同步依赖、可能下载工具并写入旧输出目录；不能在本轮共享工作树中未经审查直接运行。构建器已排除构建机的 `direct_url.json` 安装来源元数据；保留依赖 METADATA 与许可证，并对实际提取内容再次核验。

生成目录：

```text
output\<本次独立staging>\deliverables\
```

## 交付工件

独立 staging 构建器将以下文件一起放入 `deliverables`，不再只复制 EXE：

- `VisionData Gate_0.1.0_x64-setup.exe`
- `SHA256SUMS.txt`
- `BUILD_MANIFEST.json`
- `SOURCE_MANIFEST.json`
- `DELIVERY_STATUS.json`

`SHA256SUMS.txt` 校验安装器和旁附 JSON，不是样例图片校验表。构建刚完成时，`DELIVERY_STATUS.json` 为 `BUILD_COMPLETE_VALIDATION_PENDING`，安装、GUI、干净机等项目显式为 `NOT_RUN`；不能将该目录当作已验收正式发行。

`BACKEND_SIDECAR_SMOKE.json`、`GATEWAY_SMOKE.json`、`INSTALLER_SMOKE.json` 或该构建实际采用的验证回执，只有真实执行相应检查后才附加，并核对安装器 SHA、执行方式和范围。没有执行时不生成伪造 Smoke 文件，也不继承另一安装包的 PASS。追加回执后需重新生成该交付集合的校验清单。

实际文件名以本次交付清单为准。不要把构建日志、DPAPI 状态、测试数据库、私域图像或含个人路径的内部回执加入可公开下载的包。

这些是本地构建证据，不等于代码签名、客户验收、生产发布或官方平台验证。另一台干净 Windows 电脑完成实装前，状态保持 `CLEAN_MACHINE_VALIDATION=HOLD`。现有 Python/npm/Cargo SBOM 不包含完整 Maven/JRE 物料；完整三层 SBOM 仍是单独 HOLD，不宣称原清单覆盖整个安装包。

失败训练任务的存储与保留范围见 [模型任务存储策略](MODEL_JOB_RETENTION.md)。升级训练执行器后，其源码指纹会改变；已有外部运行环境需要显式重新探测并确认新的指纹，不能为兼容旧记录而关闭身份校验。

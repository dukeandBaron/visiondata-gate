# Windows 候选 `f7f31f7` 构建与验收记录

- 日期：2026-09-16
- 包版本：`0.1.0`
- 构建身份：`windows-local-f7f31f7-finals-20260916`
- 源码提交：`f7f31f7048b14b79990a445f285946f46d3bc41f`
Release：[`windows-local-f7f31f7-finals-20260916`](https://github.com/dukeandBaron/visiondata-gate/releases/tag/windows-local-f7f31f7-finals-20260916)

## 结论

该公开提交已经重新冻结、构建并通过本机提取态、包内学习、实际安装启动、SQLite、发布版 UIA 登录注册和卸载验证。

```text
status=PASS_LOCAL_WINDOWS_CANDIDATE_RELEASE_HOLD
release_status=HOLD_LIMITED_REVIEW_ONLY
code_signed=false
clean_machine_validation=NOT_RUN
same_version_upgrade_validation=NOT_RUN
industrial_performance_verified=false
customer_acceptance=NOT_RUN
production_release_allowed=false
```

它是可下载的限量评审候选，不是生产发行、客户验收或工业模型效果证明。

## 源码与工件身份

| 项目 | 值 |
| --- | --- |
| Source tree | `539fad43bc7074991d516539748bb2f9fa9e08dc` |
| 冻结源码文件 | `355` |
| Source content SHA-256 | `8b7e3ba0a281107016b1e6572901446f4a2ce8314e2440bbdccd12e4ad03fa3c` |
| Source manifest SHA-256 | `0a7266f9290b20a2b9c479f5a4c49a73e72c56edd41597624b8355bc45a5df0f` |
| Build manifest SHA-256 | `6fdc3a2717c77ea9969014a843d515cb6301dff97ab859881c49e5406066bb74` |
| 安装器大小 | `121687638` bytes |
| 安装器 SHA-256 | `e32b10cf7e6ac8a9cdeca06b00973c29ff08acec2ae193fbf80c9d0d9a48e826` |
| 已安装桌面程序 SHA-256 | `ac452815407885f1deb3dc30b1a5863dacd3831601427bbc159a5ab4a3454b2c` |
| 候选 ZIP SHA-256 | `33c5816de9480645cda779161a123b4675c89e5fa19d22f3e0a075382d82b1d1` |

Maven、jlink、PyInstaller 和 Tauri／NSIS 均退出 0。Node 依赖先按最终 `package-lock.json` 在隔离目录执行离线 `npm ci`；React 19.3.0、Vite 8.3.0 等 10 个先前漂移项归零。非 Windows 平台的可选二进制没有伪装为本机缺失依赖。

PyInstaller PYZ 内 26 个运行模块逐项与冻结 staged source 代码对象匹配。Torch、TorchVision、Ultralytics、模型权重和模型 pack 未打包。

## 提取态与包内学习

从同一构建资源启动 Spring WebFlux 与 FastAPI：

```text
status=PASS_EXTRACTED_PLATFORM_HTTP_SMOKE
http_checks=113/113
gateway_headers=113/113
source_fallback=false
restart_persistence=PASS
cross_user_isolation=PASS
receipt_file_sha256=0cfa72f3435a5f7bf42141f9c7b45774fb80e2d868af871a71473a51e3f790ac
```

独立包内参考学习：

```text
status=PASS_PACKAGED_LEARNING
rounds=2
source_fallback=false
receipt_file_sha256=da4764ff83096333e94f122fcbf751e863f6eef666c639b2bfa44fc68e5fd2ca
```

这是 NumPy 合成参考学习合同，不是工业 RL／TTT、模型精度或外部算力证明。

## 实际安装、GUI 与卸载

NSIS 静默安装、应用 readiness 和卸载退出码均为 0；HMAC readiness 为真，SQLite `integrity_check=ok`，卸载后安装目录、注册表项、快捷方式和相关卸载进程均收敛为零。业务数据按产品边界保留，不把卸载视为删除数据授权。

发布版 WebView 保持 DevTools 关闭。使用 PowerShell 7.6.5 与 Windows UI Automation 完成：

1. 创建首个管理员并登录；
2. 错误密码被拒绝且按钮恢复；
3. 普通用户注册为待审批；
4. 管理员批准；
5. 普通用户登录；
6. 正常关闭、重启并再次登录；
7. 退出登录。

```text
installer_smoke=PASS_LOCAL_INSTALLED_SMOKE
installer_smoke_file_sha256=aa76448157643043a3766ee198cd2ee7d0ff361f92fc97a35df54a1d07159612
identity_gui=PASS_REAL_DESKTOP_IDENTITY_UIA
identity_uia_file_sha256=1abc5da8476aab163dc6e111c9c9a67711250566d1b588e421718b341e2caa41
webview_devtools_enabled=false
```

## 全仓回归

同一源码树的连续本地运行：

```text
2094 collected
2070 passed
24 skipped
0 failed
0 errors
17 warnings
3067.57 seconds
```

24 项 skip 为 19 项未随公共仓分发的历史私有发行输入、4 项 Windows 当前用户无 symlink 权限和 1 项外部 YOLO 运行时未授权；不计入 PASS。公开回执 SHA-256 为 `f09d87b94ed622c800b2b8e96a89824854084818b803d867a97c6e0cc2b1db7f`。原始 JUnit 含本机绝对路径，因此未公开，只绑定其原始 SHA。

## 仍未关闭

- 未代码签名，Windows 可能显示未知发布者；
- 未在独立干净机和同版本覆盖升级环境执行；
- 可选训练运行时与权重需要使用者另行登记和授权；
- Operating Point 是源码级已测组件，尚未接入产品 API，也没有生产阈值；
- 工厂误放行／误拦截、客户 ROI、生产 IAM 和完整在线业务后端未验证；
- Agent 不具有设备写入或生产放行权。

[安装说明](WINDOWS_INSTALLER.md) · [完整回归记录](FULL_REGRESSION_F7F31F7_20260916.md) · [版本演进](VERSION_EVOLUTION.md)

# Windows 候选 `ca1fa7b` 构建与验收记录

日期：2026-09-15

包版本：`0.1.0`

构建身份：`windows-local-ca1fa7b-20260915`

源码提交：`ca1fa7b1727535014e8723e5bceb4d539272cf2b`

## 结论

该源码提交已经生成新的 Windows x64 NSIS 候选，并在当前 Windows 主机上完成构建身份、安装器提取、Spring/FastAPI HTTP、两轮 packaged-learning、实际安装启动、SQLite 和发布版登录注册 GUI 验收。

```text
LOCAL_BUILD_AND_SOURCE_BINDING=PASS
EXTRACTED_PLATFORM_POSTVALIDATION=PASS
LOCAL_INSTALL_START_UNINSTALL=PASS
REAL_RELEASE_IDENTITY_UIA=PASS

code_signed=false
clean_machine_validation=NOT_RUN
industrial_performance_verified=false
production_release_allowed=false
```

这是本机候选验证，不是生产发行、客户验收或工业模型效果证明。

同一主仓 prerelease：[`windows-local-ca1fa7b-20260915`](https://github.com/dukeandBaron/visiondata-gate/releases/tag/windows-local-ca1fa7b-20260915)。Release 提供直装 EXE、完整候选 ZIP、Build/Source Manifest、验证摘要/回执和 Release SHA256SUMS；所有附件仍遵守下述 HOLD 边界。

## 构建身份

| 项目 | 值 |
| --- | --- |
| 冻结源码文件 | `350` |
| Source content SHA-256 | `3271a37b7f0bca837c83554c5ea2b0ebf5fdcf62fb859fa82bab35c32b08400d` |
| Source manifest SHA-256 | `c514dd38034cb22069ac7bcc96c0e0abb97a48eaea83fbd7095763633641ceaf` |
| Build manifest SHA-256 | `40b381bfb48088bd77d8912660ce9313784f119998451a714d691083c494b33b` |
| 安装器大小 | `121732575` bytes |
| 安装器 SHA-256 | `09468a0d148017717b2932fc940f17caa378e46fef88ededf582accfea6d05f0` |
| 已安装桌面程序 SHA-256 | `151163f5a5f27509dedefc663286054a8312b254949fc55dbe4065819f12328c` |

Maven、jlink、PyInstaller 和 Tauri/NSIS 四个构建步骤均以退出码 `0` 完成。PyInstaller PYZ 中的 26 个运行模块已经逐个与冻结的 staged source 代码对象比较，结果全部匹配。

## 提取态与包内学习

安装器被安装到新的隔离目录后完成：

- 运行资源与 Build Manifest 重新绑定；
- Spring → FastAPI 真实请求 `120/120` 成功；
- `X-VisionData-Gateway` 网关头验证 `120/120`；
- 两轮 packaged-learning 完成，累计 `72` 次 HTTP 请求；
- 未使用源码服务回退，`source_fallback=false`；
- 卸载完成，安装目录、相关卸载进程、注册表项与快捷方式均收敛为零。

```text
status=PASS_EXTRACTED_PLATFORM_POSTVALIDATION
receipt_sha256=f9e14d2c64019c35804c8ee45c05c4bebed0e82c35bd82ad9dfcbb101d3f816c

packaged_learning_status=PASS_PACKAGED_LEARNING
packaged_learning_receipt_sha256=7154f8d988b125cf8266e79967de19fdbb18c6f7f5b77a1a565b9171d02710d3
```

## 实际安装与启动

同一安装器另行执行实际安装、桌面启动和静默卸载：

```text
status=PASS_LOCAL_INSTALLED_SMOKE
installer_exit_code=0
application_exit_code=0
uninstaller_exit_code=0
desktop_startup_status=READY
gateway=SPRING_BOOT_WEBFLUX
bind_scope=LOOPBACK_ONLY
hmac_readiness_verified=true
sqlite_integrity_check=ok
uninstall_complete=true
```

卸载后业务数据仍保留在该次隔离数据目录；这验证“卸载不等于删除用户数据”的产品边界。

## 发布版登录注册 GUI

正式 Release 构建默认关闭 DevTools。最初的 CDP 验收因此无法连接调试端口，但后端启动回执仍为 `READY`；该失败没有被改写为成功。最终验收改用 Windows UI Automation，只在验收进程传入 `--force-renderer-accessibility`，不打开 DevTools 或 CDP 端口。

同一安装器的真实 Tauri WebView 完成：

1. 创建首个管理员并登录；
2. 错误密码被拒绝，登录按钮恢复可用；
3. 普通用户注册为待审批；
4. 管理员确认批准；
5. 普通用户登录；
6. 正常关闭并重启后再次登录；
7. 退出登录。

```text
status=PASS_REAL_DESKTOP_IDENTITY_UIA
scope=REAL_RELEASE_WEBVIEW_UIA_SPRING_FASTAPI_ISOLATED_DATA
validation_tool_sha256=194f7a17334d7188c11aca16638c7188b5ac7e009aed94ba4ce38cff9ee6a92f
webview_devtools_enabled=false
database_created=true
```

## 内部候选 ZIP

验证摘要、验证回执、构建清单、安装器和包内 SHA256SUMS 已组合为一个不可变内部候选：

```text
archive=VisionData-Gate-ca1fa7b-20260915-internal.zip
archive_bytes=122002168
archive_sha256=1da33346b05306431be206035484d1351ed9bd21493a95ea889972a4bfdc0bd7
member_count=7
status=CREATED_INTERNAL_CANDIDATE_RELEASE_HOLD
```

该 ZIP 仍明确标记 `INTERNAL_ONLY / RELEASE_HOLD`，公开附件只称为“限量评审候选”，不能称为正式生产安装包。GitHub 返回的 7 个附件均为 `uploaded`，远端记录的大小和 SHA-256 与本地清单一致；Release、EXE 与 ZIP 的匿名 HEAD 检查均为 HTTP 200。

## 测试与未关闭门禁

与构建、公开导出、术语和桌面验收相关的扩大回归为：

```text
105 passed
1 skipped  # 当前 Windows 未授予创建符号链接权限
1 warning  # 既有 Starlette TestClient/httpx 弃用提示
```

仍保持：

- `clean_machine_validation=NOT_RUN`；
- `code_signed=false`；
- 同版本覆盖升级未单独验证；
- Torch、Ultralytics、外部权重和视觉训练环境不随核心安装器分发；
- 工厂误放行率、误拦截率和整改后通过率仍等待独立真值裁决；
- 工业模型效果、客户验收和生产放行均未建立；
- `production_release_allowed=false`；
- 完整在线后端工作台尚未部署，静态 Pages 不能替代本地 Python/Java 运行链。

安装方法与安全边界见 [Windows 安装说明](WINDOWS_INSTALLER.md)，版本关系见 [版本演进](VERSION_EVOLUTION.md)。

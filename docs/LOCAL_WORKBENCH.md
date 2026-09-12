# 本地工作台：启动与重新打开

工作台由浏览器、Web 服务和本地 API 组成。这个 Windows 入口让服务独立于发起命令的终端运行，并提供可恢复浏览器会话的 `open` 操作。

## 已有项目

在项目根目录运行：

```powershell
.\start_local_workbench.ps1
```

默认使用 `output/product` 中已有的数据库，Web 端口为 `5173`，API 端口为 `8787`。服务启动并核验通过后，入口会请求浏览器打开工作簿。

关闭标签页后，使用同一个入口重新打开：

```powershell
.\start_local_workbench.ps1 -Action open
```

`open` 会核验已保存的服务身份、端口和会话，再恢复浏览器访问权限。只输入普通网址的新标签页可能没有会话；不要因为页面缺少工作空间而创建替代项目。

检查是否仍在运行：

```powershell
.\start_local_workbench.ps1 -Action status
```

只有 API 和 Web 代理都能证明服务身份，且两端严格身份状态一致时，命令才报告服务 `READY`。首次账户初始化前，还会核对双端启动授权工作区响应；初始化后不再用启动凭证访问业务数据。

`READY` 不表示用户已经登录。输出的 `next_action=INITIALIZE_ACCOUNT` 表示需创建首管理员，`next_action=LOGIN` 表示需在界面登录；初始化后的 `user_authenticated=false` 与 `business_access_verified=false` 会明确保留。启动器不保存用户密码或 Bearer 会话。

## 首次使用

先按 [环境与账户说明](quickstart.md) 安装 Python 与 Web 依赖。创建一个新的独立数据目录需要显式初始化：

```powershell
.\start_local_workbench.ps1 -Initialize -ProductRoot .\output\my_workspace
```

该目录必须为空。已有目录的数据库缺失时，入口会提示错误，不会静默生成一个空工作空间冒充原项目。

## 数据与服务生命周期

源代码与业务数据应保存在长期使用的磁盘目录。避免将需要保留的工作空间放到 Windows Temp 中；临时文件清理可能移除数据库和上传图片。

会话凭据由当前 Windows 用户的 DPAPI 加密，保存在本机应用数据目录，明文不进入命令输出。服务日志与启动状态也保存在本机。原始图片、任务和 CAPA 数据仍保存在指定的 ProductRoot。

关闭发起终端或浏览器标签页不会主动关闭服务。系统重启、进程退出或人为停止服务后，需要重新 `start`。这不是 Windows 服务管理器，也不提供开机自启、进程崩溃自动重启或跨主机调度。

端口被占用时，入口不会终止占用者，也不会向未核验的服务发送会话。若是本入口已经启动的工作台，使用 `status` 和 `open`；若是其他应用，可显式指定空闲端口。

```powershell
.\start_local_workbench.ps1 -ApiPort 8789 -WebPort 5175
```

默认使用开发模式。需要生产资源预览时，可用 `-Mode Preview`，它会先构建当前 Web 代码再启动独立预览目录。这仍是本地工作台，不代表已经完成公网部署。

## 上传重复图片后

1. 在同一个项目中上传两次同一张图片，选择后上传的资产，运行 Agent 取证。
2. 在重复建议旁点击“冻结项目并交给 Agent”，创建项目任务并人工批准执行计划。
3. 项目任务完成后，在“受控 CAPA 案件”查看对应交付，具名选择和批准整改方案。
4. 执行派生版本与 Child Run。完全重复的去重需要字节、标注和上下文一致，并满足原合同覆盖要求。
5. 查看 Child 门禁结论和责任队列；任务执行完成不等于数据通过，数据通过也不代表生产批准。

像素工单用于缺陷框的人工处置。项目级重复问题进入受控 CAPA，不需要为重复资产虚构 BBox。

# VisionData Gate｜复赛答辩运行手册

## 官方时间

```text
日期：2026-09-05
候场：08:56 前
答辩：09:16–09:24
队伍：第 03 队
方向：AI+其他（工业视觉应用）
会议：腾讯会议，以组委会最终通知为准
```

建议内部 08:36 前完成设备、网络和材料自检；这只是项目内缓冲，不是官方时间。

## 材料优先级

1. 新版 PPTX/PDF：`GOAI_VisionDataGate_Semifinal_Defense_RC4_20260902.*`；
2. 公开静态工作台：无后端、无密钥、无客户数据；
3. 本机静态构建：网络不可用时优先；
4. 60 秒备用视频：`VisionDataGate_GOAI_Semifinal_60s_RC4_20260902.mp4`；
5. 六张关键截图与 PDF：视频播放器失败时使用；
6. 89.9 秒 RC3 完整视频：仅供会后核验，不在 1 分钟窗口完整播放。

## T-40 分钟自检

- [ ] 腾讯会议链接、会议号和密码来自最新组委会通知；
- [ ] 摄像头、麦克风、扬声器、屏幕共享和演示者视图可用；
- [ ] PPTX 与 PDF 均能打开，字体和截图无错位；
- [ ] 六个 Demo 标签页按脚本顺序打开；
- [ ] 公网与本机静态页各验证一次 manifest SHA；
- [ ] 60 秒视频可播放且声音正常；
- [ ] 通知、聊天、邮箱、个人目录和密钥窗口全部关闭；
- [ ] 桌面只保留答辩包，不显示本机路径或私域文件名；
- [ ] 计时器单独放在不共享的屏幕；
- [ ] 一名成员主讲，一名成员只负责计时和故障切换。

## 8 分钟控制点

| 时间 | 动作 |
|---:|---|
| 00:00 | 开始 3 分钟陈述 |
| 02:45 | 无论当前页数，准备收束 |
| 03:00 | 切入 Demo，不再补陈述 |
| 03:55 | 停在 `production=false`，结束操作 |
| 04:00 | 进入 Q&A |
| 06:40 | 最后一个问题；回答控制在 20 秒 |
| 07:00 | 停止答题，留给评分与切换 |

## 故障切换

```text
公网异常 > 3 秒
→ 本机静态页
→ 仍异常 > 3 秒
→ 60 秒备用视频
→ 播放器异常
→ PDF / 六张关键截图
```

任何失败都不现场修改代码、不输入 API Key、不启动外部模型、不登录私人账户、不展示私域数据。

## 答辩后必须保存

- 实际答辩时间与是否完整播放 Demo；
- 组委会或平台的正式回执；
- 实际提交文件名与 SHA-256；
- 现场使用的 PPTX/PDF/视频版本；
- 发生的故障与切换路径。

未取得官方回执前继续保持：

```text
current_rc4_defense_kit=PASS_LOCAL_RC4_DEFENSE_KIT_INTEGRITY
public_mirror_rc4_sync=PASS_PUBLIC_RC4_SYNC
public_mirror_source_commit=46a7242f9aa746f9b8f0f78b776d662422d32c72
public_mirror_source_tree=ab27540b18b8d63db6d9db9256fa2b3330f44dfc
public_mirror_head=eb3ef24f7b7df771a4be51a1a3263a060c561db3
current_rc5_document_publication=PENDING
official_submission=PENDING
official_evaluation=NOT_EVALUATED
production_release_allowed=false
```

新版 PPT/PDF、当前公开工作台 57.33 秒视频、公共源码快照、SHA 清单、Defense Kit ZIP 与匹配回执已完成本地包级联检。RC4 公共镜像已有独立 GitHub Actions/Pages 成功回执；当前 RC5 文档尚未发布。官网提交、官方评测和生产放行仍必须读取各自外部回执。

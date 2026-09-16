# 全仓源码回归记录｜9417f01｜2026-09-16

## 裁决

```text
status=PASS_LOCAL_SOURCE_REGRESSION
source_commit=9417f01216925b6912a1f2c9bdc994c9cf1f6ef9
python=3.12.5
collected=2093
passed=2066
skipped=27
failed=0
warnings=17
elapsed_seconds=3422.65
release_attestation=NOT_ISSUED_BY_THIS_RUN
new_windows_installer=NOT_BUILT
production_release_allowed=false
```

这是一次在同一进程、同一项目内锁定 `.venv`、同一源码候选上的连续 Pytest 回归。它不是把多次局部运行相加得到的结果，也不修改旧 Benchmark、私域回执或用户数据。

执行语义（本机解释器与临时目录已规范化为可移植占位符）：

```text
uv run --no-sync python -m pytest -x -q --tb=short \
  --basetemp <LOCAL_TEMP_ROOT>/pytest-main-sync-20260916-09
```

`basetemp` 路径只是本机验证位置，不是可移植输入或公开工件身份。该轮没有生成 Full JUnit，也没有签发 Release Attestation，因此只能标记为本地源码回归 PASS，不能替代正式发行门禁。

## 27 项显式跳过

| 类别 | 数量 | 原因与边界 |
| --- | ---: | --- |
| 未分发的历史私有发行/评审证据 | 22 | RC1/RC3 release、Goal3 私有 evidence、旧 Reviewer Server 快照、旧 website 和视频不进入公开 checkout；完整缺失时明确 skip，发现部分残留时仍 fail |
| Windows 当前用户无法创建符号链接 | 4 | 覆盖数据集、备份、公开快照和修复评估的 symlink 负向测试；当前主机返回 WinError 1314，不写成通过 |
| 外部 YOLO 运行授权未提供 | 1 | 测试要求显式外部 runtime authorization；未授权时保持 skip，不下载权重或制造训练结果 |

私有材料存在的本地权威工作区仍可单独运行相应测试；公开源码回归不会伪造这些输入。27 项 skip 不计入 PASS，也不证明对应外部能力成立。

## 17 条警告

- FastAPI TestClient 对当前 httpx 适配层的弃用提示；
- Starlette `HTTP_422_UNPROCESSABLE_ENTITY` 常量弃用提示。

这些是依赖迁移技术债，不是本轮失败；后续升级必须单独验证 API 状态码、客户端兼容性与锁文件，不能在本轮静默改依赖消除警告。

## 本轮证明与不证明

本轮证明：

- 当前公开源码候选的 2093 项收集集合可连续执行到结束；
- Agent、数据治理、学习生命周期、持久化、发布合同、Web 源码合同和 Windows smoke 合同没有观察到测试失败；
- 缺失私域历史输入时，相关测试有明确边界，而不是制造文件或误记 PASS。

本轮不证明：

- 已重新生成或验收包含该源码的 Windows 安装包；
- 干净机、同版本升级、签名、SmartScreen、macOS/Linux 桌面已通过；
- 外部 YOLO、工厂数据 KPI、客户验收、在线后端或官方平台结果已通过；
- 27 项跳过用例的能力已经被当前公开 checkout 验证。

现有 Windows `ca1fa7b` 候选仍只代表其冻结源码与原始回执。新源码若要成为新的安装包候选，必须重新冻结源 commit、构建、提取态、安装、UIA、卸载、清单和 SHA-256；不得沿用旧安装器 PASS。

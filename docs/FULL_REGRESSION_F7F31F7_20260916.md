# 全仓源码回归记录｜f7f31f7｜2026-09-16

## 裁决

```text
status=PASS_LOCAL_SOURCE_REGRESSION
source_commit=f7f31f7048b14b79990a445f285946f46d3bc41f
source_tree=539fad43bc7074991d516539748bb2f9fa9e08dc
python=3.12.5
collected=2094
passed=2070
skipped=24
failed=0
errors=0
warnings=17
elapsed_seconds=3067.57
production_release_allowed=false
```

这是一次在同一进程、同一公开源码树和锁定 Python 环境中连续执行到结束的 Pytest 回归，不是多次局部结果相加。

```text
python -m pytest -q --tb=short --junitxml=<LOCAL_OUTPUT>
```

原始 JUnit 为 302303 bytes，SHA-256 `32cbf0df8dd789000ece64b239c2a7e29d829c82c998a87b45efe297fc817df1`。它包含本机绝对路径和主机字段，因此不进入公共附件；Release 中的 `FULL_REGRESSION_RECEIPT.json` 只公开计数、源树、原文件摘要和边界。

## 24 项显式跳过

| 类别 | 数量 | 边界 |
| --- | ---: | --- |
| 历史私有 RC1／RC3／旧 Reviewer 输入未分发 | 19 | 完整缺失时明确 skip；相关原断言保留，带档案环境仍可执行 |
| Windows 当前用户无 symlink 权限 | 4 | WinError 1314；不把未执行的符号链接负向测试记作 PASS |
| 外部 YOLO 运行时未授权 | 1 | 不下载依赖、权重或制造训练结果 |

## 17 条警告

- FastAPI／Starlette TestClient 与当前 httpx 适配层的弃用提示；
- `HTTP_422_UNPROCESSABLE_ENTITY` 常量弃用提示。

这些是依赖迁移债务，不是本轮失败；升级依赖需单独验证 API 状态码、客户端与锁文件。

## 能证明与不能证明

能证明：当前公开源树的 Agent、数据治理、CAPA、学习生命周期、持久化、基准、Web、打包与安全合同在该本机环境中未观察到测试失败。

不能证明：24 个 skip 的能力、客户采用、工厂 KPI、代码签名、独立干净机、同版本升级、生产部署或官方赛事结果。Windows 候选另有独立构建和安装回执；源码回归不能替代安装验收，反之亦然。

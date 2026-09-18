# 从公开源码复现一个真实任务

本指南用于第三方部署和现场重跑。在线 Pages 是浏览器图像体验与冻结合成回放；下列命令运行真实本地代码，使用新生成的合成数据，不连接工厂、付费模型或真实设备。

## 准备环境

需要 Git、Python 3.12/3.13、uv；浏览器工作台另需 Node.js 22.12+。在新的工作目录：

```text
git clone https://github.com/dukeandBaron/visiondata-gate.git
cd visiondata-gate
uv sync --locked --extra api --extra qa
```

使用明确提交版本进行复现。固定版本的具体 SHA 在提交清单或 Release 中，不把不断更新的 main 当作已封版对象。

## 1. 改变输入的本地检查与整改复验

```text
uv run --no-sync visiondata-gate demo --output output/demo-input-a --seed 20260915
uv run --no-sync visiondata-gate demo --output output/demo-input-b --seed 20260916
```

两次使用不同 seed 与独立目录，保留新生成的输入与输出。seed 改变数据生成，不等于增加新的任务类型或一份工厂测试；运行状态以本次结果为准。不要覆盖已有目录来制造同一轮成功。

查看两次输入清单、工具结果、Finding、整改记录和新 Run。结果需要分别解释：进程结束、数据 Gate、责任关闭和生产权限不是同一状态。

## 2. 比较动态补证与固定规则

```text
uv run --no-sync python tools/run_dynamic_benchmark_v3.py output/demo-dynamic-v3/report.json
uv run --no-sync python tools/run_dynamic_benchmark_v4.py --output output/demo-dynamic-v4/report.json --v3-report benchmarks/DYNAMICBENCH_V3_REPLANNING_20260829.json --scratch-root output/demo-dynamic-v4/runtime
```

v3 比较同协议编排；v4 经实际 ProductService/Incident 执行合成案件。保留报告里的 case/事件/工具/结果引用，不能从不同案件拼成一条成功链。输出目录要新建；无需加入 `--force`。

ArchBench 的默认 CLI 是较小规模的运行检查，不自动等于历史 ArchBench-v2 的 288 条记录。比较架构时必须固定相同 fixture、重复次数、预算和机器负载，不能将一次并发自测的时延当作正式性能优势。

## 3. 实际浏览器工作台

```text
npm --prefix web ci
uv run --no-sync python tools/run_cross_platform_workbench.py --check
uv run --no-sync python tools/run_cross_platform_workbench.py
```

使用启动器打开的本地会话；首次创建管理员，进入有权限的工作区/项目，导入 `sample_data` 或获准数据。保存人工标注、用途和输入版本后再启动任务。不要把公共网页上的浏览器测量当作已提交后端任务。

操作顺序：导入→复核标注/用途→冻结→检查→查看计划/工具/结果→人工决定→受支持的派生整改→子版本重检。缺少授权或替换数据时保留待处理结果，不修改真实输入强求 PASS。

Windows 快捷入口：`./run_demo.ps1 -Check`，通过后 `./run_demo.ps1`。这是同一真实 API/Web 启动器，不需要旧私域文件。已有工作台运行时不要占用其端口；诊断可使用 `-ApiPort 18787 -WebPort 15173 -NoBrowser -SmokeSeconds 5`，仅检查新启动实例。

### 建议现场分别核验的三件事

- **重复处理**：同一图片以两个身份导入同划分，标注/工况等相同且剩余覆盖足够。查看 EXACT_DUPLICATE → 人工批准 → 派生排除 → Child 重检。父版本保持不变。
- **拒绝不安全处理**：将其中一份改为不同标注或不足覆盖；系统应该阻断自动排除，而不是为了演示出现 PASS。缺陷图重拍、返标和补采需人工提供真实新证据。
- **动态补证**：另行创建 Incident 案件，展示 triggering evidence、selected/rejected workers、预算与 Trace；不要把上传基础 Gate 的固定算子清单当作动态重规划。

模型中心可显示实际登记的 Normality pack、沙箱批准、冻结图像和推理回执。没有自备可信模型/环境时应显示空态和 HOLD。真实 PNG 热图经字节摘要验证后展示，具名反馈保存并回读；选择单次 TTT 时必须另外提供互不重复的正常回放与两类复验图、预算及授权。查看真实步数、参数变化和前后 FP/FN，而不是只看“已完成”。[完整操作与边界](NORMALITY_TTT.md)

## 4. 学习反馈的真实 HTTP 参考流程

```text
uv run --no-sync python tools/run_learning_demo.py --output-root output/learning-live-a
```

先确保 `output` 父目录存在；输出目录必须从未使用。该流程实际运行本地 API 和 NumPy 参考模型，记录两轮数据/权重关联、验证与选择。生成标签与审核角色是明确的模拟输入，不是第三方人工验收，也不是工业训练效果。

## 现场故障与复核

- 保留准确 Run/Case ID、输入身份和本次输出，不使用另一轮日志替代。
- 外部网络失败时，继续展示本地确定性路径；模型调用有无发生以当次记录说明。
- 未知写结果先读取对账，不重复点击训练或整改执行。
- 保留旧输入和失败日志；勿当场删除目录来掩盖失败。
- 如需修改评测条件，记录变更并产生新输出；不要改动冻结 baseline 的结果文件。

本地成功不等于另一台干净机器已验证。第三方独立复现应另记录系统/版本、命令、退出状态及结果摘要，不能由维护者自测替代。

## 开发者全量回归

上面的 `api + qa` 是本地 Web/API 与定向测试环境。仓库完整测试还覆盖旧版 Streamlit UI 和安装构建合同，运行全仓测试前需要额外的 `ui` 和 `desktop` 测试依赖：

```text
uv sync --locked --extra api --extra qa --extra ui --extra desktop
uv run --no-sync python -m pytest -q
```

安装这两个依赖组不表示运行了桌面安装、加载了深度模型或启动了外部服务。部分受平台、真实权重或设备限制的测试可能跳过；请原样记录跳过项与原因。

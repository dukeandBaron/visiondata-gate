# 第三方采用指南：三条有边界的路线

先选择一条路线，记录明确 commit/tree，再依 [许可证](LICENSING.md) 和 [版本策略](VERSIONING.md) 操作。这里的 PASS 仅限所选路线，不等于客户采用、模型达标或生产放行；维护者自测不等于独立第三方记录。

## 路线 A：5 分钟无模型开放复用

5 分钟指依赖准备完成后的示例操作，不承诺首次下载耗时。

**依赖：**Git、Python 3.12/3.13、uv；无需 Node、GPU、Torch、模型 Key、权重或工业数据。

在新的源码目录选择公开来源中要验证的确切提交或 tag，不把移动的 main 当冻结版本：

```text
git clone https://github.com/dukeandBaron/visiondata-gate.git
cd visiondata-gate
git checkout <选定的提交或tag>
git rev-parse HEAD
git rev-parse "HEAD^{tree}"
uv sync --locked --extra qa
uv run --no-sync python -c "from pathlib import Path; Path('output/open-reuse').mkdir(parents=True, exist_ok=True)"
uv run --no-sync python tools/run_open_reuse_smoke.py --output-root output/open-reuse/run-01
uv run --no-sync python examples/reuse/metadata_skill.py --metadata-count 12 --observed-count 14
uv run --no-sync python examples/reuse/metadata_skill.py --metadata-count 12 --observed-count 12
uv run --no-sync python examples/reuse/custom_range_skill.py --mean 230 --lower 64 --upper 192
uv run --no-sync python -m pytest tests/test_open_reuse_smoke.py tests/test_reuse_metadata_example.py tests/test_custom_skill_example.py tests/test_industrial_skills.py -q
```

**产物：**`output/open-reuse/run-01/` 下的 Skill、Rule Pack、Adapter 三个组件回执与聚合 `OPEN_REUSE_RECEIPT.json`，以及 stdout 的自定义 Skill 回执。示例调用真实 SDK，但不读图片、不联网、不写生产设备，也不安装插件。

**PASS：**聚合状态为 `PASS_OPEN_REUSE_SMOKE`，三个组件字节摘要回读一致；两次计数示例 receipt_verified=true、差值分别为 2 和 0；自定义 Skill 明确注册后识别合成异常；相同输入回执稳定，改变输入摘要变化；production_release_allowed=false。维护者 clean-checkout CI 仍不等于独立第三方复现。

**HOLD：**Python 不兼容、lock 漂移、导入失败或回执非法时停止；不随意升级依赖。下一步数据治理可按 [现场复现](LIVE_REPRODUCTION.md) 运行合成 demo 到新目录。

## 路线 B：本地完整工作台

### 源码路径

**依赖：**Python 3.12/3.13、uv、Node.js 22.12+、npm。核心确定性治理不要求外部模型 Key、Torch 或 GPU。

```text
uv sync --locked --extra api --extra qa
npm --prefix web ci
uv run --no-sync python tools/run_cross_platform_workbench.py --check
uv run --no-sync python tools/run_cross_platform_workbench.py
```

**操作／产物：**使用启动器打开的会话→首次具名管理员设置→自有工作区和项目→导入 [6 张合成图片](../sample_data/README.md)→按用途保存标注和划分→冻结并检查。保留本次 Task/Run、Trace、Evidence SHA 及人工处理状态，不拼接不同任务的成功片段。

**PASS：**真实本地 API 返回当前账户、项目和任务的结果；下载字节与记录 SHA 一致；未批准不执行，缺证据保持 HOLD，生产权限始终 false。页面能打开或 health=200 单独不足以证明闭环。

**HOLD：**依赖缺失、端口占用、账户待审批、版本漂移、未知写结果时按 [启动排错](CROSS_PLATFORM_QUICKSTART.md) 和 [API 指南](API_QUICKSTART.md) 处理。不要杀其他服务、关闭认证、删除旧数据或自动重发 POST。

### Windows 安装器路径

按 [Windows 安装说明](WINDOWS_INSTALLER.md) 获取明确 Release/build 的 EXE、SHA256SUMS 和源码清单；不能仅凭重复使用的 0.1.0 版本号判断功能。核心运行组件内嵌，但 WebView2 是前提；其引导程序不是完整离线运行时。

**产物／PASS：**核对 EXE SHA 与 build ID，记录安装后实际登录、工作区和工作簿结果。安装器未包含的新源码能力保持 NOT_RUN。当前机器成功不等于独立干净机、同版本升级或代码签名通过。

**HOLD：**来源／摘要不符、WebView2 缺失或当前包没有所需能力时停止。保留旧包和业务数据；卸载不代表授权删除数据库。

## 路线 C：BYOM Normality

BYOM 表示用户自行准备合法可信的模型、运行环境和证据，不是项目附赠权重。先完成路线 B，再按 [模型 API](VISION_MODEL_API_CONTRACT.md) 与 [Normality TTT](NORMALITY_TTT.md) 操作。

**依赖：**兼容外部 Python、Torch/Torchvision/Ultralytics、合法 YOLO26 v2 Normality pack、来源／稳定性证据和获准图像。外部模型 Python 版本与核心应用 Python 分开核验；许可、模型包、backbone、runtime 和实现摘要分别绑定。

**命令／入口：**已有受审查 Torch CPU 环境可先检查合成机制：

```text
python tools/run_normality_ttt_synthetic.py
python -m pytest tests/test_normality_ttt.py tests/test_normality_inference.py -q
```

然后在模型中心：登记环境→明确导入探测→登记 pack→具名沙箱批准→冻结图像→一次普通推理。TTT 另需 capabilities、query/adaptation、正常 replay、正常／异常 guard、预算与全部授权。

**产物／PASS：**身份一致的推理回执、经字节校验的 PNG、具名反馈 POST 后 GET 回读；TTT 记录实际步数、参数、更新前／最终更新后目标与 guard。ACCEPTED_EPISODIC、ROLLED_BACK、FAILED_CLOSED 必须分开解释，安全拒绝不冒充模型收益。

**HOLD／无权重 fallback：**没有兼容环境、合法权重或正确证据时模型页保持空态／不可执行，不自动下载、不编造预训练结果；继续使用路线 A/B 的确定性治理。无 Torch 的 tensor skip 是 NOT_RUN，不是模型 PASS。人工框和维护者集成测试区域不等于独立缺陷真值。

## 留下可复核证据

按 [第三方复现记录](THIRD_PARTY_REPRODUCTION.md) 保存 exact commands、版本、退出状态、产物 SHA 和未运行项。维护者 CI、同机提取态、新目录、独立第三方和独立干净机是不同证据。原始日志默认私有；公开前单独脱敏与授权，不提前填写 PASS。

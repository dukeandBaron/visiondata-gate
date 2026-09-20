# 复用一个实际工业 Skill

## 一次检查三个公开复用组件

先按仓库的[源码环境指引](../../docs/CROSS_PLATFORM_QUICKSTART.md)准备锁定依赖。
下面的工具不会安装依赖、启动子进程、访问网络、调用模型或读取私域数据。
它真实调用本页的 `run_example()`、Rule Pack 的 `verify_rule_pack()` 和
Adapter 的 `verify_adapter_conformance()`，使用仓库已有的公开合成输入。

```text
uv run --no-sync python -c "from pathlib import Path; Path('output').mkdir(exist_ok=True)"
uv run --no-sync python tools/run_open_reuse_smoke.py --output-root output/open-reuse-fresh-001
```

父目录必须已存在；`output-root` 必须是新的非根目录。已有目录、文件以及链接/重解析
路径均拒绝，UNC 网络路径在文件探测之前拒绝，工具不会覆盖旧回执。成功时生成：

| 文件 | 内容 |
| --- | --- |
| `skill.json` | 实际计数 Skill 调用、绑定的输入/输出与已验证回执 |
| `rulepack.json` | 5 条规则、3 个动态触发的规则包验证回执 |
| `adapter.json` | 7 项离线 conformance 检查与原始组件回执摘要 |
| `OPEN_REUSE_RECEIPT.json` | 三文件实际字节摘要、长度、公开输入摘要与聚合 JCS/SHA 回执 |

成功状态为 `PASS_OPEN_REUSE_SMOKE`。它明确保留：

```text
execution_scope=MAINTAINER_OR_USER_LOCAL_SYNTHETIC_OPEN_REUSE
evidence_scope=MAINTAINER_CI_CLEAN_CHECKOUT_NOT_THIRD_PARTY_ADOPTION
third_party_reproduction_status=THIRD_PARTY_REPRODUCTION_PENDING
actual_model_call_count=0
network_call_count=0
production_release_allowed=false
```

`evidence_scope` 是证据类别，不代表本次实际运行在 CI；工具不自行提供 CI 运行证明。
本机或维护者 CI 通过都不等于第三方采用、工厂效果或完整 TTT/产品链路通过。
同一公开输入在两个新目录中的四份 JSON 字节完全相同，不写入时间、绝对路径或用户名。
聚合摘要是对去掉 `receipt_sha256` 字段后的 JCS 字节计算 SHA-256；它不是身份签名或
独立第三方证明。组件内部原有摘要协议保持不变。

可对已保存结果进行只读复核：

```python
from pathlib import Path
from tools.run_open_reuse_smoke import verify_receipt

receipt = verify_receipt(Path("output/open-reuse-fresh-001"))
print(receipt["status"])
```

组件失败、输入变化、回执篡改或写入后字节不一致时，工具返回 `HOLD`/非零退出码，
不会发布新的聚合 PASS。失败目录可能保留部分组件材料；不会自动删除或覆盖它，
再次执行需显式选择另一个新目录。

## 单独调用计数 Skill

该示例调用项目已有的版本固定 SDK，比较两个输入计数、输出差异并验证回执；不需要模型、网络或工业数据。

```text
uv run --no-sync python examples/reuse/metadata_skill.py --metadata-count 12 --observed-count 14
uv run --no-sync python examples/reuse/metadata_skill.py --metadata-count 12 --observed-count 12
```

第一组产生差值 2，第二组差值 0。数值来自显式合成输入，展示的是 SDK 调用与结果绑定，不是图像识别或工厂误差测量。代码不会安装依赖、读取图片或执行生产动作。

扩展方法：实现受审查的 Skill 类，声明输入、输出、权限和版本，显式注册，再调用固定版本。Markdown Skill 说明与可执行 Python 插件不同；注册器不是任意代码安全沙箱。

## 编写并注册一个完整自定义 Skill

[custom_range_skill.py](custom_range_skill.py) 展示完整第三方实现，不修改核心 SDK：

- 继承 `BaseIndustrialSkill`；
- 声明固定 ID、版本、算法、依赖、输入和冻结参数；
- 由受信 host 构造 `IndustrialMeasurement` 与 evidence span；
- 显式实例化并注册精确版本，不扫描插件目录、不动态 import；
- 返回严格 `IndustrialSkillOutcome`，再由 Registry 封装并验证回执。

```text
uv run --no-sync python examples/reuse/custom_range_skill.py --mean 128 --lower 64 --upper 192
uv run --no-sync python examples/reuse/custom_range_skill.py --mean 230 --lower 64 --upper 192
uv run --no-sync python examples/reuse/custom_range_skill.py --omit-measurement
```

前两条分别得到区间内与高曝光异常的已验证回执；缺少必需测量时第三条返回 `DEFER` 和非零退出码。边界值只是合成示例，不是工厂曝光标定。自定义 Python 代码仍需审查；显式 Registry 不是恶意代码 OS 沙箱。

重复输入会产生相同回执；内容变化会改变输入和回执摘要。接入真实测量时，受信 host 应先完成来源授权和测量，再构造路径无关的 `IndustrialSkillInvocation`；不能把这里的合成计数当作授权凭据。

```text
uv run --no-sync pytest -q tests/test_open_reuse_smoke.py tests/test_reuse_metadata_example.py tests/test_custom_skill_example.py tests/test_reuse_contracts.py tests/test_industrial_skills.py
```

[核心代码地图](../../src/visiondata_gate/README.md) · [文本 Skill 目录](../../skills/README.md) · [SDK 文档](../../docs/INDUSTRIAL_SKILL_SDK.md) · [版本兼容](../../docs/VERSIONING.md) · [许可证](../../docs/LICENSING.md)

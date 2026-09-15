# 复用一个实际工业 Skill

该示例调用项目已有的版本固定 SDK，比较两个输入计数、输出差异并验证回执；不需要模型、网络或工业数据。

```text
uv run --no-sync python examples/reuse/metadata_skill.py --metadata-count 12 --observed-count 14
uv run --no-sync python examples/reuse/metadata_skill.py --metadata-count 12 --observed-count 12
```

第一组产生差值 2，第二组差值 0。数值来自显式合成输入，展示的是 SDK 调用与结果绑定，不是图像识别或工厂误差测量。代码不会安装依赖、读取图片或执行生产动作。

扩展方法：实现受审查的 Skill 类，声明输入、输出、权限和版本，显式注册，再调用固定版本。Markdown Skill 说明与可执行 Python 插件不同；注册器不是任意代码安全沙箱。

[SDK 文档](../../docs/INDUSTRIAL_SKILL_SDK.md) · [开发来源与依赖](../../docs/DEVELOPMENT_PROVENANCE.md)

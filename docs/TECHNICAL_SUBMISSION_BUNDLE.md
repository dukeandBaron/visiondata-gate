# 可复现的技术提交包

本流程只打包源码、依赖锁、文档、公开示例与显式选入的文字回执，不依赖 PPT 是否定稿。它不是安装器构建器，也不会宣称已经在赛事官网提交。

## 构建与验证

在已经审查并提交的干净候选仓库中运行：

```text
python tools/build_finals_technical_bundle.py build --repo . --output ../VisionData-Gate-Technical.zip
python tools/build_finals_technical_bundle.py verify ../VisionData-Gate-Technical.zip
```

默认只导出 HEAD 中经过路径过滤的受 Git 管理文件，不包含 `.git`、环境、运行数据库、日志、模型权重下载、视频、PPT、安装器和私有 output。未跟踪文件不会被偷偷加入。默认拒绝已跟踪源码的未提交修改；必要时显式 `--allow-dirty`，产物标记 `PATCHED_WORKTREE`，不冒充某个提交的精确内容。

构包应在操作者已审查、Git 配置可信的本地仓库运行，不是执行不可信 Git 配置的沙箱。Git 只从仓库之外的绝对 PATH 目录解析；拒绝当前目录、相对 PATH 或输入仓库中的同名程序，不使用 shell，关闭 fsmonitor，并限制每次 Git 调用为 60 秒。外部 PATH 目录及 Git 配置仍属于操作者负责的可信工具链。

外部回执必须逐个选入，不能传整个材料目录：

```text
python tools/build_finals_technical_bundle.py build --repo . --output ../VisionData-Gate-Technical-With-Evidence.zip --evidence demo.json=output/public-reviewed/demo.json --public-evidence-reviewed
```

该声明意味着操作者已经检查公开权限、隐私和结果口径。工具拒绝常见秘密、用户主目录、二进制和无效 JSON，但自动扫描不是完整隐私审查；也不批准再分发第三方数据。原始 JUnit 可能包含用户名/路径，不能直接选入，先制作经核实的无个人信息摘要。

## 包内结构

```text
START_HERE.md             独立入口，不复制一份会断链的 README
SOURCE_IDENTITY.json      提交、内容摘要、过滤范围、各交付状态
BUNDLE_MANIFEST.json      精确文件清单、大小、SHA-256 与整体清单摘要
source/                  保留仓库相对目录，README 和文档链接正常解析
evidence/                可选的公开文字回执
```

同一提交与相同回执在相同构建工具链中产生相同 ZIP。文件时间固定，文件顺序稳定，拒绝覆盖已有输出。源码内容摘要与 ZIP 字节摘要分别记录。

## 解压与验收

先在解压前校验 ZIP，并把输出 SHA 与独立发布渠道提供的 SHA 比较：

```text
python tools/build_finals_technical_bundle.py verify ../VisionData-Gate-Technical.zip --expected-sha256 <独立保存的64位摘要>
python tools/build_finals_technical_bundle.py verify ../fresh-extracted-bundle
```

核验器拒绝文件修改、缺失、额外文件、重复/大小写冲突、路径穿越、Windows 非法路径及符号链接。摘要只能发现相对于给定清单的变化，不是数字签名；没有独立可信摘要时不能抵御整包连同清单被一起替换。

核验后进入 `source/`，按 [现场复现](LIVE_REPRODUCTION.md) 改变输入重跑。复现产生文件后整个解压目录不再是原始包，应该保留一份未运行的原始解压件用于完整性核验。

成功只输出 `INTEGRITY_VERIFIED`；能力验证明确为 `NOT_RUN_BY_BUNDLER`。源码测试、安装验收、公开部署、业务效果与官网提交必须分别出具回执。

# 独立第三方复现记录：空模板，不是成功证明

按 [采用指南](ADOPTION_GUIDE.md) 选择 SDK、工作台或 BYOM 的明确范围。**maintainer CI 不等于第三方**；同一维护者新建目录不自动成为独立第三方或干净机验证。仓库公开、模板提交、下载和 Star/Fork 都不等于部署成功记录。

默认状态为 NOT_RUN。仅在实际执行后填写；这个文档模板不是新的运行时 Schema 或法律认证。不要提交密码、Bearer、startup capability、API Key、私域绝对路径、客户身份、原图或未授权权重。

## 可复制记录

```json
{
  "record_type": "third_party_reproduction_template",
  "status": "NOT_RUN",
  "scope": null,
  "commit": null,
  "tree": null,
  "source_acquisition": {
    "public_repository_or_release_url": null,
    "archive_or_installer_sha256": null,
    "build_id": null,
    "working_tree_clean": null
  },
  "os": {"name": null, "version": null, "architecture": null, "clean_machine": null},
  "versions": {"python": null, "uv": null, "node": null, "npm": null, "optional_model_runtime": null},
  "exact_commands": [],
  "artifacts": [],
  "observations": [],
  "not_run": ["installer_acceptance", "independent_clean_machine", "real_model_inference", "industrial_effectiveness", "production_release"],
  "independence": {
    "is_independent_third_party": null,
    "relationship_to_maintainers": null,
    "maintainer_assistance": [],
    "reporter_statement": null
  },
  "privacy": {
    "reviewed_for_publication": false,
    "customer_data_included": null,
    "secrets_removed": null,
    "private_machine_paths_redacted": null,
    "raw_logs_kept_private": true,
    "publication_authorized_by_reporter": false
  }
}
```

## 填写依据

- **commit/tree：**记录 git rev-parse HEAD 和 git rev-parse "HEAD^{tree}" 的实际结果。ZIP 用户记录包身份和实测 SHA，不把维护者提供的字符串当作自己已验证的 Git 身份。
- **OS/versions：**实际系统、架构、Python/uv；工作台路径加 Node/npm；BYOM 加外部 Python/Torch/Torchvision/Ultralytics 与合法模型身份。未使用项明确写 NOT_RUN／不适用。
- **exact_commands：**每条记录原样命令、相对工作目录、开始／结束时间、退出码、stdout/stderr 私有保存位置与 SHA-256。公开时把私有路径换成解释清楚的占位符，移除实际凭据并声明已脱敏。
- **artifacts：**记录真实文件的相对名、字节数、实算 SHA-256、用途、来源命令与公开许可。ZIP 和解压清单分别核验；完整性不代替运行验证。
- **observations：**记录本次 Task/Run/Case、执行状态与 Gate、下载摘要验证和失败恢复。不要拼接不同任务；公开 ID 可作稳定脱敏映射。
- **not_run：**保留未运行项。未做 GUI、安装、干净机、覆盖升级、GPU/NPU 或真实模型时不要借用别人的 PASS。
- **independence：**声明与维护者关系、是否由维护者代操作、得到哪些调试协助；接受协助可以如实披露，但不能隐藏后仍称完全独立。
- **privacy：**发布前另行复核；不确定项不能直接改为 true。原始日志和客户数据保持在复现者受控范围。

## 何时能改为 PASS

所选范围的公开步骤实际完成、产物可校验、版本一致且无未解释矛盾后，复现者才可记录该范围 PASS。依赖或授权不满足写 HOLD；命令失败保留退出码和阶段，不删除失败再借另一次成功。

SDK／合成任务 PASS 不证明真实模型；模型运行 PASS 不证明精度提升；本机安装 PASS 不证明独立干净机或同版本升级。建议同时记录正常结果与适用的安全拒绝／HOLD 分支。

最小提交材料是：路线与版本身份、环境和完整命令、退出状态、本次产物 SHA、未运行项、独立性声明、公开隐私审查。通过仓库复现 Issue 模板提交脱敏记录，不等于维护者验收或赛事官方认可；应分别保留第三方陈述、维护者复核和未核实层级。

[API 首次真实任务](API_QUICKSTART.md) · [版本策略](VERSIONING.md) · [许可证](LICENSING.md) · [公开边界](PUBLICATION_BOUNDARY.md)

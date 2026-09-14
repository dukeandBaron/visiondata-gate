# RC3 Release Attestation v1

## 结论与边界

`Release Attestation v1` 是候选发布包外部的、可重复生成的完整性证明。它采用 in-toto
Statement v1 的外形，把候选 ZIP、Git 源状态、依赖锁、SBOM、全量测试回执、干净解压回执、
第二次构包结果以及构建身份放进同一个 RFC 8785 JCS Statement。

该协议当前**没有数字签名、可信时间戳或外部锚定**：

```text
signature             NOT_CONFIGURED
trusted_timestamp     NOT_CONFIGURED
external_anchor       NOT_CONFIGURED
submission_eligible   false
official_status       NOT_EVALUATED
```

因此，本地验证通过只能写作 `PASS_LOCAL_INTEGRITY`，不能写作“已签名”“官方已提交”“官方已
验收”或“可直接放行”。当前开发工作树如果是 dirty，构建器会按设计返回 `FAIL`；不得为了生成
漂亮回执绕过该门禁。

## 1. 绑定范围

Statement 的唯一 subject 是第一次构建的候选 ZIP。predicate 固定绑定：

1. `git rev-parse HEAD`；
2. `git rev-parse HEAD^{tree}`；
3. `git status --porcelain=v1 -z --untracked-files=all` 必须为空；
4. Git index 不得存在 `skip-worktree` 或 `assume-unchanged` 隐藏标记；
5. 仓库根目录的 `uv.lock`；
6. `docs/SBOM.cdx.json`；
7. `visiondata-gate.full-test-receipt.v2`，以及其绑定的 JUnit XML 路径、字节数与 SHA-256；
8. `visiondata-gate.clean-extract-receipt.v1` 及其排序后的 required-path 分母；
9. 两份 `visiondata-gate.release-build-receipt.v1`；
10. 两个声明的构建 invocation、相互隔离的 workspace 路径、不同 ZIP 路径和不同底层文件对象；
11. 两个 ZIP 的字节数及原始 SHA-256 必须相同；
12. builder ID，以及现场探测并严格对账的 `git`、`python`、`uv`、`visiondata-gate` 四项工具版本。

所有路径写成项目根目录内的规范 POSIX 相对路径。绝对路径、盘符、反斜杠、`..`、符号链接、
目录联接、缺失文件、空文件和项目根目录逃逸全部失败关闭。

## 2. 摘要协议

候选 ZIP、第二次构包和四项材料采用原始文件字节的标准 SHA-256。完整 Statement 使用以下固定
帧再做 SHA-256：

```text
UTF8("visiondata-gate.release-attestation-frame.v1") || 0x00
|| uint16be(domain_length)
|| UTF8("visiondata-gate/release-attestation/statement/v1")
|| uint64be(jcs_statement_length)
|| RFC8785_JCS(statement)
```

域分离摘要用于避免同一字节串在不同协议角色间被误用；长度前缀使帧边界无歧义。实现只调用
标准 SHA-256 和项目已锁定的 `rfc8785` 库，没有自制加密算法，也没有把摘要包装成数字签名。

Attestation 文件自身必须是无 BOM、无尾换行的精确 RFC 8785 JCS 字节。验证器拒绝重复 JSON
键、非有限数、未知字段、宽松格式和自摘要漂移。

## 3. 必需回执合同

### 3.1 全量测试回执

逻辑结构如下。实际文件必须输出为 RFC 8785 JCS，而不是下方用于阅读的缩进格式。

```json
{
  "schema_version": "visiondata-gate.full-test-receipt.v2",
  "status": "PASS",
  "scope": "FULL_REPOSITORY",
  "source": {
    "commit": "<git-commit>",
    "tree": "<git-tree>",
    "dirty": false
  },
  "inputs": {
    "uv_lock_sha256": "<64-lowercase-hex>",
    "sbom_sha256": "<64-lowercase-hex>"
  },
  "junit": {
    "path": "deliverables/rc3/<release-id>/full-test.junit.xml",
    "digest": {"sha256": "<64-lowercase-hex>"},
    "size_bytes": 1
  },
  "result": {
    "command_argv": [
      "uv", "run", "--frozen", "python", "-m", "pytest", "-q",
      "--junitxml=deliverables/rc3/<release-id>/full-test.junit.xml"
    ],
    "cwd": ".",
    "pytest_addopts": "",
    "exit_code": 0,
    "passed": 1,
    "failed": 0,
    "errors": 0,
    "skipped": 0,
    "warnings": 0
  },
  "claim_boundary": "LOCAL_FULL_REGRESSION_RESULT_NOT_EXTERNAL_CERTIFICATION"
}
```

`passed` 必须至少为 1；`failed`、`errors` 和退出码必须为 0。命令数组必须逐项等于无过滤的
全仓命令，并且只能追加一个与 `junit.path` 完全一致的 `--junitxml` 输出参数；不允许追加单测
文件、`-k`、marker 或其他过滤。`cwd` 必须是仓库根目录 `.`，`PYTEST_ADDOPTS` 的合同值必须
为空。回执中的 Git、lock、SBOM 和 JUnit 摘要必须与构建现场完全一致；构建和复验都会重新读取
JUnit 并核验大小与 SHA-256。Attestation 通过 full-test receipt 的材料摘要间接绑定 JUnit，
verification summary 同时重复绑定 `junit_sha256`，防止摘要字段漂移。验证器不会重放测试命令，
因此该证据仍属于本地自声明，而不是第三方认证。

`full-test-receipt.v1` 没有绑定 JUnit 物理文件，现只作为历史开发合同保留，不得用于 RC3 候选
Attestation。

### 3.2 干净解压回执

```json
{
  "schema_version": "visiondata-gate.clean-extract-receipt.v1",
  "status": "PASS",
  "source": {
    "commit": "<git-commit>",
    "tree": "<git-tree>",
    "dirty": false
  },
  "candidate": {
    "path": "deliverables/<candidate>.zip",
    "digest": {"sha256": "<64-lowercase-hex>"},
    "size_bytes": 1
  },
  "required_paths": ["<DEFAULT_SUBMISSION_REQUIRED_PATHS 的完整排序清单>"],
  "audit_tool": {
    "implementation": "visiondata_gate.package.audit_submission_zip",
    "manifest_schema": "visiondata-gate.submission-manifest.v1"
  },
  "audit": {
    "ok": true,
    "clean_extract_verified": true,
    "required_paths_verified": true,
    "credential_scan_passed": true,
    "private_path_scan_passed": true,
    "entry_count": 1,
    "verified_file_count": 1,
    "issue_count": 0
  },
  "claim_boundary": "LOCAL_CLEAN_EXTRACT_AUDIT_NOT_EXTERNAL_CERTIFICATION"
}
```

该回执必须绑定第一次候选 ZIP 的相对路径、字节数、SHA-256 和完整 required-path 分母。v1
把该分母冻结为 Git 绑定源码中 `package.DEFAULT_SUBMISSION_REQUIRED_PATHS` 的完整排序清单；回执
不能自行删减。构建 Attestation 和独立验证时都会重新调用项目现有的
`audit_submission_zip`，现场检查 manifest、凭据、危险路径、固定 ZIP 元数据、required paths
和干净解压重哈希；回执中的计数必须与现场结果一致。任一布尔门不是 `true`、`issue_count`
不是 0、分母缩减，或现场重审计失败，均不能通过。

### 3.3 两次构建回执

两次构建各自需要一份精确 JCS 回执。二者必须使用不同 invocation ID、不同且 clean 的
workspace；输出 ZIP 必须位于各自 workspace 内。`command_argv` 必须从 `uv run --frozen
python tools/<tracked-builder>.py` 开始，并逐字绑定 `--workspace` 与 `--output`。构建入口必须是
当前 Git tree 中的受跟踪文件。

```json
{
  "schema_version": "visiondata-gate.release-build-receipt.v1",
  "status": "PASS",
  "source": {
    "commit": "<git-commit>",
    "tree": "<git-tree>",
    "dirty": false
  },
  "inputs": {
    "uv_lock_sha256": "<64-lowercase-hex>",
    "sbom_sha256": "<64-lowercase-hex>"
  },
  "invocation_id": "rc3/build-1",
  "workspace": "deliverables/build-1",
  "clean_workspace": true,
  "command_argv": [
    "uv", "run", "--frozen", "python", "tools/<tracked-builder>.py",
    "--workspace", "deliverables/build-1",
    "--output", "deliverables/build-1/VisionData_Gate_RC3.zip"
  ],
  "output": {
    "path": "deliverables/build-1/VisionData_Gate_RC3.zip",
    "digest": {"sha256": "<64-lowercase-hex>"},
    "size_bytes": 1
  },
  "builder": {
    "builder_id": "local://visiondata-gate/release-builder",
    "toolchain": {
      "git": "<observed-version>",
      "python": "<observed-version>",
      "uv": "<observed-version>",
      "visiondata-gate": "<observed-version>"
    },
    "identity_assurance": "REQUIRED_VERSIONS_LOCALLY_PROBED_IDENTITY_NOT_AUTHENTICATED"
  },
  "claim_boundary": "LOCAL_BUILD_INVOCATION_RECEIPT_NOT_AUTHENTICATED_BY_EXTERNAL_BUILDER"
}
```

这两份回执只证明“两份声明的输出及其回执在当前验证时相互一致”，验证器不会重放
`command_argv`，也无法独立证明两次 invocation 实际发生。协调伪造的两份本地回执仍可能通过；
因此结论必须写作 `TWO_DECLARED_OUTPUTS_BYTE_IDENTICAL`，不能写作“已证明可复现构建”，builder
身份也未由第三方或远程可信构建服务认证。

## 4. 一键证据流水线

功能和材料冻结并形成 clean commit 后，使用新的执行器生成全量 JUnit、测试回执、两个隔离
输出 workspace、clean-extract 回执、两份 build receipt 和最终 unsigned Attestation：

```powershell
uv run --frozen python tools\build_rc3_release_evidence.py `
  --project-root . `
  --release-id vdg-rc3-final `
  --output-root deliverables\rc3\vdg-rc3-final
```

执行器在任何输出产生前检查 Git clean，并要求输出 namespace 已被 `.gitignore` 覆盖且此前不
存在。任何失败都会保留诊断文件、拒绝复用 namespace，并且不会生成 PASS Attestation。

每个 build workspace 内的 `source-tree.zip` 只是 `git archive HEAD` 生成的内部构建输入，
不是 Attestation subject、不是第二份候选，也不得上传给评委。上传白名单中的工程包只认
`build-1/VisionData_Gate_RC3.zip`；`build-2` 仅用于字节一致性核验。独立 verifier 还需要
release namespace 中的四份 receipt、Full JUnit、第二份 ZIP，以及当前 clean Git tree、
`uv.lock` 和 SBOM；“候选 ZIP + Attestation”两个文件不是自包含证明集。

## 5. 手工 Attestation 构建命令

建议把两个候选包、四份回执、Full JUnit 和最终 Attestation 放在已由 `.gitignore` 明确排除的
`deliverables/` 内；它们仍必须位于项目根目录之下。

```powershell
uv run --frozen python tools\build_release_attestation.py `
  --project-root . `
  --release-id vdg-rc3-final `
  --candidate-zip deliverables\VisionData_Gate_RC3_build1.zip `
  --second-build-zip deliverables\VisionData_Gate_RC3_build2.zip `
  --full-test-receipt deliverables\full-test.receipt.json `
  --clean-extract-receipt deliverables\clean-extract.receipt.json `
  --build-one-receipt deliverables\build-1.receipt.json `
  --build-two-receipt deliverables\build-2.receipt.json `
  --builder-id local://visiondata-gate/release-builder `
  --toolchain git=2.x `
  --toolchain python=3.12.x `
  --toolchain uv=0.x `
  --toolchain visiondata-gate=0.1.0 `
  --output deliverables\VisionData_Gate_RC3.attestation.json
```

工具版本必须替换为现场真实值，不得复制示例占位符；构建器会现场运行版本探测并逐项拒绝
漂移。输出已存在时默认拒绝覆盖；只有明确重建同一目标时才使用 `--force`。工作树内的输出
路径必须被 `.gitignore` 显式排除，否则构建器在写入前失败关闭；也可以把 Attestation 写到
项目根目录之外。

## 6. 验证命令

```powershell
uv run --frozen python tools\verify_release_attestation.py `
  --project-root . `
  --attestation deliverables\VisionData_Gate_RC3.attestation.json
```

验证器重新执行：

- 精确 JCS 与 Statement 域摘要核验；
- Git worktree clean、commit 和 tree 对账；
- 两个 ZIP 的存在性、大小、SHA-256、底层文件身份和完整 package audit；
- 六项必需材料的路径、大小与 SHA-256 对账；
- CycloneDX SBOM 基本结构核验；
- 全量测试、clean-extract 和两份 build receipt 的 JCS、schema、PASS 语义与交叉绑定核验；
- 受跟踪 build entrypoint、隔离 workspace 路径、现场工具版本及 required-path 分母核验；
- Statement 摘要与回执摘要的摘要式比较。

成功结果仍明确输出：

```text
status                 PASS_LOCAL_INTEGRITY
two_declared_outputs   BYTE_IDENTICAL
signature              NOT_CONFIGURED
trusted_timestamp      NOT_CONFIGURED
external_anchor        NOT_CONFIGURED
submission_eligible    false
official_status        NOT_EVALUATED
```

## 7. 威胁边界

本协议可以发现普通文件漂移、ZIP 替换、回执替换、Statement 字段修改、缺件、路径逃逸、脏工作
树和双构包不一致。如果攻击者可以同时修改 Statement 并重新计算其未签名摘要，单靠本文件不能
证明原签发者身份或原始时间。要跨机器建立身份与时间保证，后续版本必须接入经过评审的签名
服务、受保护密钥、可信时间戳以及外部不可回滚锚点；在这些设施真正配置前，三个字段必须继续
保持 `NOT_CONFIGURED`。

# Product Kernel CLI

`visiondata-gate product-run` 是正式产品内核的本地入口。它直接调用
`ProductService` 的公开生命周期接口，不依赖 pytest、测试夹具、Fake runner、
REST 拼接或私有方法。

## 运行边界

- 输入必须是操作员有权使用的本地 Omni 格式目录。
- 源目录只读就地检查，原图、Mask、标注和 metadata 不复制进产品目录。
- `--product-root` 是唯一写入区，且必须与源目录形成两个互不包含的独立目录树。
- 必须显式提供来源归档 SHA-256、用途、权利依据和授权声明。
- 此命令固定使用确定性本地 Agent 内核；Hosted AgentTeams、外部模型和网络传输均关闭。
- 命令成功表示 ProductKernel 完成合同成立，不表示数据 `PASS`，更不表示客户验收、
  工厂部署、安全认证或生产放行。

## 命令

安装项目后可直接执行：

```powershell
visiondata-gate product-run `
  --source-root "E:\authorized-data\Omni-AD-30" `
  --source-archive-sha256 "<64位小写SHA-256>" `
  --purpose "用于本地只读工业视觉训练数据质量门禁。" `
  --rights-basis "操作员确认已获授权，可在本机执行限定用途检查。" `
  --attest-authorized-use `
  --product-root "E:\authorized-data\visiondata-private-state" `
  --goal "审核授权工业视觉数据，动态补证并交付可追溯整改工单。" `
  --seed 20260828
```

`--source-archive-sha256` 是操作员提供的来源身份绑定，不是 CLI 对整个目录重新计算的
归档哈希。目录内容还会在授权和执行前分别建立数据画像；画像漂移时任务失败关闭。

## 主链与测试的分离

```text
操作员授权输入
  -> ProductService 租户 / 工作区 / 项目
  -> 本地来源授权与路径脱敏回执
  -> 任务预检
  -> run_task_sync
  -> ProductKernelRunReceipt
  -> SHA 校验后的证据 ZIP

pytest
  -> 只调用并观察上述公开入口
  -> 验证退出码、只读边界和收据绑定
  -> 不参与规划、工具执行、裁决或证据生成
```

成功时 stdout 只输出一份稳定 JSON。核心字段包括：

- `command_status=COMPLETED_LOCAL_PRODUCT_KERNEL`
- `kernel_receipt_status=TASK_BOUND_IN_SHA_VERIFIED_EVIDENCE`
- `runtime_status`、`initial_decision`、`final_decision`
- `kernel_receipt_sha256`、`evidence_sha256`
- `network_mode=OFFLINE_NO_EXTERNAL_TRANSPORT`
- `production_approval_status=pending`
- `production_release_allowed=false`

业务裁决为 `RECAPTURE`、`QUARANTINE`、`DEFER` 或其他阻断结果时，只要内核和证据交付完整，命令仍可
正常结束；裁决值不能被当作执行错误。参数、授权、预检、内核运行、收据完整性或证据交付
失败时，stderr 输出结构化错误 JSON，并以退出码 `2` 结束。

CLI 输出不包含源目录或产品目录的绝对路径，也不会输出任何 Token。完整证据保留在指定的
私有 `--product-root` 中，供后续独立审核。

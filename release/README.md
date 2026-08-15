# RC1 发布附件完整性

[`SHA256SUMS.txt`](SHA256SUMS.txt) 列出 `v0.1.0-goai-rc1` Release 的五个作品附件；校验清单不包含自身，以避免递归摘要。

本地已保留全部附件时，运行：

```powershell
uv run python tools/check_release_assets.py --require-all
```

干净 Git checkout 默认不含被忽略的候选 ZIP。此时不带 `--require-all` 的 CI 会核验四个受版本控制的附件，并把 ZIP 条目与 detached receipt 中冻结的文件名、大小和 SHA-256 交叉比对。GitHub Release 上传后还需单独核对平台返回的 asset digest。

`v0.1.0-goai-rc1` tag 是冻结发布快照；`main` 可以继续增加验证与文档加固，但不得静默移动已发布 tag 或覆盖冻结候选 ZIP。

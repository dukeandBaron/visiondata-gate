# VisionData Gate 最小体验图片

本目录提供 6 张可直接上传到 `/workspace` 的固定 seed 合成图片，用于本地复现工作台交互。它们来自项目内部批次 `visiondata-demo-seed-20260809-dirty`，不是生产现场数据，也不能作为模型精度或真实产线效果证明。

## 文件分组

### clear

- `clean-val-gear.png`
- `clean-val-bearing.png`
- `clean-test-bearing.png`

### quality_anomalies

- `q-blur.png`
- `q-underexposed.png`
- `q-overexposed.png`

## 推荐体验路径

1. 启动 `run_workbench.ps1`，打开 `http://127.0.0.1:4173/workspace`。
2. 点击“上传真实图片”，一次选择本目录中的 6 张 PNG。
3. 用 `INSPECTOR` 查看本地像素统计、剖面探针和标注 revision。
4. 用 `AGENT` 生成不可变 Activity Trace，展开 Tool Receipt 并询问 Evidence Copilot。
5. 在已保存的 BBox 上右键创建工单；未完成具名人工复核时，提交按钮应保持禁用。
6. 进入 `/capa`，验证本地工单的 `OPEN -> ACKNOWLEDGED -> IN_CAPA` 流转。

若要体验重复账本，可将同一张图片再次上传。字节重复只证明 SHA-256 相同，不自动证明 Train/Val 泄漏。

## SHA-256

完整校验值见 `SHA256SUMS.txt`。

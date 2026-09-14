# Reviewer Workbench

这是一个与现有 Streamlit 页面、`app.py`、Demo 脚本和 API 实现完全解耦的只读前端原型。它用 IDE / 工作台信息架构呈现案件、合成视觉 fixture、责任项、Parent / Child 血缘与 Governed Agent Trace。

## 本地预览

目录中只有原生 HTML、CSS、JavaScript，不需要安装前端依赖。可从仓库根目录启动任意本地静态服务器，例如：

```powershell
python -m http.server 4173 --directory reviewer_workbench
```

然后访问 `http://127.0.0.1:4173/`。

## 只读数据契约

页面优先读取：

```text
GET /api/reviewer/snapshot
GET /api/reviewer/assets/before
GET /api/reviewer/assets/after
```

Snapshot 必须声明：

```json
{
  "schema_version": "visiondata-gate.reviewer-workbench.v1",
  "case": {},
  "public_pilot": {},
  "synthetic_visual": {},
  "phases": [],
  "runtime": {},
  "snapshot_integrity": {"sha256": "<server-provided value>"},
  "external_model": {
    "base_url": "https://gw.opentoken.io",
    "mode": "off",
    "key_configured": false,
    "connection_status": "NOT_CONFIGURED"
  }
}
```

前端转换层只从真实 contract 的 `case / public_pilot / synthetic_visual / phases / runtime / snapshot_integrity / external_model` 生成 UI 视图；不要求后端提供不存在的 `cases[]`。只有 schema 与必需结构都通过最小校验时才采用 API 数据，否则自动回退到内嵌的冻结证据摘要。外部模型卡只读取并显示 provider 状态；页面没有 Key 输入框，也不会读取、展示或存储 Key。

## Fallback 证据边界

- `Synthetic-v3` 只标为合成工程证据；内嵌 SVG 只是视觉槽位 fallback，不是证据图片或真实工厂图像。
- 已显示的唯一图像测量为 `Laplacian 1.8585 < 18`；After fallback 不声明 `PASS`。
- RC2 只显示冻结的 `180 / 45 findings / 45 工单 / 1 replan / 3 workers / RECAPTURE`。
- RC3 只显示 `49→33 findings / 6 closed / 43 open / HOLD / production=false`。
- Reviewer 模式中的审批与 Child Run 按钮始终禁用。
- 页面不展示模型私有思维链，只展示结构化决策摘要和工具回执。

## 响应式布局

- `> 1100px`：案件资产树 + 双主视窗 + Agent Trace 三栏工作台。
- `≤ 1100px`：案件 / 证据 / Trace 面板 Tab，避免挤压和横向溢出。
- `≤ 720px`：双主视窗纵向排列，底部治理状态自动精简。

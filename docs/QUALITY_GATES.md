# 工程质量门禁：基线、范围与渐进收紧

核查日期：2026-09-12。依据外部 `visiondata-gate-review.md` 的第 1–5 条，核查当前 authority 工作区；公开 GitHub 快照和实际 Actions 运行结果不由本地文件存在性替代。

本文不声称已经达到全仓类型正确、95% 覆盖率或安全扫描零发现。构包期间不修改依赖版本、`uv.lock` 或广域格式化源码。

## 当前实测边界

| 项目 | 当前证据 | 门禁状态 |
| --- | --- | --- |
| 默认 Ruff lint | 当前工作区 `ruff check --no-cache .`：0 项问题 | `PASS_LOCAL`，不等于全仓 CI PASS |
| Ruff format | `ruff format --no-cache --check .`：19 个文件需格式化，285 个已格式化 | `HOLD`；保留并行工作的用户改动，未自动格式化 |
| 建议扩展规则 | `I,UP,B,SIM,C4,PERF,PT,RUF` 在 `src desktop tools tests`：1,130 项 / 256 个文件 | `BASELINE_ONLY`，不可直接全部升级为阻断门禁 |
| Python 类型检查 | `.venv` 未安装 pyright/mypy，无项目类型检查配置、无 CI 类型步骤；已有系统 mypy 宽松诊断为 945 项 / 81 文件 | `NOT_RUN_IN_PROJECT_ENV`；系统工具结果只作额外基线 |
| 测试覆盖率 | `.venv` 未安装 coverage/pytest-cov，无 coverage 配置及 CI 阈值 | `NOT_MEASURED`；不得填写 95% 或用测试数量代替覆盖率 |
| Python CI 平台 | 本轮已配置 Linux + Windows × Python 3.12 / 3.13，显式解释器选择与版本断言；相关静态合同 4 项通过 | `LOCAL_CONFIG_VERIFIED / ACTIONS_NOT_RUN` |
| pip-audit / Bandit | `.venv`、项目 qa 依赖、锁文件和 CI 均未配置 | `NOT_RUN`；不等于没有漏洞 |
| CodeQL / Dependabot | authority 未发现对应 workflow / `.github/dependabot.yml` | `NOT_CONFIGURED` |
| pre-commit | 没有 `.pre-commit-config.yaml`，也没有锁定 pre-commit 工具 | `NOT_CONFIGURED` |

基线环境为 Windows、项目 `.venv` Python 3.12.5、Ruff 0.15.22、pytest 9.1.1。当前 `tests/` 根目录有 133 个 `test_*.py`，`src/visiondata_gate/` 有 120 个扁平 Python 模块；这些数量不是覆盖率或功能完成度。

当前工作区含进行中的修改，上述数值是本次测量快照，后续变更应重新测量。安装器或其他工作流的通过不能抹去这里的 `HOLD` / `NOT_RUN`。

## 1. 类型检查：先可重复基线，再收紧契约模块

审查意见成立：类型注解尚未构成 Python CI 门禁。Web 已有 TypeScript 检查不代表 Python 类型检查已完成。

推荐在构包冻结结束并获得依赖变更授权后，把一个固定版本的 Pyright 加入 qa 工具并同步锁文件；先以 `basic` 模式建立全仓基线，再逐个收紧契约、证据、策略、发布和审计模块。不得用全局忽略所有未知类型或大段 `type: ignore` 制造绿色结果。

预期的后续检查入口（当前缺工具，尚未执行）：

```powershell
uv run --frozen pyright --pythonpath .venv/Scripts/python.exe --outputjson
```

CI 的解释器必须来自同一版本矩阵；不能借用系统环境的类型结果冒充项目锁定工具结果。已有系统 mypy 只能作为额外诊断，不作为正式门禁。

本轮额外运行已有系统 mypy 1.11.2，以项目解释器定位依赖，但采用宽松导入策略：945 项诊断 / 81 文件，退出码 1。其中 `arg-type` 547、`union-attr` 113、`attr-defined` 86、`assignment` 75、`index` 56。该计数不是 Pyright basic/strict 结果，也不是 945 个已确认运行时缺陷；Pydantic 构造、类型工具版本与类型注解表达方式需要进一步分类。

```powershell
python -m mypy --python-executable .venv/Scripts/python.exe --python-version 3.12 --follow-imports=silent --ignore-missing-imports --no-incremental --cache-dir NUL --show-error-codes --no-error-summary --no-pretty src/visiondata_gate
```

## 2. Windows 与 Python 版本矩阵

外部审查中“仅 Ubuntu”不再适用于当前 authority：原 `.github/workflows/ci.yml` 已配置 Ubuntu、Windows，以及独立 Windows Tauri 合同检查。本轮进一步把 Python 版本从 job 名称变成实际约束，覆盖 `3.12` 与 `3.13`，保留 `fail-fast: false`、锁定依赖安装和动作 SHA 固定。

本轮 Python job 已明确使用：

```yaml
matrix:
  os: [ubuntu-latest, windows-latest]
  python-version: ["3.12", "3.13"]
```

`setup-uv` 使用对应 `python-version`，依赖安装及各 Python 检查显式选择同一解释器；新增步骤断言实际 `sys.version_info` 并输出 `sys.version`。Ruff lint 与 format 被拆成两个独立步骤，避免 Windows PowerShell 的后一个原生命令成功掩盖前一个失败。

静态合同测试 `tests/test_quality_gate_contracts.py` 已实跑 4 项通过；新增矩阵、显式 Ruff 配置和独立 lint/format 步骤均先观测到旧配置下的失败。未执行 GitHub Actions，也未创建 Python 3.13 项目环境。本机存在 Python 3.13 解释器不等于已在该环境安装锁定依赖或通过全套测试。

当前公开导出器只显式从模板注入 Pages workflow，没有 public CI 模板。不能把 authority 中依赖私有发布证据的整套 CI 直接复制到公共快照。公开 CI 的模板、导出映射及契约测试需要另行收敛并核验；本文不改导出 allowlist。

## 3. 覆盖率：不盲设 95%

当前没有覆盖率数字。先在固定输入和完整测试范围上测量行覆盖率与分支覆盖率，并保存实际报告，然后再决定全仓基线和关键模块阈值。

依赖授权后的首次测量命令示例：

```powershell
uv run --frozen python -m pytest -q --cov=visiondata_gate --cov-branch --cov-report=term-missing --cov-report=json:tmp/quality/coverage.json --cov-report=xml:tmp/quality/coverage.xml
```

关键路径应包括目的地/权限拒绝、证据缺失、哈希不一致、审批绑定失效、恢复冲突和审计链失败等反例。应按实际模块路径逐文件审计覆盖率，不能用聚合 95% 掩盖某个关键文件未测试。第一轮只报告实际值和未覆盖分支；修复缺口后再引入 ratchet（不得低于已核验基线），最后对可达到的关键模块设严格阈值。

## 4. 安全扫描：配置、执行、发现处置分开

`pip-audit` 是依赖漏洞检查，Bandit 和 CodeQL 是静态分析，Dependabot 是依赖更新工作流，不能互相替代。当前均未形成已验证工程门禁。

后续最窄落地顺序：

1. 构包冻结后，在独立候选中固定审计工具版本，并由同一锁文件准备环境。
2. `pip-audit` 对明确的平台/extra 依赖集合测量；说明所用漏洞数据库与网络范围。不得把只审当前 Windows 环境写成所有平台均安全。
3. Bandit 先扫描 `src`、`desktop`、`tools`，逐条验证规则命中；不把所有 `assert` 或预期子进程调用自动升级为已证实漏洞，也不全局关闭规则。
4. 公共仓库单独配置最小权限 CodeQL job 和 Dependabot 更新来源；新增 GitHub 安全能力及外部写入需在对应任务授权后执行。
5. 已知抑制项必须有规则编号、具体理由、范围和复核条件；扫描运行失败或缺工具必须失败关闭/明确 `NOT_RUN`，不可使用 `|| true` 隐藏。

预期命令（当前未安装工具，尚未执行）：

```powershell
uv run --frozen python -m pip_audit --format json
uv run --frozen python -m bandit -r src desktop tools -f json
```

`pip-audit` 可能访问外部漏洞服务，执行前应确认只发送必要的依赖标识，不包含客户数据或凭据。

## 5. Ruff：先显式等效，再有选择地扩展

本轮已加入保持现有规则语义的显式配置：`target-version = "py312"`、`line-length = 88`、lint 选择 `E4,E7,E9,F`。未启用全部 E 规则，未改变项目支持的 Python 范围，也未调整依赖版本或 `uv.lock`。NumPy 上限只补充保守冻结说明，不把尚未验证的新版本写成不兼容。

建议规则组的测量摘要：

| 规则 | 命中数 | 处理原则 |
| --- | ---: | --- |
| RUF001 | 538 | 大量为中文全角标点；先定义允许字符，不能盲改中文内容 |
| I001 | 205 | 导入排序，可在独立干净候选中机械整理后全套回归 |
| UP042 | 62 | Enum → StrEnum 可能改变行为，逐项审查 |
| UP035 | 38 | 检查 typing 导入迁移兼容性 |
| RUF100 | 38 | 核对既有 noqa 是否仍有理由 |
| RUF022 | 25 | 显式导出顺序，不改公共 API 内容 |
| PERF401 | 22 | 不以列表推导式取代必要的审计/异常处理语义 |
| PT018 | 21 | 测试断言拆分需保持原始失败语义 |
| B008 | 15 | 区分 FastAPI 的 Depends 等声明式默认值与真正易变默认值 |

不在 dirty authority 上运行全仓 `--fix` 或格式化。启用新规则时限定文件集合，保存前后诊断数并运行受影响测试。pre-commit 应在工具锁定后复用 CI 的 Ruff 版本和检查范围，不是绕过 CI 的替代品。

本次可重复的只读命令：

```powershell
.venv/Scripts/python.exe -m ruff check --no-cache .
.venv/Scripts/python.exe -m ruff format --no-cache --check .
.venv/Scripts/python.exe -m ruff check --no-cache --select I,UP,B,SIM,C4,PERF,PT,RUF src desktop tools tests
```

## 交付判定

当前总体状态：`QUALITY_GATE_BASELINE_ESTABLISHED / HOLD_UNMEASURED_GATES`。只有实际跑过且报告满足判定条件的检查才可标记 PASS；配置已写、工具可调用、源代码存在、CI 实际通过和发布包已验证是不同状态。

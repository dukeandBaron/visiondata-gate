# 能力与运行入口

VisionData Gate 是工业视觉数据准备、整改复验与受控模型开发工作台。下面区分业务入口、执行实现与尚未贯通的环节；功能存在不代表每个部署都已完成现场验收。

## 当前可以实际执行的路径

| 路径 | 用户操作与实际实现 | 验证入口 | 明确边界 |
| --- | --- | --- | --- |
| 图像与标注 | 本地工作簿导入、人工框选、保存版本、冻结用途；服务端复核图片和标注摘要 | `tests/test_operator_snapshot_source.py`、`tests/test_operator_snapshot_annotation_roundtrip.py` | 不是自动语义标注；结构检查不能证明框选到了正确缺陷 |
| 上传快照 Gate | `product_runs.py` 执行质量、重复、标注、覆盖、元数据检查并保存 Finding | `test_operator_snapshot_executes_as_native_product_task_and_seals_evidence` | 此路径固定工具清单，动态任务数为 0；不是每次上传都触发 LLM 或动态补证 |
| 动态案件 | 单独创建 IndustrialIncident；`incident_agent_kernel.py` 与 `worker_selection.py` 按证据选择/拒绝 Worker，保存预算和 Trace | DynamicBench-v4；`tests/test_dynamic_benchmark_v4.py` | v4 为真实服务执行合成输入，不是工厂上线；选择规则并非已测得最优信息增益 |
| 精确重复整改 | 人工批准后只在派生版本排除同身份、同划分的精确重复，创建 Child 独立重检 | `test_exact_duplicate_capa_removes_only_derived_copy_and_child_rechecks` | 字节、标注、类别、视角、工况等身份必须匹配，覆盖下限仍满足；跨划分、近重复、冲突不能盲目自动删除 |
| 重拍、返标、补采 | 生成明确待办，人提交新图像或标注后再检查 | `capa.py`、标注往返测试 | 不操控相机、机器或生产线；缺新证据时保持阻断。像素工单与 CAPA 责任账本尚无统一自动关闭桥接 |
| 参考学习闭环 | 实际 CPU/NumPy 六参数模型，两轮数据/父权重绑定、训练、独立验证、候选选择、反馈及最终测试封存 | `tools/run_learning_demo.py`、`tests/test_learning_lifecycle.py` | 合成图像/标签与模拟审批；证明软件闭环，不证明工业模型效果 |
| YOLO 检测训练 | 登记可信运行时、受控数据和可选权重，独立授权后执行有界 CPU 监督训练，人工选择候选，关联验证反馈 | `local_model_registry.py`、`vision_model_api.py`、`tests/test_vision_model_api.py` | 训练预算 10–600 秒；需自备合法环境/权重；test 保持未运行，不能继承参考模型的防遗忘验收结果 |
| Normality 推理 | 模型中心登记带稳定性证据的 pack → 单独批准运行时 → 冻结图像资产 → 授权 CPU 推理 → 验封结果 | `tests/test_normality_model_registry.py`、`tests/test_normality_inference.py`；Web 合同与浏览器测试 | 真实模型需自备可信 pack/环境；前端测试使用明确的合成 API 替身，不等于在该安装包中跑过真实模型 |
| 异常与恢复 | 未知写入保留账号/项目级对账锁，按原 request_key 只读确认；Child 中断可恢复 | `tests/web_vision_model_workbench.browser.mjs`、快照 CAPA 恢复测试 | 不自动重发不确定的训练/整改写请求；人工批准不转授生产权限 |

## 模型交互与单次适应

Normality 现在有真实 PNG 热图读取、具名反馈持久化与只读回读。账号/项目/记录变化时取消过期请求，未知写结果按原 request_key 对账，不自动重发。模型实现升级后可重新具名核验沙箱批准。

新增单次 Normality TTT：冻结主干、父包、归一化器和阈值，只在外部已授权 CPU 运行时更新克隆 student；固定遮蔽重建、教师回放和参数锚定损失，独立 guard 检查后采用或回滚。每次重置，不进行永久模型替换。详见 [TTT 执行合同与复现](NORMALITY_TTT.md)。实现/运行回执、模型质量与安装包验收分开判断。

## 尚未完成的连接

- **Normality 反馈到责任关闭**：具名反馈可显式导入真实工作簿，人工保存框选后再建立 OPEN 工单并绑定血缘。当前不会自动创建标注、关闭 CAPA 或进入训练；工单状态更新、返图复验到最终关闭仍须按各自合同验收。
- **统一防遗忘门禁**：参考学习与持续学习评测合同不能直接外推到每个 YOLO/Normality 产品任务。
- **持续学习、RL、VLM 预标注、主动学习、自动 Mask**：单次 TTT 不代表这些功能已完成；YOLO detect 训练的 adaptation 仍为 OFF，永久在线自更新没有开放。
- **外部算力**：交接合同不等于已配置远端连接或已提交训练，本轮不提供此类成功声明。
- **工厂指标**：缺独立真值/客户验收时，误放行率、误拦截率、ROI 仍未测量。

## 三种交付物分别验收

1. **源码**：按提交或内容清单复现；运行结果绑定当次输入、Case/Run 和工具版本。
2. **Pages**：浏览器本地图片处理与合成回放，没有持久化业务后端。HTTP 200 不证明已部署最新 main。
3. **安装器**：按其 BUILD/SOURCE 清单与安装器 SHA 单独验收。源码新测试通过不会自动更新已发布二进制。

所有路径均保留人工最终判断；任务完成、数据 Gate PASS、模型候选与生产放行是不同状态。

[现场复现](LIVE_REPRODUCTION.md) · [决赛证据地图](FINALS_EVIDENCE_MAP.md) · [技术包构建](TECHNICAL_SUBMISSION_BUNDLE.md)

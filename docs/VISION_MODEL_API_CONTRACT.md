# 本地视觉模型 API 合同 v1

本合同描述 VisionData Gate 已实现的本地视觉模型边界。它管理外部模型权重、
显式授权的训练解释器、冻结 BBox 数据集、有界 CPU 训练和人工反馈；它与 LLM
Provider 配置分离，也不把“可执行训练”写成“工业模型已经达标”。

## 安全与身份约束

- 路由前缀为 `/v1/projects/{project_id}`；请求必须通过宿主认证和项目成员检查。
- POST 仅接受 loopback 受控入口，不信任 `X-Forwarded-For`。
- DTO 使用 `extra=forbid`。本地绝对路径只进入授权请求和私有存储，不进入正常
  公共响应；当前没有权重下载 API。
- 响应以 JCS 封存，strong `ETag` 与 `X-Content-SHA256` 绑定当前回执。
- `request_key` 提供同身份、项目和操作范围内的幂等对账；未知网络结果不能
  自动重放写请求。

## 资源与路由

| 资源 | 主要路由 | 已实现行为 | 不代表 |
| --- | --- | --- | --- |
| 模型登记 | `GET/POST /vision-models` | 流式核对权重 SHA、任务类型、来源和许可声明；登记时不反序列化 `.pt` | 已加载、已验证安全或允许生产 |
| 外部运行环境 | `GET/POST /vision-runtimes`、`POST /vision-runtimes/{id}/probe` | 绑定解释器 SHA 与 runtime fingerprint；显式 `import_check=true` 才执行库导入／CPU probe | 自动安装依赖或云端算力已连接 |
| 检测数据集 | `GET/POST /vision-datasets`、`POST /vision-datasets/from-data-pool` | 冻结 train／val／test、BBox、采集组、图像和标注版本 | 自动生成标签、Mask 或把 val/test 回灌 train |
| 训练任务 | `GET/POST /vision-training-runs`、cancel／recover／selection | 单次有界 CPU detect；保存运行、checkpoint 与人工选择状态 | GPU 已运行、自动重试或生产发布 |
| 验证反馈 | `GET /vision-training-runs/{id}/feedback`、triage | FP/FN 只生成复核候选；具名人员分类后可显式关联下一轮 | 模型分歧自动证明标签错误 |

## 检测数据冻结

标准输入包含非空 train／val／test、明确 `class_names`、采集组和人工复核的 BBox。
每个样本绑定图像 SHA、split、group、annotation revision 与 reviewer。空框正常样本
需要显式 `normal_attested=true`；系统不从二值 Mask 推断类别或框。

以下情况在训练启动前 fail closed：

- 图像字节或解码 RGB 像素跨 split 重复；
- 同一 split 内出现字节完全重复或解码像素完全相同的图像；
- 采集组跨 train／val／test、held-out 成员重新进入 train；
- 图像、标签、框、类别、尺寸或冻结回执发生漂移。

这不是近重复／连续帧语义判定器，也不会自动删除被拒绝样本。

## 有界 YOLO 训练

训练执行器只支持监督 BBox `detect`，当前设备为 CPU。冻结预算为：

```text
epochs=1–5
imgsz=64–320（32 的倍数）
batch=2–8
max_seconds=10–600
threads=1–4
```

API DTO、发布 JSON Schema、Web 表单和底层 `YoloTrainingConfig` 使用相同范围，
默认 `max_seconds=120`。独立 Normality 推理预算不套用该训练下限。

随机初始化不能写成 pretrained。加载已登记 `.pt` 时，必须再次核对精确权重
SHA，并分别确认 trusted weights 与 pickle load 风险。运行前检查目标卷空间；
不足时写入 `YOLO_OUTPUT_SPACE_INSUFFICIENT`，不启动 runtime 或复制训练数据。

训练状态为：

```text
QUEUED → RUNNING → SUCCEEDED_CANDIDATE | FAILED | CANCELLED | TIMED_OUT
```

`SUCCEEDED_CANDIDATE` 只表示这次训练、验证和候选权重持久化完成；指标可以为 0，
仍需人工选择，且 `production_release_allowed=false`。中断／失败任务的保留策略
见 [MODEL_JOB_RETENTION](MODEL_JOB_RETENTION.md)。

## 反馈与下一轮

固定验证协议对 val 预测做 class-aware、一对一 IoU 匹配并生成 FP/FN 复核候选。
test 不输出错题，也不参与训练选择。每条反馈绑定 run、dataset、sample、图像／
标签／checkpoint SHA 与协议摘要。

人工 triage 只能把候选记录为模型问题候选、标签复核候选、困难样本候选或证据
不足；它不自动确立标签真值、关闭 issue 或授权训练摄入。下一轮若响应旧反馈，
必须使用新数据回执和显式反馈引用，仍需重新通过数据门禁。

## 当前边界

```text
training_device=CPU_ONLY
supervised_bbox_detector=BOUNDED_LOCAL_RUNTIME
weight_download_allowed=false
normality_ttt_status=NORMALITY_EPISODIC_AVAILABLE
detect_training_adaptation=OFF
industrial_effectiveness_status=NOT_EVALUATED
production_release_allowed=false
```

Ultralytics 的 AGPL／Enterprise 许可义务需要独立评估；分进程运行不自动豁免。

## Normality 图像推理与单次适应

模型中心现提供 `vision-ttt-capabilities`、`vision-models/{id}/ttt-inferences`、
`vision-ttt-failures`，以及 `vision-inferences/{id}/heatmap` 和 `feedback`。
普通推理与 TTT 的原模型、输入图像、实现身份均由服务端重新验证；TTT 还绑定
适应、正常回放、独立复验三组的字节与解码像素身份。授权需单独给出，不由
一次普通推理批准隐式继承。

TTT 仅适用于 Normality student，候选只用于当前会话。真实 PNG 响应绑定字节
SHA 和强 ETag；反馈保存后只读回读，不自动确立标签真值。硬超时／worker
错误生成独立失败回执，没有测量就不填虚构步数。未知写结果使用原请求键
对账，禁止自动重新运行。[完整合同与预算](NORMALITY_TTT.md)

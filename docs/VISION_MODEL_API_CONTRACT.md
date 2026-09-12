# 本地视觉模型 API 合同 v1

2026-09-12，本地工程候选。安装函数 `install_vision_model_routes(app, actor_dependency, product_dependency)`；由 Goal2 统一挂载及认证。该模块管理视觉权重与外部训练运行环境，与 LLM ProviderCenter 分开。

所有路径前缀 `/v1/projects/{project_id}`；所有 GET/POST 都需宿主认证和项目成员资格。POST 额外验证连接来源为 loopback，不信任 X-Forwarded-For。DTO `extra=forbid`；绝对本地路径只进入请求和私有存储，正常响应不返回绝对路径。当前没有权重下载 API。

## 公共请求字段

所有 POST 都包含：`request_key`（12–100 字符 `[A-Za-z0-9_-]`）、`reviewer_identity`（2–160）、`note`（8–1000）。同身份/项目/操作/request_key 的相同请求幂等；不同内容返回 409。审核人姓名是当前操作者提供的声明，真实 actor 由宿主依赖提供，不从姓名推断身份。

所有响应为 JCS 封存字典，`receipt_sha256` 为去除此字段后的 JCS SHA256；响应头 strong `ETag`、`X-Content-SHA256`、`Cache-Control: private, no-store`。列表也是字典 `{schema_version,project_id,items,receipt_sha256}`，不是裸数组。

## 模型注册

- `GET /vision-models`：模型列表。
- `POST /vision-models`：201，公共字段加 `display_name`, `weights_path`（本地绝对路径）, `expected_weights_sha256`（64位小写hex）, `task_type`（detect/segment）, `license_id`, `source_description`, `operator_attests_read_authorized=true`。
- `GET /vision-models/{model_id}`：读取持久化登记事实。

返回字段包含 `resource_id=model_id`, `project_id`, `display_name`, `task_type`, `weights_sha256`, `file_bytes`, `format`（pt/onnx/safetensors）, `license_id`, `license_status=OPERATOR_DECLARED_NOT_LEGAL_VERIFICATION`, `source_description`, `status=REGISTERED_NOT_LOADED`, `loaded=false`, `production_release_allowed=false`。

登记只流式读字节/SHA，不解析或反序列化 `.pt`。模型可以登记为 segment，但首版可执行训练只支持 detect。读到登记事实不等于文件当前未变，启动时会重新校验字节。

## 外部 Python 运行环境

- `GET /vision-runtimes`：已登记运行环境列表。
- `POST /vision-runtimes`：201，公共字段加 `display_name`, `executable_path`, `expected_executable_sha256`, `operator_attests_trusted_runtime=true`, `operator_attests_execution_authorized=true`。
- `POST /vision-runtimes/{runtime_id}/probe`：200，公共字段加 `expected_runtime_sha256`, `operator_attests_trusted_runtime=true`, `operator_attests_execution_authorized=true`, `import_check=false`（显式设 true 才做实际库导入与 CPU probe）。

运行环境登记会执行已显式授权解释器的 stdlib metadata 探测，不安装包。返回 `runtime_id`, `display_name`, `executable_sha256`, `runtime_sha256`, `probe`, `status`。`probe.status` 为 ready/unavailable；`probe.import_status` 区分未导入与实际结果。`runtime_sha256` 是运行环境指纹，不等于 exe SHA，训练必须绑定该指纹。

## 明确授权的检测数据集

- `GET /vision-datasets`：冻结数据集列表。
- `POST /vision-datasets`：201，公共字段加 `source_root`, `manifest`（保持原始JSON对象）, `expected_manifest_sha256`（原始 manifest JCS SHA）, `operator_attests_data_authorized=true`。

manifest：

```json
{
  "schema_version": "visiondata-gate.detection-dataset.v1",
  "source_version": "reviewed-detection-v1",
  "class_names": ["defect"],
  "samples": [
    {
      "sample_id": "train_a",
      "image_path": "images/frame.png",
      "image_sha256": "<64-hex>",
      "split": "train",
      "group_id": "acquisition-a",
      "annotation_revision": 1,
      "boxes": [{"class_id": 0, "x_center": 0.5, "y_center": 0.5, "width": 0.25, "height": 0.25}],
      "reviewer_name": "Named reviewer",
      "reviewed": true,
      "normal_attested": false
    }
  ]
}
```

上例仅说明一条样本的字段；实际必须有非空 train/val/test，且采集组、图片字节和像素不能跨集合重复。总样本最多64；框必须真实明确提供，不从二值mask猜类别。空框需 `normal_attested=true`。返回 `dataset_id`, `status=FROZEN_REVIEWED_DETECTION_DATASET`, `dataset_receipt_sha256`, `dataset_receipt`（含 class_names、samples、split_counts 等）。项目内已登记的 heldout 成员不得在后续数据集换成 train。

## 训练创建与查询

- `POST /vision-training-runs`：202，显式创建后直接启动一个有界后台工作线程；无自动重试调度。
- `GET /vision-training-runs`：列表。
- `GET /vision-training-runs/{run_id}`：重新读取持久化状态；浏览器断开后恢复查询，不自动发起第二次训练。

训练请求：公共字段，加：

```json
{
  "runtime_id": "vision_runtime_<opaque>",
  "expected_runtime_sha256": "<runtime fingerprint>",
  "dataset_id": "vision_dataset_<opaque>",
  "expected_dataset_receipt_sha256": "<dataset receipt>",
  "initialization": "ARCHITECTURE_RANDOM",
  "initial_model_id": null,
  "expected_weights_sha256": null,
  "architecture": "yolo26n",
  "training": {"epochs": 1, "imgsz": 64, "batch": 2, "seed": 0, "max_seconds": 120, "threads": 2},
  "operator_attests_training_authorized": true,
  "operator_attests_trusted_runtime": true,
  "operator_attests_trusted_weights": false,
  "operator_attests_pickle_load_risk": false,
  "ultralytics_license_acknowledged": true,
  "adaptation": "OFF"
}
```

`REGISTERED_WEIGHTS` 模式必须同时给出 initial_model_id、expected_weights_sha256，并把 trusted_weights 与 pickle_load_risk 两项明确设 true。`.pt` 可能包含可执行 pickle，登记不构成加载授权。随机初始化是从已安装架构配置建立新模型，不能写成 pretrained。

训练限制：CPU detect；epochs 1–5，imgsz 64–320且32倍数，batch 2–8，max_seconds 10–600，threads 1–4；服务和执行器取共同支持范围。生产放行始终 false。Ultralytics AGPL-3.0/Enterprise 需要适用性审查，分进程运行不自动免除许可证义务。

状态 `QUEUED -> RUNNING -> SUCCEEDED_CANDIDATE | FAILED | CANCELLED | TIMED_OUT`；中断可记录 `INTERRUPTED_HOLD`。响应包含 `run_id`, `runtime_id`, `dataset_id`, `initial_model_id`, `initialization`, `pretrained_claimed=false`, `device=cpu`, `training`, `cancel_requested`, `candidate_model_id`, `selection=PENDING`, `result`, `error_code`。

真实完成后 result 包含 baseline/candidate 验证指标、actual_epochs、training_samples、validation_samples、checkpoint.relative_path/sha256/bytes、test_evaluation=NOT_RUN、模型初始化与参数、CPU/GPU和工业效果边界。`SUCCEEDED_CANDIDATE` 表示训练/验证/权重持久化成功，指标可以是0，不自动代表效果达标。

## 取消、恢复、人工选择

- `POST /vision-training-runs/{run_id}/cancel`：公共字段 + `expected_run_sha256`, `operator_attests_reviewed=true`。设置请求后由拥有的执行器终止自己创建的工作进程，保留记录。
- `POST /vision-training-runs/{run_id}/recover`：同上。只在原工作锁不再被持有时记录 INTERRUPTED_HOLD，不自动重跑；新训练需要新请求和授权。
- `POST /vision-training-runs/{run_id}/selection`：上述字段 + `action=APPROVE_SANDBOX|REJECT`, `expected_candidate_weights_sha256`。重新核验候选文件与数据绑定；不接生产。
- `GET /vision-operations/{operation}/{request_key}`：读取原操作对应 resource_id/resource，`auto_replayed=false`。操作名 register_model/register_runtime/register_dataset/create_training_run；资源操作内部名称为 probe_runtime:{id}/cancel:{id}/recover:{id}/selection:{id}。

## 能力投影

`GET /vision-capabilities`：`model_domain=LOCAL_VISUAL_MODELS`, `llm_provider_managed=false`, `supported_registration_tasks=[detect,segment]`, `executable_training_tasks=[detect]`, `training_device=CPU_ONLY`, `registered_model_count`, `registered_runtime_count`, `registered_dataset_count`, `training_ready`, `training_authorization_required=true`, `weight_download_allowed=false`, `ttt_status=DISABLED_NOT_IMPLEMENTED`, `industrial_effectiveness_status=NOT_EVALUATED`。

`training_ready` 只表示已登记可用运行环境和数据；实际启动仍重新验证来源、运行环境、授权及预算。TTT 无标签自监督测试时适应未实现；本接口提供有标签监督训练，不得在 UI 中标为 TTT。

## 工程接入状态

### 验证集反馈与明确续轮（2026-09-13）

完成后的 `run.result` 新增 `validation_feedback_protocol`、`validation_samples_detail`（完整val成员）和 `validation_feedback_candidates`（仅fp/fn非零）。固定confidence=0.25、IoU=0.5、同类别按IoU降序贪心一对一匹配；平局按预测/参考索引。每项绑定sample_id、image_sha256、label_sha256、预测框与置信度、参考框、tp/fp/fn/matches/reason_codes。只对val预测，test不输出错题。

协议含后端dataset_sha256/checkpoint_sha256/runtime_sha256，服务再绑定注册数据集 `dataset_receipt_sha256`、project/run；两种dataset摘要结构不同，不可互换。主服务从冻结bbox再核验GT和matching。旧结果缺少协议时标 `NOT_AVAILABLE_LEGACY_RESULT`，不计作零错误。

run新增 `feedback_ids`, `feedback_status`, `responds_to_feedback_ids`。`GET /vision-training-runs/{run_id}/feedback` 返回封存列表envelope，每项：

```text
resource_id = feedback_id = vfeedback_<24hex>
project_id / run_id / dataset_id / dataset_receipt_sha256
sample_id / split=val / image_sha256 / label_sha256 / checkpoint_sha256
protocol_sha256 / detail（实际预测与reference匹配详情）
status=PENDING_HUMAN_REVIEW / classification=null
issue_closed=false / label_truth_authority=false
training_ingestion_allowed=false / production_release_allowed=false
receipt_sha256
```

`POST /vision-training-runs/{run_id}/feedback/{feedback_id}/triage`，200：公共字段 + `expected_run_sha256`, `expected_feedback_sha256`, `operator_attests_reviewed=true`, `classification=MODEL_ERROR|LABEL_REVIEW_REQUIRED|HARD_SAMPLE|UNKNOWN`。返回该反馈记录 `status=TRIAGED_FOR_REVIEW`，增加 reviewed_by/reviewer_identity/review_note/reviewed_at。人工分类不等于独立标签真值，issue_closed和自动训练摄入仍为false。相同request_key支持查询/重试对账。

下一次 `POST /vision-training-runs` 可带 `responds_to_feedback_ids=[...]` 与 `expected_feedback_receipts={"vfeedback_<24hex>":"<current feedback receipt SHA>"}`。两者键集必须相同，反馈必须同项目、已人工分类且非UNKNOWN；新数据实际receipt必须不同。若旧反馈来自数据池，新输入还必须为新的pool version和新的Gate task；原val/test像素和采集组不能改成train。输入修订经新Gate/Pool审核后再登记到检测数据集，不自动将验证样本回灌训练。新run引用旧feedback只表示显式回应该问题，不自动把它关闭。

### 工作簿数据池桥接（2026-09-13）

`POST /vision-datasets/from-data-pool`，201：公共请求字段加 `pool_id`, `version_id`, `expected_pool_receipt_sha256`, `expected_version_receipt_sha256`, `class_names`, `groups`, `normal_sample_ids=[]`, `operator_attests_data_authorized=true`。不接受本地路径。

服务调用 Goal3 `load_fresh_data_pool_context(... require_current=True, require_all_qualified=True, require_gate_pass=True)`。当前 Pool 和版本必须指向完整、已通过新 Gate 的真实快照，groups 必须精确覆盖所有成员；读取当前 bbox 文档时，要求 asset SHA、annotation revision/document SHA 与冻结快照一致。明确的 label 映射到 class_names，左上角归一化 xywh 转中心归一化 xywh。空框正常样本必须在 normal_sample_ids 显式声明；不会从二值mask反推类别或框。EXIF旋转/多帧未统一坐标前保持HOLD。

`QUALIFIED_CANDIDATE`、子集派生的 `new_gate_status=NOT_STARTED` 均不能作为训练批准。子集必须完成新的 Task/Gate 并绑定到当前 Pool 版本后再导入。返回原 dataset DTO 额外包含 `pool_binding`：绑定当前 Pool/Version/Task/Source/Snapshot/Gate/Readiness、类别、分组、坐标合同及真实标注文档摘要。登记后，训练前、结果发布和人工选择前都重验该绑定；旧版池或标注变化要求重新冻结。

机器可读请求 Schema：[vision_model_requests.v1.json](../schemas/vision_model_requests.v1.json)。权限布尔必须为真正 JSON true/false，数字1不等价于具名授权。

本合同基于新增Python DTO与路由。Goal2宿主身份/挂载及Goal1界面集成需分别验证。当前真实CPU合成smoke已取得检测训练、val、checkpoint，但不代表私域工业数据效果；没有下载预训练权重，没有修改核心环境依赖。

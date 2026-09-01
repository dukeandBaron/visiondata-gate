import type {
  DynamicBenchEvaluationEvidenceProjection,
  DynamicBenchReportEvidence,
  DynamicBenchV3CoreMetrics,
  DynamicBenchV3Evidence,
  DynamicBenchV4CoreMetrics,
  DynamicBenchV4Evidence,
  EvaluationEvidenceRequestScope,
  EvaluationEvidenceScope,
} from "../evaluationEvidenceDomain";
import { OperatorApiError, operatorFetch } from "./api";
import { detachedJcsSha256 } from "./jcs";

const sha256Pattern = /^[0-9a-f]{64}$/;

const projectionKeys = [
  "schema_version",
  "status",
  "availability",
  "verification_status",
  "pair_binding_status",
  "failure_codes",
  "scope",
  "reports",
  "data_scope",
  "factory_metrics_status",
  "factory_shadow_metrics_status",
  "customer_validation_status",
  "production_deployment_status",
  "production_release_allowed",
  "machine_write_permitted",
  "benchmark_truth_feedback_to_agent_runtime",
  "read_only",
  "claim_boundary",
  "projection_hash_profile",
  "projection_sha256",
] as const;

const scopeKeys = [
  "scope_kind",
  "workspace_id",
  "project_id",
  "association_status",
  "read_only",
] as const;

const reportKeys = [
  "version",
  "evidence_role",
  "source_artifact_name",
  "availability",
  "verification_status",
  "verification_error_code",
  "content_sha256",
  "sealed_report_sha256",
  "schema_version",
  "benchmark_id",
  "report_status",
  "verdict",
  "data_source_status",
  "industrial_effectiveness_status",
  "production_deployment_status",
  "production_route",
  "claim_boundary",
  "core_metrics",
] as const;

const v3MetricKeys = [
  "fixture_denominator",
  "paired_record_count",
  "fixed_rule_correct_terminal_disposition_count",
  "dynamic_replanning_correct_terminal_disposition_count",
  "correct_terminal_gain_count",
  "fixed_rule_total_tool_call_count",
  "dynamic_replanning_total_tool_call_count",
  "fixed_rule_unnecessary_tool_call_count",
  "dynamic_replanning_unnecessary_tool_call_count",
  "unnecessary_tool_call_reduction_count",
  "fixed_rule_tool_failure_recovery_rate",
  "dynamic_replanning_tool_failure_recovery_rate",
  "fixed_rule_evidence_changed_adaptation_rate",
  "dynamic_replanning_evidence_changed_adaptation_rate",
  "fixed_rule_unsafe_release_count",
  "dynamic_replanning_unsafe_release_count",
  "actual_model_call_count",
] as const;

const v4MetricKeys = [
  "fixed_fixture_denominator",
  "product_service_execution_count",
  "passed_count",
  "incident_v6_count",
  "decision_packet_v3_count",
  "tool_failure_fixture_count",
  "tool_failure_recovered_fail_closed_count",
  "unsafe_production_release_count",
  "actual_external_model_call_count",
] as const;

function contractFailure(message: string): never {
  throw new OperatorApiError("EVALUATION_EVIDENCE_CONTRACT_DRIFT", message, 502);
}

function requireContract(condition: boolean, message: string): asserts condition {
  if (!condition) contractFailure(message);
}

function record(value: unknown, label: string): Record<string, unknown> {
  requireContract(
    typeof value === "object" && value !== null && !Array.isArray(value),
    `${label} 不是对象`,
  );
  return value as Record<string, unknown>;
}

function rejectUnexpectedKeys(
  value: Record<string, unknown>,
  expectedKeys: readonly string[],
  label: string,
): void {
  const actual = Object.keys(value).sort();
  const expected = [...expectedKeys].sort();
  requireContract(
    actual.length === expected.length && actual.every((key, index) => key === expected[index]),
    `${label} 字段集合漂移`,
  );
}

function stringField(
  value: Record<string, unknown>,
  key: string,
  label: string,
): string {
  const candidate = value[key];
  requireContract(typeof candidate === "string" && candidate.length > 0, `${label}.${key} 无效`);
  return candidate;
}

function nullableStringField(
  value: Record<string, unknown>,
  key: string,
  label: string,
): string | null {
  const candidate = value[key];
  requireContract(candidate === null || (typeof candidate === "string" && candidate.length > 0), `${label}.${key} 无效`);
  return candidate as string | null;
}

function integerField(
  value: Record<string, unknown>,
  key: string,
  label: string,
  minimum = 0,
): number {
  const candidate = value[key];
  requireContract(
    typeof candidate === "number" && Number.isInteger(candidate) && candidate >= minimum,
    `${label}.${key} 必须是大于等于 ${minimum} 的整数`,
  );
  return candidate;
}

function rateField(value: Record<string, unknown>, key: string, label: string): number {
  const candidate = value[key];
  requireContract(
    typeof candidate === "number" && Number.isFinite(candidate) && candidate >= 0 && candidate <= 1,
    `${label}.${key} 必须位于 0 到 1`,
  );
  return candidate;
}

function nullableShaField(
  value: Record<string, unknown>,
  key: string,
  label: string,
): string | null {
  const candidate = value[key];
  requireContract(candidate === null || (typeof candidate === "string" && sha256Pattern.test(candidate)), `${label}.${key} 不是 SHA-256`);
  return candidate as string | null;
}

function parseV3Metrics(value: unknown): DynamicBenchV3CoreMetrics {
  const metrics = record(value, "DynamicBench-v3 metrics");
  rejectUnexpectedKeys(metrics, v3MetricKeys, "DynamicBench-v3 metrics");
  const parsed: DynamicBenchV3CoreMetrics = {
    fixture_denominator: integerField(metrics, "fixture_denominator", "v3 metrics", 1),
    paired_record_count: integerField(metrics, "paired_record_count", "v3 metrics", 1),
    fixed_rule_correct_terminal_disposition_count: integerField(metrics, "fixed_rule_correct_terminal_disposition_count", "v3 metrics"),
    dynamic_replanning_correct_terminal_disposition_count: integerField(metrics, "dynamic_replanning_correct_terminal_disposition_count", "v3 metrics"),
    correct_terminal_gain_count: integerField(metrics, "correct_terminal_gain_count", "v3 metrics"),
    fixed_rule_total_tool_call_count: integerField(metrics, "fixed_rule_total_tool_call_count", "v3 metrics"),
    dynamic_replanning_total_tool_call_count: integerField(metrics, "dynamic_replanning_total_tool_call_count", "v3 metrics"),
    fixed_rule_unnecessary_tool_call_count: integerField(metrics, "fixed_rule_unnecessary_tool_call_count", "v3 metrics"),
    dynamic_replanning_unnecessary_tool_call_count: integerField(metrics, "dynamic_replanning_unnecessary_tool_call_count", "v3 metrics"),
    unnecessary_tool_call_reduction_count: integerField(metrics, "unnecessary_tool_call_reduction_count", "v3 metrics"),
    fixed_rule_tool_failure_recovery_rate: rateField(metrics, "fixed_rule_tool_failure_recovery_rate", "v3 metrics"),
    dynamic_replanning_tool_failure_recovery_rate: rateField(metrics, "dynamic_replanning_tool_failure_recovery_rate", "v3 metrics"),
    fixed_rule_evidence_changed_adaptation_rate: rateField(metrics, "fixed_rule_evidence_changed_adaptation_rate", "v3 metrics"),
    dynamic_replanning_evidence_changed_adaptation_rate: rateField(metrics, "dynamic_replanning_evidence_changed_adaptation_rate", "v3 metrics"),
    fixed_rule_unsafe_release_count: integerField(metrics, "fixed_rule_unsafe_release_count", "v3 metrics"),
    dynamic_replanning_unsafe_release_count: integerField(metrics, "dynamic_replanning_unsafe_release_count", "v3 metrics"),
    actual_model_call_count: integerField(metrics, "actual_model_call_count", "v3 metrics"),
  };
  requireContract(
    parsed.fixed_rule_correct_terminal_disposition_count <= parsed.fixture_denominator &&
      parsed.dynamic_replanning_correct_terminal_disposition_count <= parsed.fixture_denominator,
    "DynamicBench-v3 终态正确数超过冻结夹具分母",
  );
  return parsed;
}

function parseV4Metrics(value: unknown): DynamicBenchV4CoreMetrics {
  const metrics = record(value, "DynamicBench-v4 metrics");
  rejectUnexpectedKeys(metrics, v4MetricKeys, "DynamicBench-v4 metrics");
  const parsed: DynamicBenchV4CoreMetrics = {
    fixed_fixture_denominator: integerField(metrics, "fixed_fixture_denominator", "v4 metrics", 1),
    product_service_execution_count: integerField(metrics, "product_service_execution_count", "v4 metrics"),
    passed_count: integerField(metrics, "passed_count", "v4 metrics"),
    incident_v6_count: integerField(metrics, "incident_v6_count", "v4 metrics"),
    decision_packet_v3_count: integerField(metrics, "decision_packet_v3_count", "v4 metrics"),
    tool_failure_fixture_count: integerField(metrics, "tool_failure_fixture_count", "v4 metrics"),
    tool_failure_recovered_fail_closed_count: integerField(metrics, "tool_failure_recovered_fail_closed_count", "v4 metrics"),
    unsafe_production_release_count: integerField(metrics, "unsafe_production_release_count", "v4 metrics"),
    actual_external_model_call_count: integerField(metrics, "actual_external_model_call_count", "v4 metrics"),
  };
  requireContract(
    parsed.product_service_execution_count <= parsed.fixed_fixture_denominator &&
      parsed.passed_count <= parsed.product_service_execution_count &&
      parsed.incident_v6_count <= parsed.product_service_execution_count &&
      parsed.decision_packet_v3_count <= parsed.product_service_execution_count &&
      parsed.tool_failure_recovered_fail_closed_count <= parsed.tool_failure_fixture_count,
    "DynamicBench-v4 计数关系无效",
  );
  return parsed;
}

function parseReport(
  value: unknown,
  expectedVersion: "v3" | "v4",
): DynamicBenchReportEvidence {
  const report = record(value, `DynamicBench-${expectedVersion} report`);
  rejectUnexpectedKeys(report, reportKeys, `DynamicBench-${expectedVersion} report`);
  requireContract(report.version === expectedVersion, `DynamicBench-${expectedVersion} 版本边界漂移`);
  const expectedRole = expectedVersion === "v3"
    ? "FROZEN_SYNTHETIC_ORCHESTRATION_COMPARISON"
    : "FROZEN_SYNTHETIC_PRODUCTSERVICE_INCIDENT_V6_BRIDGE";
  requireContract(report.evidence_role === expectedRole, `DynamicBench-${expectedVersion} 证据角色漂移`);
  const availability = report.availability;
  const verificationStatus = report.verification_status;
  requireContract(availability === "AVAILABLE" || availability === "UNAVAILABLE", `DynamicBench-${expectedVersion} availability 无效`);
  requireContract(verificationStatus === "VERIFIED" || verificationStatus === "FAILED_CLOSED", `DynamicBench-${expectedVersion} verification_status 无效`);

  const common = {
    source_artifact_name: stringField(report, "source_artifact_name", `DynamicBench-${expectedVersion}`),
    availability,
    verification_status: verificationStatus,
    verification_error_code: nullableStringField(report, "verification_error_code", `DynamicBench-${expectedVersion}`),
    content_sha256: nullableShaField(report, "content_sha256", `DynamicBench-${expectedVersion}`),
    sealed_report_sha256: nullableShaField(report, "sealed_report_sha256", `DynamicBench-${expectedVersion}`),
    schema_version: nullableStringField(report, "schema_version", `DynamicBench-${expectedVersion}`),
    benchmark_id: nullableStringField(report, "benchmark_id", `DynamicBench-${expectedVersion}`),
    report_status: report.report_status,
    verdict: nullableStringField(report, "verdict", `DynamicBench-${expectedVersion}`),
    data_source_status: report.data_source_status,
    industrial_effectiveness_status: report.industrial_effectiveness_status,
    production_deployment_status: report.production_deployment_status,
    production_route: nullableStringField(report, "production_route", `DynamicBench-${expectedVersion}`),
    claim_boundary: nullableStringField(report, "claim_boundary", `DynamicBench-${expectedVersion}`),
  };

  if (availability === "UNAVAILABLE") {
    requireContract(verificationStatus === "FAILED_CLOSED", `DynamicBench-${expectedVersion} 未可用时必须失败关闭`);
    requireContract(common.verification_error_code !== null, `DynamicBench-${expectedVersion} 缺少失败代码`);
    requireContract(
      common.sealed_report_sha256 === null && common.schema_version === null &&
        common.benchmark_id === null && common.report_status === null &&
        common.verdict === null && common.data_source_status === null &&
        common.industrial_effectiveness_status === null &&
        common.production_deployment_status === null && common.production_route === null &&
        common.claim_boundary === null && report.core_metrics === null,
      `DynamicBench-${expectedVersion} 失败关闭投影携带了未经验证的报告字段`,
    );
    if (expectedVersion === "v3") {
      return { version: "v3", evidence_role: expectedRole, ...common, core_metrics: null } as DynamicBenchV3Evidence;
    }
    return { version: "v4", evidence_role: expectedRole, ...common, core_metrics: null } as DynamicBenchV4Evidence;
  }

  requireContract(verificationStatus === "VERIFIED", `DynamicBench-${expectedVersion} 可用报告必须已核验`);
  requireContract(common.verification_error_code === null, `DynamicBench-${expectedVersion} 已核验报告仍携带失败代码`);
  requireContract(common.content_sha256 !== null && common.sealed_report_sha256 !== null, `DynamicBench-${expectedVersion} 缺少双层 SHA`);
  requireContract(common.report_status === "PASS", `DynamicBench-${expectedVersion} 报告状态不是 PASS`);
  requireContract(common.data_source_status === "FROZEN_SYNTHETIC_FIXTURES", `DynamicBench-${expectedVersion} 数据边界漂移`);
  requireContract(common.industrial_effectiveness_status === "NOT_EVALUATED", `DynamicBench-${expectedVersion} 越权声明工业效果`);
  requireContract(common.claim_boundary !== null && common.claim_boundary.length >= 40, `DynamicBench-${expectedVersion} 声明边界缺失`);

  if (expectedVersion === "v3") {
    requireContract(common.schema_version === "visiondata-gate.dynamic-benchmark.v3", "DynamicBench-v3 schema 漂移");
    requireContract(common.benchmark_id === "DynamicBench-v3-dynamic-replanning", "DynamicBench-v3 benchmark_id 漂移");
    requireContract(common.verdict === "DYNAMIC_REPLANNING_ADVANTAGE_OBSERVED_IN_FROZEN_LOCAL_FIXTURES", "DynamicBench-v3 verdict 漂移");
    requireContract(common.production_deployment_status === null && common.production_route === null, "DynamicBench-v3 不得声明生产路径");
    return {
      version: "v3",
      evidence_role: expectedRole,
      ...common,
      core_metrics: parseV3Metrics(report.core_metrics),
    } as DynamicBenchV3Evidence;
  }

  requireContract(common.schema_version === "visiondata-gate.dynamic-benchmark.v4", "DynamicBench-v4 schema 漂移");
  requireContract(common.benchmark_id === "DynamicBench-v4-production-runtime-bridge", "DynamicBench-v4 benchmark_id 漂移");
  requireContract(common.verdict === "PRODUCTION_RUNTIME_BRIDGE_VERIFIED_ON_FROZEN_LOCAL_FIXTURES", "DynamicBench-v4 verdict 漂移");
  requireContract(common.production_deployment_status === "NOT_CONNECTED", "DynamicBench-v4 不得声明生产已连接");
  requireContract(
    common.production_route === "ProductService.run_task_sync->ProductService.create_industrial_incident_case->IncidentKernelV6",
    "DynamicBench-v4 ProductService / Incident v6 路径漂移",
  );
  return {
    version: "v4",
    evidence_role: expectedRole,
    ...common,
    core_metrics: parseV4Metrics(report.core_metrics),
  } as DynamicBenchV4Evidence;
}

function parseScope(
  value: unknown,
  expected: EvaluationEvidenceRequestScope,
): EvaluationEvidenceScope {
  const scope = record(value, "evaluation evidence scope");
  rejectUnexpectedKeys(scope, scopeKeys, "evaluation evidence scope");
  requireContract(scope.read_only === true, "evaluation evidence scope 必须只读");

  if (expected.kind === "GLOBAL_REVIEW") {
    requireContract(
      scope.scope_kind === "GLOBAL_REVIEW" && scope.workspace_id === null &&
        scope.project_id === null && scope.association_status === "GLOBAL_FROZEN_REFERENCE",
      "全局评审证据作用域漂移",
    );
  } else if (expected.kind === "WORKSPACE_REFERENCE") {
    requireContract(
      scope.scope_kind === "WORKSPACE_REFERENCE" &&
        scope.workspace_id === expected.workspaceId && scope.project_id === null &&
        scope.association_status === "REFERENCE_ONLY_NOT_WORKSPACE_DERIVED",
      "工作空间参考证据作用域漂移",
    );
  } else {
    requireContract(
      scope.scope_kind === "PROJECT_REFERENCE" &&
        scope.workspace_id === expected.workspaceId && scope.project_id === expected.projectId &&
        scope.association_status === "REFERENCE_ONLY_NOT_PROJECT_DERIVED",
      "项目参考证据作用域漂移",
    );
  }
  return scope as unknown as EvaluationEvidenceScope;
}

function normalizeEtag(value: string | null): string {
  return value?.trim().replace(/^W\//, "").replace(/^\"|\"$/g, "").toLowerCase() ?? "";
}

function bindProjectionHeaders(response: Response, expectedSha256: string): void {
  const observed = response.headers.get("X-Evaluation-Evidence-SHA256")?.trim().toLowerCase() ?? "";
  const etag = normalizeEtag(response.headers.get("ETag"));
  requireContract(sha256Pattern.test(observed), "X-Evaluation-Evidence-SHA256 缺失或无效");
  requireContract(observed === expectedSha256, "evaluation evidence 响应摘要与投影不一致");
  requireContract(etag === expectedSha256, "evaluation evidence ETag 与投影不一致");
}

export function validateDynamicBenchEvaluationEvidence(
  value: unknown,
  expectedScope: EvaluationEvidenceRequestScope,
): DynamicBenchEvaluationEvidenceProjection {
  const projection = record(value, "DynamicBench evaluation evidence projection");
  rejectUnexpectedKeys(projection, projectionKeys, "DynamicBench evaluation evidence projection");
  requireContract(
    projection.schema_version === "visiondata-gate.dynamicbench-evaluation-evidence-projection.v1",
    "DynamicBench evaluation evidence schema 漂移",
  );
  requireContract(projection.status === "PASS_LOCAL_EVIDENCE" || projection.status === "HOLD", "evaluation evidence status 无效");
  requireContract(projection.availability === "AVAILABLE" || projection.availability === "UNAVAILABLE", "evaluation evidence availability 无效");
  requireContract(projection.verification_status === "VERIFIED" || projection.verification_status === "FAILED_CLOSED", "evaluation evidence verification_status 无效");
  requireContract(
    projection.pair_binding_status === "VERIFIED" ||
      projection.pair_binding_status === "FAILED_CLOSED" ||
      projection.pair_binding_status === "NOT_VERIFIABLE",
    "evaluation evidence pair binding 状态无效",
  );
  requireContract(Array.isArray(projection.failure_codes) && projection.failure_codes.every((code) => typeof code === "string" && code.length > 0), "evaluation evidence failure_codes 无效");
  requireContract(Array.isArray(projection.reports) && projection.reports.length === 2, "evaluation evidence 必须恰好包含 v3 / v4 两份报告");

  const rawV3 = projection.reports.find((report) => record(report, "DynamicBench report").version === "v3");
  const rawV4 = projection.reports.find((report) => record(report, "DynamicBench report").version === "v4");
  requireContract(rawV3 !== undefined && rawV4 !== undefined, "evaluation evidence 缺少唯一的 v3 / v4 配对");
  const v3 = parseReport(rawV3, "v3") as DynamicBenchV3Evidence;
  const v4 = parseReport(rawV4, "v4") as DynamicBenchV4Evidence;
  const scope = parseScope(projection.scope, expectedScope);

  requireContract(projection.data_scope === "FROZEN_SYNTHETIC_FIXTURES", "evaluation evidence 数据范围漂移");
  requireContract(projection.factory_metrics_status === "NOT_MEASURED_BY_DYNAMICBENCH", "DynamicBench 不得声明工厂指标");
  requireContract(projection.factory_shadow_metrics_status === "NOT_MEASURED_PENDING_ADJUDICATION", "工厂影子指标边界漂移");
  requireContract(projection.customer_validation_status === "NOT_CLAIMED", "DynamicBench 不得声明客户验收");
  requireContract(projection.production_deployment_status === "NOT_CONNECTED", "DynamicBench 不得声明生产部署");
  requireContract(projection.production_release_allowed === false, "DynamicBench 不得授权生产放行");
  requireContract(projection.machine_write_permitted === false, "DynamicBench 不得授权设备写入");
  requireContract(projection.benchmark_truth_feedback_to_agent_runtime === false, "评测真值不得回灌 Agent runtime");
  requireContract(projection.read_only === true, "evaluation evidence 投影必须只读");
  requireContract(typeof projection.claim_boundary === "string" && projection.claim_boundary.length >= 80, "evaluation evidence 总声明边界缺失");
  requireContract(projection.projection_hash_profile === "visiondata-gate.rfc8785-jcs-projection-sha256.v1", "evaluation evidence 哈希规范漂移");
  requireContract(typeof projection.projection_sha256 === "string" && sha256Pattern.test(projection.projection_sha256), "evaluation evidence projection SHA 无效");

  const isVerified = projection.status === "PASS_LOCAL_EVIDENCE";
  if (isVerified) {
    requireContract(
      projection.availability === "AVAILABLE" && projection.verification_status === "VERIFIED" &&
        projection.pair_binding_status === "VERIFIED" && projection.failure_codes.length === 0 &&
        v3.availability === "AVAILABLE" && v4.availability === "AVAILABLE",
      "PASS_LOCAL_EVIDENCE 与报告核验状态不一致",
    );
  } else {
    requireContract(
      projection.availability === "UNAVAILABLE" && projection.verification_status === "FAILED_CLOSED" &&
        projection.failure_codes.length > 0 &&
        (projection.pair_binding_status !== "VERIFIED" || v3.availability === "UNAVAILABLE" || v4.availability === "UNAVAILABLE"),
      "HOLD 投影未明确失败关闭",
    );
  }

  return {
    schema_version: "visiondata-gate.dynamicbench-evaluation-evidence-projection.v1",
    status: projection.status,
    availability: projection.availability,
    verification_status: projection.verification_status,
    pair_binding_status: projection.pair_binding_status,
    failure_codes: [...projection.failure_codes],
    scope,
    reports: [v3, v4],
    data_scope: "FROZEN_SYNTHETIC_FIXTURES",
    factory_metrics_status: "NOT_MEASURED_BY_DYNAMICBENCH",
    factory_shadow_metrics_status: "NOT_MEASURED_PENDING_ADJUDICATION",
    customer_validation_status: "NOT_CLAIMED",
    production_deployment_status: "NOT_CONNECTED",
    production_release_allowed: false,
    machine_write_permitted: false,
    benchmark_truth_feedback_to_agent_runtime: false,
    read_only: true,
    claim_boundary: projection.claim_boundary,
    projection_hash_profile: "visiondata-gate.rfc8785-jcs-projection-sha256.v1",
    projection_sha256: projection.projection_sha256,
  };
}

export async function getDynamicBenchEvaluationEvidence(
  scope: EvaluationEvidenceRequestScope,
): Promise<DynamicBenchEvaluationEvidenceProjection> {
  let path = "/v1/review/evaluation-evidence/dynamicbench";
  if (scope.kind !== "GLOBAL_REVIEW") {
    const query = new URLSearchParams();
    if (scope.kind === "PROJECT_REFERENCE") query.set("project_id", scope.projectId);
    const suffix = query.size ? `?${query.toString()}` : "";
    path = `/v1/workspaces/${encodeURIComponent(scope.workspaceId)}/evaluation-evidence/dynamicbench${suffix}`;
  }
  const response = await operatorFetch(path);
  const raw = await response.json() as unknown;
  const projection = validateDynamicBenchEvaluationEvidence(raw, scope);
  const computedSha256 = await detachedJcsSha256(
    raw as Record<string, unknown>,
    "projection_sha256",
  );
  requireContract(
    computedSha256 === projection.projection_sha256,
    "evaluation evidence payload JCS SHA-256 与声明摘要不一致",
  );
  bindProjectionHeaders(response, projection.projection_sha256);
  return projection;
}

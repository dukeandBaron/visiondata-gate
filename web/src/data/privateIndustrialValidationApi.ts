import type {
  FactoryShadowMetrics,
  IndustrialValidationBinding,
  IndustrialValidationRateMetric,
  IndustrialValidationScenarioGroup,
  IndustrialValidationScenarioGroupName,
  IndustrialValidationStrategy,
  IndustrialValidationStrategyResult,
  OmniOfflineValidation,
  PrivateIndustrialValidationSummary,
  VisaPublicProxyValidation,
} from "../privateIndustrialValidationDomain";
import { OperatorApiError, operatorFetch } from "./api";
import { canonicalizeJcs } from "./jcs";

const sha256Pattern = /^[0-9a-f]{64}$/;
const rateKeys = [
  "status", "numerator", "denominator", "value", "wilson_95_lower",
  "wilson_95_upper", "unit_of_analysis", "definition",
  "not_measured_reason_code",
] as const;

function fail(message: string, code = "INDUSTRIAL_VALIDATION_CONTRACT_DRIFT"): never {
  throw new OperatorApiError(code, message, 502);
}

function requireContract(condition: boolean, message: string): asserts condition {
  if (!condition) fail(message);
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  requireContract(
    typeof value === "object" && value !== null && !Array.isArray(value),
    `${label} 不是 JSON object`,
  );
  return value as Record<string, unknown>;
}

function exactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
  label: string,
): void {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  requireContract(
    actual.length === required.length &&
      actual.every((key, index) => key === required[index]),
    `${label} 字段集合漂移`,
  );
}

function nonEmptyString(value: unknown, label: string): string {
  requireContract(typeof value === "string" && value.trim().length > 0, `${label} 无效`);
  return value;
}

function integer(value: unknown, label: string, allowNegative = false): number {
  requireContract(
    Number.isSafeInteger(value) && (allowNegative || Number(value) >= 0),
    `${label} 必须是${allowNegative ? "" : "非负"}整数`,
  );
  return Number(value);
}

function nullableNumber(value: unknown, label: string): number | null {
  requireContract(value === null || (typeof value === "number" && Number.isFinite(value)), `${label} 无效`);
  return value as number | null;
}

function parseRate(value: unknown, label: string): IndustrialValidationRateMetric {
  const rate = objectValue(value, label);
  exactKeys(rate, rateKeys, label);
  requireContract(
    rate.status === "MEASURED" ||
      rate.status === "NOT_MEASURED_PENDING_ADJUDICATION" ||
      rate.status === "NOT_APPLICABLE",
    `${label}.status 无效`,
  );
  const numerator = nullableNumber(rate.numerator, `${label}.numerator`);
  const denominator = nullableNumber(rate.denominator, `${label}.denominator`);
  const measuredValue = nullableNumber(rate.value, `${label}.value`);
  const lower = nullableNumber(rate.wilson_95_lower, `${label}.wilson_95_lower`);
  const upper = nullableNumber(rate.wilson_95_upper, `${label}.wilson_95_upper`);
  if (rate.status === "MEASURED") {
    requireContract(
      numerator !== null && denominator !== null && denominator > 0 &&
        measuredValue !== null && measuredValue >= 0 && measuredValue <= 1 &&
        lower !== null && lower >= 0 && lower <= 1 &&
        upper !== null && upper >= 0 && upper <= 1 && lower <= upper &&
        rate.not_measured_reason_code === null,
      `${label} 的 MEASURED 分母、数值或 Wilson 区间无效`,
    );
  } else {
    requireContract(
      numerator === null && denominator === null && measuredValue === null &&
        lower === null && upper === null &&
        typeof rate.not_measured_reason_code === "string" &&
        rate.not_measured_reason_code.length > 0,
      `${label} 未测量时不得携带数值`,
    );
  }
  nonEmptyString(rate.unit_of_analysis, `${label}.unit_of_analysis`);
  nonEmptyString(rate.definition, `${label}.definition`);
  return rate as unknown as IndustrialValidationRateMetric;
}

function parseBinding(
  value: unknown,
  label: string,
  allowedStatuses: readonly string[],
): IndustrialValidationBinding {
  const binding = objectValue(value, label);
  exactKeys(
    binding,
    [
      "status", "matched_count", "total_count", "drifted_count", "missing_count",
      "mismatched_artifacts", "missing_artifacts",
    ],
    label,
  );
  requireContract(
    typeof binding.status === "string" && allowedStatuses.includes(binding.status),
    `${label}.status 无效`,
  );
  for (const key of ["matched_count", "total_count", "drifted_count", "missing_count"] as const) {
    integer(binding[key], `${label}.${key}`);
  }
  requireContract(
    Number(binding.matched_count) + Number(binding.drifted_count) + Number(binding.missing_count) ===
      Number(binding.total_count),
    `${label} 计数不守恒`,
  );
  for (const key of ["mismatched_artifacts", "missing_artifacts"] as const) {
    requireContract(
      Array.isArray(binding[key]) &&
        binding[key].every((item) => typeof item === "string" && item.length > 0) &&
        JSON.stringify(binding[key]) === JSON.stringify([...binding[key]].sort()),
      `${label}.${key} 无效或未排序`,
    );
  }
  const mismatchedArtifacts = binding.mismatched_artifacts as string[];
  const missingArtifacts = binding.missing_artifacts as string[];
  requireContract(
    Number(binding.drifted_count) === mismatchedArtifacts.length &&
      Number(binding.missing_count) === missingArtifacts.length,
    `${label} 文件清单与计数不一致`,
  );
  return binding as unknown as IndustrialValidationBinding;
}

const strategyNames: readonly IndustrialValidationStrategy[] = [
  "FIXED_SINGLE_ATTEMPT",
  "FIXED_UNIFORM_BOUNDED_RETRY",
  "DYNAMIC_CONTRACT_AWARE_RETRY",
];

function parseStrategy(value: unknown, label: string): IndustrialValidationStrategyResult {
  const strategy = objectValue(value, label);
  exactKeys(
    strategy,
    [
      "execution_strategy", "correct_decision_rate", "false_release_rate",
      "false_block_rate", "transient_recovery_rate", "non_retryable_retry_rate",
      "physical_tool_call_count", "retry_count",
    ],
    label,
  );
  requireContract(
    typeof strategy.execution_strategy === "string" &&
      strategyNames.includes(strategy.execution_strategy as IndustrialValidationStrategy),
    `${label}.execution_strategy 无效`,
  );
  return {
    execution_strategy: strategy.execution_strategy as IndustrialValidationStrategy,
    correct_decision_rate: parseRate(strategy.correct_decision_rate, `${label}.correct_decision_rate`),
    false_release_rate: parseRate(strategy.false_release_rate, `${label}.false_release_rate`),
    false_block_rate: parseRate(strategy.false_block_rate, `${label}.false_block_rate`),
    transient_recovery_rate: parseRate(strategy.transient_recovery_rate, `${label}.transient_recovery_rate`),
    non_retryable_retry_rate: parseRate(strategy.non_retryable_retry_rate, `${label}.non_retryable_retry_rate`),
    physical_tool_call_count: integer(strategy.physical_tool_call_count, `${label}.physical_tool_call_count`),
    retry_count: integer(strategy.retry_count, `${label}.retry_count`),
  };
}

const scenarioNames: readonly IndustrialValidationScenarioGroupName[] = [
  "NORMAL_NO_FAULT",
  "TRANSIENT_RECOVERABLE_FAULT",
  "PERSISTENT_FAULT_SAFETY_COST",
];

function parseScenario(value: unknown, index: number): IndustrialValidationScenarioGroup {
  const label = `visa_public_proxy.scenario_groups[${index}]`;
  const scenario = objectValue(value, label);
  exactKeys(
    scenario,
    [
      "scenario_group", "fault_modes", "episode_denominator",
      "release_allowed_denominator", "block_required_denominator", "strategies",
    ],
    label,
  );
  requireContract(
    typeof scenario.scenario_group === "string" &&
      scenarioNames.includes(scenario.scenario_group as IndustrialValidationScenarioGroupName),
    `${label}.scenario_group 无效`,
  );
  const allowedFaultModes = new Set([
    "NONE",
    "TRANSIENT_TIMEOUT_ONCE",
    "PERMISSION_DENIED_PERSISTENT",
    "TOOL_RESPONSE_INTEGRITY_PERSISTENT",
  ]);
  requireContract(
    Array.isArray(scenario.fault_modes) &&
      scenario.fault_modes.every((item) => typeof item === "string" && allowedFaultModes.has(item)),
    `${label}.fault_modes 无效`,
  );
  requireContract(Array.isArray(scenario.strategies), `${label}.strategies 无效`);
  const strategies = scenario.strategies.map((item, strategyIndex) =>
    parseStrategy(item, `${label}.strategies[${strategyIndex}]`),
  );
  requireContract(
    strategies.length === strategyNames.length &&
      strategies.every((item, strategyIndex) => item.execution_strategy === strategyNames[strategyIndex]),
    `${label}.strategies 顺序或集合漂移`,
  );
  const episodeDenominator = integer(scenario.episode_denominator, `${label}.episode_denominator`);
  const releaseDenominator = integer(scenario.release_allowed_denominator, `${label}.release_allowed_denominator`);
  const blockDenominator = integer(scenario.block_required_denominator, `${label}.block_required_denominator`);
  requireContract(
    episodeDenominator > 0 && releaseDenominator > 0 && blockDenominator > 0 &&
      episodeDenominator === releaseDenominator + blockDenominator,
    `${label} 分母不守恒`,
  );
  return {
    scenario_group: scenario.scenario_group as IndustrialValidationScenarioGroupName,
    fault_modes: scenario.fault_modes as string[],
    episode_denominator: episodeDenominator,
    release_allowed_denominator: releaseDenominator,
    block_required_denominator: blockDenominator,
    strategies,
  };
}

function parseVisa(value: unknown): VisaPublicProxyValidation {
  const visa = objectValue(value, "visa_public_proxy");
  exactKeys(
    visa,
    [
      "evidence_track", "evidence_origin", "recomputable_now", "status", "dataset_id",
      "benchmark_id", "compact_receipt_artifact_name", "compact_receipt_file_sha256",
      "compact_receipt_sha256", "benchmark_file_sha256", "benchmark_report_sha256",
      "implementation_receipt_file_sha256", "implementation_receipt_sha256",
      "dataset_identity_sha256", "source_binding_sha256",
      "programmatic_manifest_sha256", "truth_receipt_sha256",
      "core_component_binding", "project_environment_binding", "dynamic_capability_claim",
      "scenario_groups", "scenario_groups_sha256",
      "configured_intervention_distribution_is_production_prevalence",
      "production_release_allowed", "actual_factory_truth", "claim_boundary",
    ],
    "visa_public_proxy",
  );
  requireContract(visa.evidence_track === "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH", "VisA evidence_track 漂移");
  requireContract(visa.evidence_origin === "CURRENT_ENVIRONMENT_RECOMPUTED_RECEIPT" && visa.recomputable_now === true, "VisA RC5 当前环境复验来源边界漂移");
  requireContract(visa.status === "VERIFIED_CURRENT_ENVIRONMENT_RECOMPUTED", "VisA status 无效");
  requireContract(visa.dataset_id === "VisA", "VisA dataset_id 漂移");
  requireContract(
    visa.benchmark_id === "Public-GovernanceBench-v1-runtime-recovery-v2",
    "VisA benchmark_id 漂移",
  );
  requireContract(
    visa.compact_receipt_artifact_name === "visa_public_proxy_summary.v1.json",
    "VisA compact_receipt_artifact_name 漂移",
  );
  for (const key of [
    "compact_receipt_file_sha256", "compact_receipt_sha256",
    "benchmark_file_sha256", "benchmark_report_sha256",
    "implementation_receipt_file_sha256", "implementation_receipt_sha256",
    "dataset_identity_sha256", "source_binding_sha256",
    "programmatic_manifest_sha256", "truth_receipt_sha256", "scenario_groups_sha256",
  ] as const) {
    requireContract(typeof visa[key] === "string" && sha256Pattern.test(visa[key] as string), `VisA ${key} 无效`);
  }
  requireContract(visa.dynamic_capability_claim === "CONTRACT_AWARE_BOUNDED_RECOVERY_NOT_WORKER_REPLANNING", "VisA 动态能力边界漂移");
  requireContract(
    visa.production_release_allowed === false && visa.actual_factory_truth === false &&
      visa.configured_intervention_distribution_is_production_prevalence === false,
    "VisA 工厂/生产边界漂移",
  );
  nonEmptyString(visa.claim_boundary, "VisA claim_boundary");
  requireContract(Array.isArray(visa.scenario_groups), "VisA scenario_groups 无效");
  const scenarioGroups = visa.scenario_groups.map(parseScenario);
  requireContract(
    scenarioGroups.length === scenarioNames.length &&
      scenarioGroups.every((item, index) => item.scenario_group === scenarioNames[index]),
    "VisA normal/transient/persistent 场景顺序或集合漂移",
  );
  return {
    ...visa,
    core_component_binding: parseBinding(
      visa.core_component_binding,
      "visa_public_proxy.core_component_binding",
      ["MATCHED", "DRIFTED", "UNAVAILABLE"],
    ),
    project_environment_binding: parseBinding(
      visa.project_environment_binding,
      "visa_public_proxy.project_environment_binding",
      ["MATCHED", "DRIFTED_2_OF_2", "DRIFTED", "UNAVAILABLE"],
    ),
    scenario_groups: scenarioGroups,
  } as unknown as VisaPublicProxyValidation;
}

function parseOmni(value: unknown): OmniOfflineValidation {
  const omni = objectValue(value, "omni_offline_validation");
  exactKeys(
    omni,
    [
      "evidence_track", "evidence_origin", "recomputable_now", "status",
      "source_artifact_name", "source_report_file_sha256", "capa_receipt_sha256",
      "original_receipts_available_now",
      "source_profile_image_count", "source_profile_mask_count", "fixed_gate_sample_count",
      "parent_finding_count", "child_finding_count", "finding_count_delta",
      "verified_closed_responsibility_count", "open_responsibility_count",
      "verified_remediation_pass_rate", "factory_shadow_equivalent",
      "production_release_allowed", "not_recomputable_reason_code", "claim_boundary",
    ],
    "omni_offline_validation",
  );
  requireContract(omni.evidence_track === "DATASET_OFFLINE_VALIDATION", "Omni evidence_track 漂移");
  requireContract(omni.evidence_origin === "HISTORICAL_FROZEN_RECEIPT" && omni.recomputable_now === false, "Omni 历史来源边界漂移");
  requireContract(omni.status === "VERIFIED_HISTORICAL_ONLY", "Omni status 无效");
  requireContract(omni.source_artifact_name === "OMNI_CAPA_RC3_RESULT.md", "Omni source_artifact_name 漂移");
  for (const key of ["source_report_file_sha256", "capa_receipt_sha256"] as const) {
    requireContract(typeof omni[key] === "string" && sha256Pattern.test(omni[key] as string), `Omni ${key} 无效`);
  }
  requireContract(omni.original_receipts_available_now === false, "Omni 原始回执可用性边界漂移");
  for (const key of ["source_profile_image_count", "source_profile_mask_count", "fixed_gate_sample_count", "parent_finding_count", "child_finding_count", "verified_closed_responsibility_count", "open_responsibility_count"] as const) {
    integer(omni[key], `omni_offline_validation.${key}`);
  }
  integer(omni.finding_count_delta, "omni_offline_validation.finding_count_delta", true);
  requireContract(omni.factory_shadow_equivalent === false && omni.production_release_allowed === false, "Omni 工厂/生产边界漂移");
  requireContract(
    omni.not_recomputable_reason_code === "ORIGINAL_SOURCE_BYTES_AND_RECEIPTS_NOT_PRESENT_IN_CURRENT_AUTHORITY_TREE",
    "Omni not_recomputable_reason_code 漂移",
  );
  nonEmptyString(omni.claim_boundary, "Omni claim_boundary");
  return {
    ...omni,
    verified_remediation_pass_rate: parseRate(
      omni.verified_remediation_pass_rate,
      "omni_offline_validation.verified_remediation_pass_rate",
    ),
  } as unknown as OmniOfflineValidation;
}

function parseFactory(value: unknown): FactoryShadowMetrics {
  const factory = objectValue(value, "factory_shadow_metrics");
  exactKeys(
    factory,
    [
      "evidence_track", "evidence_origin", "recomputable_now", "status",
      "independent_adjudication_manifest_sha256",
      "customer_shadow_execution_receipt_sha256",
      "false_release_rate", "false_block_rate", "remediation_pass_rate",
      "production_release_allowed", "claim_boundary",
    ],
    "factory_shadow_metrics",
  );
  requireContract(factory.evidence_track === "FACTORY_SHADOW_METRICS", "factory evidence_track 漂移");
  requireContract(factory.evidence_origin === "NO_INDEPENDENT_ADJUDICATION_RECEIPT" && factory.recomputable_now === false, "factory evidence_origin 漂移");
  requireContract(factory.status === "NOT_MEASURED_PENDING_ADJUDICATION", "factory status 无效");
  requireContract(factory.independent_adjudication_manifest_sha256 === null, "factory 不得携带未验证 adjudication SHA");
  requireContract(factory.customer_shadow_execution_receipt_sha256 === null, "factory 不得携带未验证 customer shadow SHA");
  requireContract(factory.production_release_allowed === false, "factory production_release_allowed 必须为 false");
  nonEmptyString(factory.claim_boundary, "factory claim_boundary");
  return {
    ...factory,
    false_release_rate: parseRate(factory.false_release_rate, "factory_shadow_metrics.false_release_rate"),
    false_block_rate: parseRate(factory.false_block_rate, "factory_shadow_metrics.false_block_rate"),
    remediation_pass_rate: parseRate(factory.remediation_pass_rate, "factory_shadow_metrics.remediation_pass_rate"),
  } as unknown as FactoryShadowMetrics;
}

function parseScope(value: unknown): PrivateIndustrialValidationSummary["scope"] {
  const scope = objectValue(value, "scope");
  exactKeys(
    scope,
    ["scope_kind", "workspace_id", "project_id", "association_status", "read_only"],
    "scope",
  );
  requireContract(
    scope.scope_kind === "GLOBAL_REVIEW" ||
      scope.scope_kind === "WORKSPACE_REFERENCE" ||
      scope.scope_kind === "PROJECT_REFERENCE",
    "scope.scope_kind 无效",
  );
  requireContract(scope.read_only === true, "scope.read_only 必须为 true");
  nonEmptyString(scope.association_status, "scope.association_status");
  if (scope.scope_kind === "GLOBAL_REVIEW") {
    requireContract(scope.workspace_id === null && scope.project_id === null, "global scope 不得绑定租户");
    requireContract(scope.association_status === "GLOBAL_FROZEN_REFERENCE", "global association_status 漂移");
  } else if (scope.scope_kind === "WORKSPACE_REFERENCE") {
    nonEmptyString(scope.workspace_id, "scope.workspace_id");
    requireContract(scope.project_id === null, "workspace scope 不得绑定 project_id");
    requireContract(scope.association_status === "REFERENCE_ONLY_NOT_WORKSPACE_DERIVED", "workspace association_status 漂移");
  } else {
    nonEmptyString(scope.workspace_id, "scope.workspace_id");
    nonEmptyString(scope.project_id, "scope.project_id");
    requireContract(scope.association_status === "REFERENCE_ONLY_NOT_PROJECT_DERIVED", "project association_status 漂移");
  }
  return scope as unknown as PrivateIndustrialValidationSummary["scope"];
}

function parseSummary(value: unknown): PrivateIndustrialValidationSummary {
  const summary = objectValue(value, "private industrial validation summary");
  exactKeys(
    summary,
    [
      "schema_version", "status", "availability", "verification_status",
      "failure_codes", "scope", "visa_public_proxy", "omni_offline_validation",
      "factory_shadow_metrics", "production_release_allowed", "machine_write_permitted",
      "read_only", "claim_boundary", "projection_hash_profile", "projection_sha256",
    ],
    "private industrial validation summary",
  );
  requireContract(summary.schema_version === "visiondata-gate.private-industrial-validation-summary.v1", "industrial validation schema 漂移");
  requireContract(
    summary.status === "HOLD" && (
      summary.availability === "CURRENT_PUBLIC_PROXY_WITH_HISTORICAL_OFFLINE_EVIDENCE" ||
      summary.availability === "PUBLIC_PROXY_UNAVAILABLE_WITH_HISTORICAL_OFFLINE_EVIDENCE"
    ),
    "industrial validation HOLD/availability 边界漂移",
  );
  requireContract(summary.verification_status === "VERIFIED_BOUNDED_PROJECTION" || summary.verification_status === "FAILED_CLOSED", "industrial validation verification_status 无效");
  requireContract(Array.isArray(summary.failure_codes) && summary.failure_codes.every((item) => typeof item === "string" && item.length > 0), "industrial validation failure_codes 无效");
  requireContract(
    JSON.stringify(summary.failure_codes) ===
      JSON.stringify([...summary.failure_codes as string[]].sort()) &&
      new Set(summary.failure_codes as string[]).size === (summary.failure_codes as string[]).length,
    "industrial validation failure_codes 必须排序且唯一",
  );
  requireContract(summary.production_release_allowed === false && summary.machine_write_permitted === false && summary.read_only === true, "industrial validation 权限边界漂移");
  requireContract(typeof summary.claim_boundary === "string" && summary.claim_boundary.length >= 40, "industrial validation claim_boundary 缺失");
  requireContract(summary.projection_hash_profile === "visiondata-gate.private-industrial-validation-projection-jcs-sha256.v1", "industrial validation hash profile 漂移");
  requireContract(typeof summary.projection_sha256 === "string" && sha256Pattern.test(summary.projection_sha256), "industrial validation projection SHA 无效");
  const visa = summary.visa_public_proxy === null
    ? null
    : parseVisa(summary.visa_public_proxy);
  if (summary.verification_status === "VERIFIED_BOUNDED_PROJECTION") {
    requireContract(visa !== null, "VERIFIED_BOUNDED_PROJECTION 必须携带 VisA 受控投影");
    requireContract(
      summary.availability === "CURRENT_PUBLIC_PROXY_WITH_HISTORICAL_OFFLINE_EVIDENCE",
      "已验证 VisA RC5 投影的 availability 漂移",
    );
  } else {
    requireContract(visa === null, "FAILED_CLOSED 不得携带 VisA 历史数字");
    requireContract((summary.failure_codes as string[]).length > 0, "FAILED_CLOSED 必须携带 failure_codes");
    requireContract(
      summary.availability === "PUBLIC_PROXY_UNAVAILABLE_WITH_HISTORICAL_OFFLINE_EVIDENCE",
      "失败关闭 VisA 投影的 availability 漂移",
    );
  }
  return {
    ...summary,
    scope: parseScope(summary.scope),
    visa_public_proxy: visa,
    omni_offline_validation: parseOmni(summary.omni_offline_validation),
    factory_shadow_metrics: parseFactory(summary.factory_shadow_metrics),
  } as unknown as PrivateIndustrialValidationSummary;
}

function normalizedEtag(value: string | null): string {
  return value?.trim().replace(/^W\//, "").replace(/^"|"$/g, "").toLowerCase() ?? "";
}

async function domainJcsSha256(domain: string, value: unknown): Promise<string> {
  requireContract(Boolean(globalThis.crypto?.subtle), "Web Crypto SHA-256 不可用");
  const encoder = new TextEncoder();
  const magic = encoder.encode("visiondata-gate.private-industrial-validation.v1\0");
  const domainBytes = encoder.encode(domain);
  requireContract(domainBytes.length <= 0xffff, "industrial validation hash domain 过长");
  const payload = encoder.encode(canonicalizeJcs(value));
  const domainLength = new Uint8Array(2);
  new DataView(domainLength.buffer).setUint16(0, domainBytes.length, false);
  const payloadLength = new Uint8Array(8);
  new DataView(payloadLength.buffer).setBigUint64(0, BigInt(payload.length), false);
  const framed = new Uint8Array(
    magic.length + domainLength.length + domainBytes.length + payloadLength.length + payload.length,
  );
  let offset = 0;
  for (const part of [magic, domainLength, domainBytes, payloadLength, payload]) {
    framed.set(part, offset);
    offset += part.length;
  }
  const digest = await globalThis.crypto.subtle.digest("SHA-256", framed);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function getPrivateIndustrialValidationSummary(
  workspaceId: string,
  projectId: string,
): Promise<PrivateIndustrialValidationSummary> {
  const query = new URLSearchParams({ project_id: projectId });
  const response = await operatorFetch(
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/evaluation-evidence/industrial-validation?${query.toString()}`,
  );
  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    fail("industrial validation 响应不是有效 JSON");
  }
  const summary = parseSummary(raw);
  let observedSha: string;
  try {
    const stable = { ...(raw as Record<string, unknown>) };
    delete stable.projection_sha256;
    observedSha = await domainJcsSha256("industrial-validation-projection", stable);
    if (summary.visa_public_proxy !== null) {
      const observedScenarioSha = await domainJcsSha256(
        "visa-scenario-groups",
        summary.visa_public_proxy.scenario_groups,
      );
      requireContract(
        observedScenarioSha === summary.visa_public_proxy.scenario_groups_sha256,
        "VisA scenario_groups SHA 漂移",
      );
    }
  } catch (caught) {
    fail(
      caught instanceof Error
        ? `industrial validation JCS 复算失败：${caught.message}`
        : "industrial validation JCS 复算失败",
      "INDUSTRIAL_VALIDATION_JCS_FAILED",
    );
  }
  requireContract(observedSha === summary.projection_sha256, "industrial validation payload SHA 漂移");
  requireContract(
    response.headers.get("X-Content-SHA256")?.trim().toLowerCase() === summary.projection_sha256,
    "industrial validation X-Content-SHA256 漂移",
  );
  requireContract(
    normalizedEtag(response.headers.get("ETag")) === summary.projection_sha256,
    "industrial validation ETag 漂移",
  );
  return summary;
}

export type EvaluationEvidenceScopeKind =
  | "GLOBAL_REVIEW"
  | "WORKSPACE_REFERENCE"
  | "PROJECT_REFERENCE";

export type EvaluationEvidenceRequestScope =
  | { kind: "GLOBAL_REVIEW" }
  | { kind: "WORKSPACE_REFERENCE"; workspaceId: string }
  | { kind: "PROJECT_REFERENCE"; workspaceId: string; projectId: string };

export interface DynamicBenchV3CoreMetrics {
  fixture_denominator: number;
  paired_record_count: number;
  fixed_rule_correct_terminal_disposition_count: number;
  dynamic_replanning_correct_terminal_disposition_count: number;
  correct_terminal_gain_count: number;
  fixed_rule_total_tool_call_count: number;
  dynamic_replanning_total_tool_call_count: number;
  fixed_rule_unnecessary_tool_call_count: number;
  dynamic_replanning_unnecessary_tool_call_count: number;
  unnecessary_tool_call_reduction_count: number;
  fixed_rule_tool_failure_recovery_rate: number;
  dynamic_replanning_tool_failure_recovery_rate: number;
  fixed_rule_evidence_changed_adaptation_rate: number;
  dynamic_replanning_evidence_changed_adaptation_rate: number;
  fixed_rule_unsafe_release_count: number;
  dynamic_replanning_unsafe_release_count: number;
  actual_model_call_count: number;
}

export interface DynamicBenchV4CoreMetrics {
  fixed_fixture_denominator: number;
  product_service_execution_count: number;
  passed_count: number;
  incident_v6_count: number;
  decision_packet_v3_count: number;
  tool_failure_fixture_count: number;
  tool_failure_recovered_fail_closed_count: number;
  unsafe_production_release_count: number;
  actual_external_model_call_count: number;
}

interface DynamicBenchReportEvidenceBase {
  source_artifact_name: string;
  availability: "AVAILABLE" | "UNAVAILABLE";
  verification_status: "VERIFIED" | "FAILED_CLOSED";
  verification_error_code: string | null;
  content_sha256: string | null;
  sealed_report_sha256: string | null;
  schema_version: string | null;
  benchmark_id: string | null;
  report_status: "PASS" | null;
  verdict: string | null;
  data_source_status: "FROZEN_SYNTHETIC_FIXTURES" | null;
  industrial_effectiveness_status: "NOT_EVALUATED" | null;
  production_deployment_status: "NOT_CONNECTED" | null;
  production_route: string | null;
  claim_boundary: string | null;
}

export interface DynamicBenchV3Evidence extends DynamicBenchReportEvidenceBase {
  version: "v3";
  evidence_role: "FROZEN_SYNTHETIC_ORCHESTRATION_COMPARISON";
  core_metrics: DynamicBenchV3CoreMetrics | null;
}

export interface DynamicBenchV4Evidence extends DynamicBenchReportEvidenceBase {
  version: "v4";
  evidence_role: "FROZEN_SYNTHETIC_PRODUCTSERVICE_INCIDENT_V6_BRIDGE";
  core_metrics: DynamicBenchV4CoreMetrics | null;
}

export type DynamicBenchReportEvidence =
  | DynamicBenchV3Evidence
  | DynamicBenchV4Evidence;

export interface EvaluationEvidenceScope {
  scope_kind: EvaluationEvidenceScopeKind;
  workspace_id: string | null;
  project_id: string | null;
  association_status:
    | "GLOBAL_FROZEN_REFERENCE"
    | "REFERENCE_ONLY_NOT_WORKSPACE_DERIVED"
    | "REFERENCE_ONLY_NOT_PROJECT_DERIVED";
  read_only: true;
}

export interface DynamicBenchEvaluationEvidenceProjection {
  schema_version: "visiondata-gate.dynamicbench-evaluation-evidence-projection.v1";
  status: "PASS_LOCAL_EVIDENCE" | "HOLD";
  availability: "AVAILABLE" | "UNAVAILABLE";
  verification_status: "VERIFIED" | "FAILED_CLOSED";
  pair_binding_status: "VERIFIED" | "FAILED_CLOSED" | "NOT_VERIFIABLE";
  failure_codes: string[];
  scope: EvaluationEvidenceScope;
  reports: [DynamicBenchV3Evidence, DynamicBenchV4Evidence];
  data_scope: "FROZEN_SYNTHETIC_FIXTURES";
  factory_metrics_status: "NOT_MEASURED_BY_DYNAMICBENCH";
  factory_shadow_metrics_status: "NOT_MEASURED_PENDING_ADJUDICATION";
  customer_validation_status: "NOT_CLAIMED";
  production_deployment_status: "NOT_CONNECTED";
  production_release_allowed: false;
  machine_write_permitted: false;
  benchmark_truth_feedback_to_agent_runtime: false;
  read_only: true;
  claim_boundary: string;
  projection_hash_profile: "visiondata-gate.rfc8785-jcs-projection-sha256.v1";
  projection_sha256: string;
}

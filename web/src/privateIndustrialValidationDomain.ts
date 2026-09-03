export type IndustrialValidationRateStatus =
  | "MEASURED"
  | "NOT_MEASURED_PENDING_ADJUDICATION"
  | "NOT_APPLICABLE";

export interface IndustrialValidationRateMetric {
  status: IndustrialValidationRateStatus;
  numerator: number | null;
  denominator: number | null;
  value: number | null;
  wilson_95_lower: number | null;
  wilson_95_upper: number | null;
  unit_of_analysis: string;
  definition: string;
  not_measured_reason_code: string | null;
}

export type IndustrialValidationStrategy =
  | "FIXED_SINGLE_ATTEMPT"
  | "FIXED_UNIFORM_BOUNDED_RETRY"
  | "DYNAMIC_CONTRACT_AWARE_RETRY";

export interface IndustrialValidationStrategyResult {
  execution_strategy: IndustrialValidationStrategy;
  correct_decision_rate: IndustrialValidationRateMetric;
  false_release_rate: IndustrialValidationRateMetric;
  false_block_rate: IndustrialValidationRateMetric;
  transient_recovery_rate: IndustrialValidationRateMetric;
  non_retryable_retry_rate: IndustrialValidationRateMetric;
  physical_tool_call_count: number;
  retry_count: number;
}

export type IndustrialValidationScenarioGroupName =
  | "NORMAL_NO_FAULT"
  | "TRANSIENT_RECOVERABLE_FAULT"
  | "PERSISTENT_FAULT_SAFETY_COST";

export interface IndustrialValidationScenarioGroup {
  scenario_group: IndustrialValidationScenarioGroupName;
  fault_modes: string[];
  episode_denominator: number;
  release_allowed_denominator: number;
  block_required_denominator: number;
  strategies: IndustrialValidationStrategyResult[];
}

export interface IndustrialValidationBinding {
  status: "MATCHED" | "DRIFTED_2_OF_2" | "DRIFTED" | "UNAVAILABLE";
  matched_count: number;
  total_count: number;
  drifted_count: number;
  missing_count: number;
  mismatched_artifacts: string[];
  missing_artifacts: string[];
}

export interface VisaPublicProxyValidation {
  evidence_track: "PUBLIC_INDUSTRIAL_PROXY_WITH_PROGRAMMATIC_GOVERNANCE_TRUTH";
  evidence_origin: "CURRENT_ENVIRONMENT_RECOMPUTED_RECEIPT";
  recomputable_now: true;
  status: "VERIFIED_CURRENT_ENVIRONMENT_RECOMPUTED";
  dataset_id: "VisA";
  benchmark_id: string;
  compact_receipt_artifact_name: "visa_public_proxy_summary.v1.json";
  compact_receipt_file_sha256: string;
  compact_receipt_sha256: string;
  benchmark_file_sha256: string;
  benchmark_report_sha256: string;
  implementation_receipt_file_sha256: string;
  implementation_receipt_sha256: string;
  dataset_identity_sha256: string;
  source_binding_sha256: string;
  programmatic_manifest_sha256: string;
  truth_receipt_sha256: string;
  core_component_binding: IndustrialValidationBinding;
  project_environment_binding: IndustrialValidationBinding;
  dynamic_capability_claim: "CONTRACT_AWARE_BOUNDED_RECOVERY_NOT_WORKER_REPLANNING";
  scenario_groups: IndustrialValidationScenarioGroup[];
  scenario_groups_sha256: string;
  configured_intervention_distribution_is_production_prevalence: false;
  production_release_allowed: false;
  actual_factory_truth: false;
  claim_boundary: string;
}

export interface OmniOfflineValidation {
  evidence_track: "DATASET_OFFLINE_VALIDATION";
  evidence_origin: "HISTORICAL_FROZEN_RECEIPT";
  recomputable_now: false;
  status: "VERIFIED_HISTORICAL_ONLY";
  source_artifact_name: "OMNI_CAPA_RC3_RESULT.md";
  source_report_file_sha256: string;
  capa_receipt_sha256: string;
  original_receipts_available_now: false;
  source_profile_image_count: number;
  source_profile_mask_count: number;
  fixed_gate_sample_count: number;
  parent_finding_count: number;
  child_finding_count: number;
  finding_count_delta: number;
  verified_closed_responsibility_count: number;
  open_responsibility_count: number;
  verified_remediation_pass_rate: IndustrialValidationRateMetric;
  factory_shadow_equivalent: false;
  production_release_allowed: false;
  not_recomputable_reason_code: "ORIGINAL_SOURCE_BYTES_AND_RECEIPTS_NOT_PRESENT_IN_CURRENT_AUTHORITY_TREE";
  claim_boundary: string;
}

export interface FactoryShadowMetrics {
  evidence_track: "FACTORY_SHADOW_METRICS";
  evidence_origin: "NO_INDEPENDENT_ADJUDICATION_RECEIPT";
  recomputable_now: false;
  status: "NOT_MEASURED_PENDING_ADJUDICATION";
  independent_adjudication_manifest_sha256: null;
  customer_shadow_execution_receipt_sha256: null;
  false_release_rate: IndustrialValidationRateMetric;
  false_block_rate: IndustrialValidationRateMetric;
  remediation_pass_rate: IndustrialValidationRateMetric;
  production_release_allowed: false;
  claim_boundary: string;
}

export interface PrivateIndustrialValidationSummary {
  schema_version: "visiondata-gate.private-industrial-validation-summary.v1";
  status: "HOLD";
  availability:
    | "CURRENT_PUBLIC_PROXY_WITH_HISTORICAL_OFFLINE_EVIDENCE"
    | "PUBLIC_PROXY_UNAVAILABLE_WITH_HISTORICAL_OFFLINE_EVIDENCE";
  verification_status: "VERIFIED_BOUNDED_PROJECTION" | "FAILED_CLOSED";
  failure_codes: string[];
  scope: {
    scope_kind: "GLOBAL_REVIEW" | "WORKSPACE_REFERENCE" | "PROJECT_REFERENCE";
    workspace_id: string | null;
    project_id: string | null;
    association_status: string;
    read_only: true;
  };
  visa_public_proxy: VisaPublicProxyValidation | null;
  omni_offline_validation: OmniOfflineValidation;
  factory_shadow_metrics: FactoryShadowMetrics;
  production_release_allowed: false;
  machine_write_permitted: false;
  read_only: true;
  claim_boundary: string;
  projection_hash_profile: "visiondata-gate.private-industrial-validation-projection-jcs-sha256.v1";
  projection_sha256: string;
}

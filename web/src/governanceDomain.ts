export type GovernanceMetricStatus = "MEASURED" | "NOT_MEASURED" | "NOT_APPLICABLE";

export interface IndustrialShadowBatchIdentity {
  dataset_namespace: string;
  site_alias: string;
  line_alias: string;
  station_alias: string;
  camera_alias: string;
  batch_alias: string;
  captured_from: string;
  captured_to: string;
}

export interface ShadowConfusionCounts {
  unit_of_analysis: string;
  true_block_count: number;
  false_release_count: number;
  true_release_count: number;
  false_block_count: number;
}

export interface ShadowRemediationCounts {
  verified_pass_count: number;
  verified_fail_count: number;
  unresolved_count: number;
}

export interface CreateIndustrialShadowEvaluationInput {
  identity: IndustrialShadowBatchIdentity;
  ground_truth_method:
    | "quality_owner_adjudication"
    | "dual_human_adjudication"
    | "existing_qms_disposition";
  truth_manifest_sha256: string;
  gate_output_manifest_sha256: string;
  confusion: ShadowConfusionCounts;
  remediation: ShadowRemediationCounts;
  note: string;
  operator_attests_authorized_historical_use: true;
  operator_attests_labels_reviewed: true;
  read_only_shadow: true;
  raw_images_transmitted: false;
  machine_write_permitted: false;
}

export interface GovernanceRateMetric {
  key:
    | "false_release_rate"
    | "false_block_rate"
    | "verified_remediation_pass_rate"
    | "unresolved_remediation_rate";
  label: string;
  status: GovernanceMetricStatus;
  numerator: number;
  denominator: number;
  value: number | null;
  unit: "ratio";
  unit_of_analysis: string;
  target: string;
  definition: string;
  source_ref: string;
}

export interface IndustrialShadowEvaluationReceipt {
  schema_version: "visiondata-gate.industrial-shadow-evaluation.v1";
  receipt_id: string;
  request_sha256: string;
  workspace_id: string;
  project_id: string;
  task_id: string;
  source_id: string;
  source_authorization_event_sha256: string;
  task_request_sha256: string;
  task_evidence_sha256: string;
  task_final_decision: string;
  identity: IndustrialShadowBatchIdentity;
  evidence_scope: "OPERATOR_ATTESTED_AUTHORIZED_HISTORICAL_SHADOW";
  label_authority: "OPERATOR_REVIEWED_EXTERNAL_MANIFEST";
  ground_truth_method: CreateIndustrialShadowEvaluationInput["ground_truth_method"];
  truth_manifest_sha256: string;
  gate_output_manifest_sha256: string;
  labelled_unit_count: number;
  confusion: ShadowConfusionCounts;
  remediation: ShadowRemediationCounts;
  false_release_rate: GovernanceRateMetric;
  false_block_rate: GovernanceRateMetric;
  verified_remediation_pass_rate: GovernanceRateMetric;
  unresolved_remediation_rate: GovernanceRateMetric;
  measurement_status: "MEASURED" | "PARTIAL_MEASUREMENT";
  note: string;
  created_by: string;
  created_at: string;
  read_only_shadow: true;
  raw_images_transmitted: false;
  machine_write_permitted: false;
  customer_acceptance_claimed: false;
  production_release_allowed: false;
  claim_boundary: string;
  receipt_sha256: string;
}

export interface ShadowConfusionMetricGroup {
  unit_of_analysis: string;
  receipt_count: number;
  task_count: number;
  labelled_unit_count: number;
  false_release_rate: GovernanceRateMetric;
  false_block_rate: GovernanceRateMetric;
  receipt_ids: string[];
  group_sha256: string;
}

export interface ProjectGovernanceEffectivenessSummary {
  schema_version: "visiondata-gate.project-governance-effectiveness.v1";
  workspace_id: string;
  project_id: string;
  measurement_status: "NOT_MEASURED" | "PARTIAL_MEASUREMENT" | "MEASURED";
  confusion_pooling_status: "NOT_APPLICABLE" | "SINGLE_UNIT" | "GROUPED_BY_UNIT";
  receipt_count: number;
  task_count: number;
  labelled_unit_count: number;
  confusion_groups: ShadowConfusionMetricGroup[];
  verified_remediation_pass_rate: GovernanceRateMetric;
  unresolved_remediation_rate: GovernanceRateMetric;
  receipt_sha256s: Record<string, string>;
  source_manifest_sha256: string;
  raw_images_transmitted: false;
  shadow_labels_enter_agent_core: false;
  production_release_allowed: false;
  claim_boundary: string;
  summary_sha256: string;
}

export type ShadowTruthDisposition = "BLOCK" | "RELEASE";
export type ShadowGateDisposition = "BLOCK" | "RELEASE";
export type ShadowRemediationOutcome =
  | "NOT_APPLICABLE"
  | "UNRESOLVED"
  | "VERIFIED_PASS"
  | "VERIFIED_FAIL";

export interface ShadowEvaluationUnitV2 {
  unit_id: string;
  truth_disposition: ShadowTruthDisposition;
  gate_disposition: ShadowGateDisposition;
  truth_evidence_sha256: string;
  gate_evidence_sha256: string;
  remediation_outcome: ShadowRemediationOutcome;
  remediation_evidence_sha256: string | null;
}

export interface CreateShadowEvaluationManifestV2Input {
  identity: IndustrialShadowBatchIdentity;
  unit_of_analysis: string;
  ground_truth_method: CreateIndustrialShadowEvaluationInput["ground_truth_method"];
  units: ShadowEvaluationUnitV2[];
  note: string;
  operator_attests_authorized_historical_use: true;
  operator_attests_labels_reviewed: true;
}

export interface ShadowEvaluationManifestV2 {
  schema_version: "visiondata-gate.shadow-evaluation-manifest.v2";
  receipt_id: string;
  request_sha256: string;
  workspace_id: string;
  project_id: string;
  task_id: string;
  source_id: string;
  source_authorization_event_sha256: string;
  task_request_sha256: string;
  task_evidence_sha256: string;
  task_final_decision: string;
  source_task_binding_sha256: string;
  identity: IndustrialShadowBatchIdentity;
  unit_of_analysis: string;
  units: ShadowEvaluationUnitV2[];
  labelled_unit_count: number;
  evaluation_manifest_sha256: string;
  truth_manifest_sha256: string;
  gate_output_manifest_sha256: string;
  remediation_manifest_sha256: string;
  evidence_scope: "PER_UNIT_AUTHORIZED_HISTORICAL_SHADOW";
  label_authority: "OPERATOR_REVIEWED_PER_UNIT_EXTERNAL_EVIDENCE";
  aggregation_authority: "VISIONDATA_GATE_SERVER_DERIVED_FROM_PER_UNIT_RECORDS";
  ground_truth_method: CreateIndustrialShadowEvaluationInput["ground_truth_method"];
  confusion: ShadowConfusionCounts;
  remediation: ShadowRemediationCounts;
  false_release_rate: GovernanceRateMetric;
  false_block_rate: GovernanceRateMetric;
  verified_remediation_pass_rate: GovernanceRateMetric;
  unresolved_remediation_rate: GovernanceRateMetric;
  measurement_status: "MEASURED" | "PARTIAL_MEASUREMENT";
  server_computed_counts: true;
  client_supplied_aggregate_counts_accepted: false;
  note: string;
  operator_attests_authorized_historical_use: true;
  operator_attests_labels_reviewed: true;
  created_by: string;
  created_at: string;
  read_only_shadow: true;
  raw_images_transmitted: false;
  machine_write_permitted: false;
  shadow_labels_enter_agent_core: false;
  customer_acceptance_claimed: false;
  production_release_allowed: false;
  claim_boundary: string;
  receipt_sha256: string;
}

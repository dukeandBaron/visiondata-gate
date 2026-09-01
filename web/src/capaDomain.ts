export type ControlledCapaStatus =
  | "SELECTED"
  | "APPROVED"
  | "DERIVED_VERSION_READY"
  | "CHILD_RUN_COMPLETED"
  | "RECOVERED_TO_HUMAN_REVIEW"
  | "STILL_BLOCKED"
  | "TRANSFERRED_TO_INVESTIGATION";

export interface ControlledCapaWorkItem {
  queue_item_id: string;
  work_order_id: string;
  action: string;
  priority: string;
  owner_role: string;
  required_skill: string;
  status: string;
  selected: boolean;
  affected_sample_ids: string[];
  acceptance_criteria: string[];
  status_reason: string;
}

export interface ControlledCapaQueue {
  phase: "initial" | "final";
  items: ControlledCapaWorkItem[];
  open_count: number;
  closed_count: number;
  queue_sha256: string;
  claim_boundary: string;
}

export interface ControlledCapaPlan {
  plan_id: string;
  strategy: "containment_first" | "actionable_recovery" | "full_evidence_closure";
  title: string;
  objective: string;
  selected_work_order_ids: string[];
  deferred_work_order_ids: string[];
  evidence_coverage_ratio: number;
  relative_effort_points: number;
  residual_risk_codes: string[];
  same_contract_child_run_required: true;
  production_release_allowed: false;
  plan_sha256: string;
  claim_boundary: string;
}

export interface ControlledCapaCase {
  schema_version: "visiondata-gate.capa-case.v1";
  case_id: string;
  parent_task_id: string;
  status: ControlledCapaStatus;
  selection: {
    selected_by: string;
    selection_note: string;
    created_at: string;
    selection_sha256: string;
    plan: ControlledCapaPlan;
  };
  approval: null | {
    approved_by: string;
    approval_note: string;
    approved_work_order_ids: string[];
    approved_at: string;
    binding_sha256: string;
    operator_attests_derived_processing: true;
    source_mutation_permitted: false;
    raw_redistribution_allowed: false;
  };
  execution_authorization: null | {
    actor_user_id: string;
    reviewer_identity: string;
    execution_note: string;
    operator_attests_derived_processing: true;
    source_mutation_permitted: false;
    raw_redistribution_allowed: false;
    authorized_at: string;
    authorization_sha256: string;
  };
  initial_queue: ControlledCapaQueue;
  derived_version: null | {
    version_id: string;
    original_selection_count: number;
    derived_image_count: number;
    unresolved_work_order_ids: string[];
    parent_source_mutated: false;
    rollback_strategy: "discard_derived_version";
    receipt_sha256: string;
    claim_boundary: string;
  };
  execution: null | {
    child_task_id: string;
    derived_version_id: string;
    parent_immutable: boolean;
    child_evidence_sha256: string;
    child_lineage_report_sha256: string;
    execution_authorization_sha256?: string | null;
    executed_at: string;
    receipt_sha256: string;
  };
  final_queue: ControlledCapaQueue | null;
  recovery: null | {
    child_task_id: string;
    status: "RECOVERED_TO_HUMAN_REVIEW" | "STILL_BLOCKED" | "TRANSFERRED_TO_INVESTIGATION";
    parent_decision: string;
    child_decision: string;
    resolved_finding_codes: string[];
    new_finding_codes: string[];
    selected_work_order_count: number;
    verified_closed_work_order_count: number;
    remaining_work_order_count: number;
    recovery_success: boolean;
    production_release_allowed: false;
    required_human_action: string;
    receipt_sha256: string;
    claim_boundary: string;
    child_verification: null | {
      strictly_closed_count: number;
      persistent_count: number;
      regressed_count: number;
      is_zero_regression: boolean;
      disposition: string;
      verification_sha256: string;
    };
  };
}

export interface IndustrialEvidenceSource {
  source_type:
    | "image_batch"
    | "mask_annotation"
    | "manifest_metadata"
    | "tool_measurement"
    | "frozen_policy"
    | "operator_authorization";
  evidence_ref: string;
  evidence_sha256: string;
  observed_count: number;
  status: "used" | "operator_attested";
  role_in_decision: string;
}

export interface IndustrialEvidenceFusionEntry {
  entry_id: string;
  issue_code: string;
  sample_ids: string[];
  source_kinds: string[];
  work_order_ids: string[];
  assigned_roles: string[];
  fusion_status:
    | "CROSS_SOURCE_CORROBORATED"
    | "SINGLE_MEASUREMENT_WITH_POLICY_MAPPING";
  root_cause_established: false;
  machine_action_permitted: false;
  entry_sha256: string;
  claim_boundary: string;
}

export interface IndustrialRiskCluster {
  risk_cluster_id: string;
  title: string;
  objective: string;
  action: string;
  priority: string;
  reason_codes: string[];
  finding_ids: string[];
  work_order_ids: string[];
  affected_sample_count: number;
  atomic_work_order_count: number;
  human_owner_role: string;
  required_skill: string;
  machine_action_permitted: false;
  cluster_sha256: string;
  claim_boundary: string;
}

export interface IndustrialRemediationPlan {
  schema_version: "visiondata-gate.industrial-remediation-plan.v1";
  task_id: string;
  run_id: string;
  plan_id: string;
  strategy: "containment_first" | "actionable_recovery" | "full_evidence_closure";
  title: string;
  objective: string;
  selected_work_order_ids: string[];
  deferred_work_order_ids: string[];
  targeted_finding_ids: string[];
  evidence_coverage_ratio: number;
  relative_effort_points: number;
  residual_risk_codes: string[];
  review_eligibility:
    | "containment_only"
    | "partial_recheck_required"
    | "full_closure_recheck_required";
  same_contract_child_run_required: true;
  production_release_allowed: false;
  plan_sha256: string;
  claim_boundary: string;
}

export interface IndustrialDeliveryReceipt {
  schema_version:
    | "visiondata-gate.industrial-delivery.v1"
    | "visiondata-gate.industrial-delivery.v2"
    | "visiondata-gate.industrial-delivery.v3";
  task_id: string;
  run_id: string;
  target_user: string;
  industrial_task: string;
  final_decision: string;
  decision_reason: string;
  multi_source_fusion: IndustrialEvidenceSource[];
  evidence_fusion_matrix: IndustrialEvidenceFusionEntry[];
  risk_clusters: IndustrialRiskCluster[];
  executable_work_orders: Array<{
    work_order_id: string;
    action: string;
    priority: string;
    status: string;
    human_owner_role: string;
    required_skill: string;
    acceptance_criteria: string[];
    machine_action_permitted: false;
  }>;
  remediation_plans: IndustrialRemediationPlan[];
  autonomy_level: "L2_recommendation_only";
  production_human_approval_required: true;
  production_approval_status: "pending";
  source_assets_copied_into_product: boolean;
  unresolved_boundaries: string[];
  claim_boundary: string;
}

export interface CapaOutcomeAssessment {
  schema_version: "visiondata-gate.capa-outcome-assessment.v1";
  case_id: string;
  parent_task_id: string;
  child_task_id: string;
  selected_plan_id: string;
  selected_plan_sha256: string;
  selected_plan_is_highest_coverage: boolean;
  plan_observations: Array<{
    plan_id: string;
    plan_sha256: string;
    strategy: IndustrialRemediationPlan["strategy"];
    selected: boolean;
    execution_status: "EXECUTED" | "NOT_EXECUTED";
    selected_work_order_count: number;
    deferred_work_order_count: number;
    evidence_coverage_ratio: number;
    relative_effort_points: number;
    observed_child_decision: string | null;
    observed_verified_closed_work_order_count: number | null;
    observed_remaining_work_order_count: number | null;
    production_release_allowed: false;
  }>;
  release_feasibility_status:
    | "OBSERVED_RECOVERY_TO_HUMAN_REVIEW"
    | "NOT_ESTIMABLE_HIGHER_COVERAGE_PLAN_UNEXECUTED"
    | "NO_FEASIBLE_RELEASE_OBSERVED_IN_CURRENT_AUTHORIZED_POOL";
  minimum_observed_relative_effort_points: number | null;
  observed_release_candidate_found: boolean;
  required_next_action: string;
  assessment_sha256: string;
  claim_boundary: string;
}

export interface GovernedOutcomeEnvelope {
  schema_version: "visiondata-gate.governed-outcome-envelope.v1";
  subject: {
    parent_task_id: string;
    incident_case_id: string;
    capa_case_id: string;
    child_task_id: string;
  };
  artifacts: Array<{
    artifact_type: string;
    resource_id: string;
    artifact_schema_version: string;
    upstream_integrity_sha256: string;
    content_digest: { value: string };
  }>;
  human_authority: {
    incident_decided_by: string;
    capa_approved_by: string;
    production_decision_authority: "human_only";
    external_release_review_still_required: true;
  };
  result: {
    workflow_status:
      | "RECOVERED_TO_HUMAN_REVIEW"
      | "STILL_BLOCKED"
      | "TRANSFERRED_TO_INVESTIGATION";
    parent_gate_decision: string;
    child_gate_decision: string;
    release_feasibility_status: string;
    selected_work_order_count: number;
    verified_closed_work_order_count: number;
    total_responsibility_item_count: number;
    open_responsibility_item_count: number;
    closed_responsibility_item_count: number;
    root_cause_status: "NOT_ESTABLISHED";
    human_approval_required: true;
    production_release_allowed: false;
    machine_write_permitted: false;
    direct_equipment_control_permitted: false;
    required_human_action: string;
    claim_boundary: string;
  };
  signature: {
    status: "NOT_CONFIGURED";
    signature_algorithm: null;
    key_id: null;
    signature_value: null;
    trusted_timestamp: null;
    assurance_boundary: string;
  };
  claim_boundary: string;
  outcome_root: {
    algorithm: "sha256";
    canonicalization_profile: "rfc8785-jcs-v1";
    hash_domain: string;
    value: string;
  };
}

import type { ProjectSourceKind, ScenarioProfile } from "./domain";

export const publicAgentTools = [
  "image_quality",
  "duplicate_leakage",
  "annotation_integrity",
  "coverage_matrix",
  "governance_audit",
] as const;

export type PublicAgentTool = (typeof publicAgentTools)[number];

export type AgentTaskStatus =
  | "CREATED"
  | "PLANNED"
  | "RUNNING"
  | "VERIFYING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "ARCHIVED";

export interface AgentTask {
  task_id: string;
  workspace_id: string;
  project_id: string;
  created_by: string;
  goal: string;
  seed: number;
  scenario_profile: ScenarioProfile;
  source_kind: ProjectSourceKind;
  source_id: string | null;
  plan_approval_required: boolean;
  allowed_tools: PublicAgentTool[];
  request_sha256: string;
  idempotency_key: string | null;
  execution_status: AgentTaskStatus;
  current_phase: string;
  initial_decision: string | null;
  final_decision: string | null;
  runtime_status: string | null;
  artifact_root_rel: string | null;
  trace_rel: string | null;
  trace_sha256: string | null;
  evidence_zip_rel: string | null;
  evidence_sha256: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export type Goal3HandoffStatus =
  | "WAITING_FOR_TASK_COMPLETION"
  | "BLOCKED_TASK_TERMINAL"
  | "BLOCKED_EVIDENCE_INTEGRITY"
  | "READY_FOR_INCIDENT_INTAKE"
  | "INCIDENT_CHAIN_ACTIVE";

export interface Goal3HandoffReceipt {
  schema_version: "visiondata-gate.goal3-handoff.v1";
  task_id: string;
  workspace_id: string;
  project_id: string;
  task_request_sha256: string;
  task_execution_status: AgentTaskStatus;
  task_final_decision: string | null;
  task_evidence_sha256: string | null;
  task_evidence_integrity: "VERIFIED" | "UNAVAILABLE" | "FAILED";
  source_kind: ProjectSourceKind;
  handoff_status: Goal3HandoffStatus;
  incident_intake_permitted: boolean;
  incident_count: number;
  latest_case_id: string | null;
  latest_case_sha256: string | null;
  latest_case_version: number | null;
  latest_case_status: string | null;
  latest_case_recommendation: string | null;
  required_input_schema: "visiondata-gate.industrial-incident-request.v3";
  accepted_replay_schemas: Array<
    | "visiondata-gate.industrial-incident-request.v1"
    | "visiondata-gate.industrial-incident-request.v2"
  >;
  next_action: string;
  human_authority_required: true;
  production_release_allowed: false;
  machine_write_permitted: false;
  receipt_sha256: string;
  claim_boundary: string;
}

export interface AgentTaskLineageNode {
  task_id: string;
  parent_task_id: string | null;
  depth: number;
  relation: "initial" | "reverification";
  execution_status: AgentTaskStatus;
  final_decision: string | null;
  request_sha256: string;
  evidence_sha256: string | null;
  source_kind: ProjectSourceKind;
  source_id: string | null;
  source_binding_sha256: string | null;
  created_at: string;
  completed_at: string | null;
  is_focus: boolean;
}

export interface AgentTaskLineageEdge {
  schema_version: "visiondata-gate.task-lineage-edge.v1";
  child_task_id: string;
  parent_task_id: string;
  root_task_id: string;
  relation: "reverification";
  depth: number;
  parent_request_sha256: string;
  parent_evidence_sha256: string;
  contract_sha256: string;
  created_by: string;
  note: string;
  created_at: string;
  edge_sha256: string;
}

export interface AgentTaskLineageReport {
  schema_version: "visiondata-gate.task-lineage.v1";
  root_task_id: string;
  focus_task_id: string;
  latest_task_id: string;
  contract_sha256: string;
  node_count: number;
  edge_count: number;
  nodes: AgentTaskLineageNode[];
  edges: AgentTaskLineageEdge[];
  report_sha256: string;
  claim_boundary: string;
}

export interface AgentPlanStep {
  step_id: string;
  phase: string;
  agent_role: string;
  objective: string;
  tool_names: PublicAgentTool[];
  human_gate: boolean;
}

export interface AgentTaskPlan {
  schema_version:
    | "visiondata-gate.task-plan-preview.v1"
    | "visiondata-gate.task-plan-preview.v2";
  task_id: string;
  request_sha256: string;
  before_snapshot_sha256: string;
  plan_sha256: string;
  goal: string;
  scenario_profile: ScenarioProfile;
  source_kind: ProjectSourceKind;
  source_id: string | null;
  source_binding_sha256: string | null;
  allowed_tools: PublicAgentTool[];
  approval_required: boolean;
  steps: AgentPlanStep[];
  dynamic_replanning_policy: string;
  production_authority: "human_only";
  claim_boundary: string;
}

export interface AgentReadinessCheck {
  key: string;
  label: string;
  status: "PASS" | "PENDING" | "BLOCKED" | "NOT_APPLICABLE";
  summary: string;
  evidence_ref: string;
  evidence_sha256: string | null;
}

export interface AgentTaskPreflight {
  schema_version:
    | "visiondata-gate.task-preflight.v1"
    | "visiondata-gate.task-preflight.v2"
    | "visiondata-gate.task-preflight.v3";
  task_id: string;
  source_id?: string | null;
  source_binding_sha256?: string | null;
  lifecycle_status: AgentTaskStatus;
  overall_status:
    | "READY_TO_RUN"
    | "AWAITING_HUMAN_APPROVAL"
    | "BLOCKED"
    | "NOT_RUNNABLE";
  prerequisite_ready: boolean;
  execution_ready: boolean;
  source_profile_status: "MATCHED" | "CHANGED" | "UNAVAILABLE" | "NOT_APPLICABLE";
  frozen_source_profile_sha256?: string | null;
  current_source_profile_sha256?: string | null;
  source_authorization_status:
    | "ACTIVE"
    | "REVOKED"
    | "EXPIRED"
    | "UNAVAILABLE"
    | "NOT_APPLICABLE";
  source_authorization_event_sha256?: string | null;
  plan_sha256: string;
  checks: AgentReadinessCheck[];
  production_authority: "human_only";
  report_sha256: string;
  claim_boundary: string;
}

export type AgentInterventionAction =
  | "approve_plan"
  | "cancel_plan"
  | "acknowledge_result"
  | "request_changes";

export interface AgentIntervention {
  schema_version: "visiondata-gate.task-intervention.v1";
  intervention_id: string;
  task_id: string;
  sequence: number;
  actor_user_id: string;
  action: AgentInterventionAction;
  note: string;
  before_status: AgentTaskStatus;
  before_phase: string;
  before_snapshot_sha256: string;
  plan_sha256: string;
  approval_binding: {
    schema_version: string;
    request_sha256: string;
    before_snapshot_sha256: string;
    plan_sha256: string;
    contract_sha256: string;
    source_profile_status: "MATCHED" | "NOT_APPLICABLE";
    source_profile_sha256: string | null;
    source_authorization_event_sha256: string | null;
    binding_sha256: string;
  } | null;
  created_at: string;
}

export interface AgentTaskEvent {
  task_id: string;
  sequence: number;
  phase: string;
  stage: string;
  status: string;
  summary: string;
  payload_json: string;
  created_at: string;
}

export interface AgentRuntimeProfileCapability {
  profile_id: string;
  label: string;
  provider_kind: string;
  configured_model: string;
  supported_modes: string[];
  availability: "AVAILABLE" | "BLOCKED" | "NOT_CONFIGURED";
  reason_codes: string[];
  raw_image_transmission_supported: false;
}

export interface AgentRuntimeCapabilities {
  schema_version: "visiondata-gate.incident-runtime-capabilities.v1";
  model_profiles: AgentRuntimeProfileCapability[];
  memory_profiles: Array<{
    profile_id: string;
    label: string;
    availability: "AVAILABLE" | "NOT_CONFIGURED";
    reason_codes: string[];
    may_set_current_case_fact: false;
  }>;
  configurable_fields: string[];
  frozen_fields: string[];
  server_policy_sha256: string;
  secrets_exposed: false;
  production_decision_authority: "human_only";
}

export type HostedAgentTeamsOperation = "probe" | "submit_project";

export type HostedAgentTeamsOperationStatus =
  | "CONFIGURED_NOT_CONNECTED"
  | "CONTROLLER_CONNECTED"
  | "CONTROL_PLANE_READY"
  | "PROJECT_REGISTERED"
  | "LEADER_INGRESS_SENT"
  | "REMOTE_EXECUTION_OBSERVED";

export interface HostedAgentTeamsHTTPAttempt {
  attempt: number;
  status:
    | "success"
    | "http_error"
    | "timeout"
    | "transport_error"
    | "redirect_blocked"
    | "invalid_response";
  duration_ms: number;
  retryable: boolean;
  http_status: number | null;
  error_type: string | null;
  backoff_ms: number;
}

export interface HostedAgentTeamsHTTPExchangeReceipt {
  schema_version: "visiondata-gate.http-exchange.v1";
  request_id: string;
  endpoint_id: string;
  endpoint_scope: "local" | "remote";
  method: "GET" | "POST" | "PUT";
  status:
    | "SUCCESS"
    | "RECOVERED"
    | "TIMEOUT"
    | "HTTP_ERROR"
    | "TRANSPORT_ERROR"
    | "REDIRECT_BLOCKED"
    | "INVALID_RESPONSE"
    | "CIRCUIT_OPEN";
  request_sha256: string;
  response_sha256: string | null;
  attempts: HostedAgentTeamsHTTPAttempt[];
  attempt_count: number;
  retry_count: number;
  circuit_before: "closed" | "open" | "half_open";
  circuit_after: "closed" | "open" | "half_open";
  secrets_retained: false;
  redirects_followed: false;
}

export interface HostedAgentTeamsReceipt {
  schema_version: "visiondata-gate.agentteams-hosted-receipt.v2";
  observed_at: string;
  operation: HostedAgentTeamsOperation;
  status: "PASS" | "PARTIAL" | "FAIL";
  operation_status: HostedAgentTeamsOperationStatus;
  provider_repository: "https://github.com/agentscope-ai/AgentTeams";
  provider_version: "v1.2.3";
  provider_commit: "223ddc2b8073e4c8b93bcbb15e1d717f196c04d9";
  controller_reported_version: null;
  mode: "shadow" | "gated";
  team_name: string;
  expected_workers: string[];
  observed_workers: Array<{
    name: string;
    phase: "Running" | "UNEXPECTED";
    role: "team_leader" | "worker" | "UNEXPECTED";
    team: string;
    skills: string[];
    matrix_user_id_present: boolean;
    room_id_present: boolean;
  }>;
  expected_skill_assignments: Record<string, string[]>;
  observed_skill_assignments: Record<string, string[]>;
  checks: Record<string, boolean>;
  controller_connected: boolean;
  team_ready: boolean;
  workers_ready: boolean;
  skill_specs_verified: boolean;
  skill_files_verified: false;
  skill_runtime_verified: false;
  project_registered: boolean;
  leader_ingress_sent: boolean;
  workflow_observed: boolean;
  remote_task_execution_observed: boolean;
  matrix_assignment_verified: false;
  hosted_runtime_verified: false;
  project_id: string | null;
  source_run_id: string | null;
  goal_sha256: string | null;
  approval_id: string | null;
  wait_for_remote_execution: boolean;
  leader_ingress_event_id: null;
  matrix_transaction_sha256: string | null;
  workflow_status_counts: {
    pending: number;
    delegated: number;
    blocked: number;
    revision: number;
    in_progress: number;
    completed: number;
    other: number;
  };
  evidence_projections: Record<string, {
    path: string;
    projection_sha256: string;
    projection_bytes: number;
    source_response_sha256: string;
    source_response_bytes: number;
    evidence_kind: "version" | "team" | "workers" | "project" | "matrix_ingress" | "workflow";
    media_type: "application/json";
  }>;
  transport_receipts: HostedAgentTeamsHTTPExchangeReceipt[];
  reasons: string[];
  boundary: string;
  secrets_retained: false;
  evidence_mode: "allowlisted_projection";
  exact_wire_retained: false;
  opaque_remote_values_retained: false;
  local_runtime_connection_status: "mapped_not_connected";
  receipt_sha256: string;
}

export interface EvidenceBeliefSnapshot {
  hypothesis_id: string;
  source_hypothesis_status: "SUPPORTED" | "PLAUSIBLE" | "UNRESOLVED" | "REJECTED";
  support_status: "SUPPORTED" | "CONTRADICTED" | "UNRESOLVED" | "NOT_SUPPORTED";
  freshness_status: "CURRENT" | "STALE" | "REVOKED" | "UNKNOWN";
  supporting_evidence_refs: string[];
  contradicting_evidence_refs: string[];
  unresolved_evidence_refs: string[];
  unresolved_evidence_count: number;
  snapshot_sha256: string;
}

export interface EvidenceBeliefLedger {
  schema_version: "visiondata-gate.evidence-belief-ledger.v2";
  case_id: string;
  evidence_bundle_sha256: string;
  source_authorization_freshness: {
    freshness_status: "CURRENT" | "STALE" | "REVOKED" | "UNKNOWN";
    source_authorization_status: string;
    current_authorization_status: string;
    facts_sha256: string;
  };
  hypothesis_count: number;
  evidence_edge_count: number;
  snapshots: EvidenceBeliefSnapshot[];
  ledger_sha256: string;
}

export interface WorkerSelectionReceipt {
  schema_version: "visiondata-gate.worker-selection-receipt.v1";
  policy_id: string;
  ordering_contract: string;
  worker_budget: number;
  candidates: Array<{
    worker_id: string;
    eligible: boolean;
    ineligibility_reasons: string[];
    blocking_severity: "NONE" | "WARNING" | "BLOCKING";
    discriminated_hypothesis_ids: string[];
    unresolved_evidence_refs: string[];
    measured_cost_bucket: "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN";
  }>;
  input_sha256: string;
  ranking: Array<{
    worker_id: string;
    eligible: boolean;
    selected: boolean;
    rank: number | null;
    blocking_severity_rank: number;
    hypothesis_discrimination_count: number;
    unresolved_evidence_count: number;
    measured_cost_rank: number;
    exclusion_reasons: string[];
  }>;
  selected_worker_ids: string[];
  receipt_sha256: string;
}

export interface IncidentHypothesisContrast {
  hypothesis_id: string;
  category: string;
  status: string;
  supporting_issue_codes: string[];
  contradicting_issue_codes: string[];
  unresolved_evidence_refs: string[];
  next_discriminating_test: string;
}

export interface IncidentActionContrast {
  action:
    | "CURRENT_RECOMMENDATION"
    | "PRODUCTION_RELEASE"
    | "CLOSE_AS_ROOT_CAUSE_ESTABLISHED"
    | "EXECUTE_CAPA_WITHOUT_OWNER";
  disposition: "SELECTED" | "REJECTED" | "DEFERRED";
  rationale: string;
  evidence_refs: string[];
  change_conditions: string[];
}

export interface WorkerExecutionPlanReceipt {
  schema_version: "visiondata-gate.worker-execution-plan-receipt.v1";
  selection_receipt_sha256: string;
  worker_budget: number;
  requested_priority_order: string[];
  nodes: Array<{
    worker_id: string;
    selection_rank: number;
    dependency_worker_ids: string[];
    requires_successful_dependencies: true;
  }>;
  execution_order: string[];
  dependency_barrier_count: number;
  receipt_sha256: string;
}

export interface CouncilArbitrationReceipt {
  schema_version: "visiondata-gate.council-arbitration-receipt.v1";
  case_id: string;
  belief_ledger_sha256: string;
  worker_execution_plan_sha256: string;
  worker_receipt_sha256s: string[];
  failed_worker_ids: string[];
  examinations: Array<{
    hypothesis_id: string;
    supporting_issue_codes: string[];
    contradicting_issue_codes: string[];
    unresolved_evidence_refs: string[];
    examination_status:
      | "CONFLICT"
      | "UNRESOLVED"
      | "SUPPORTED_ONLY"
      | "CONTRADICTED_ONLY"
      | "NO_QUALIFIED_EVIDENCE";
    root_cause_established: false;
  }>;
  conflict_count: number;
  unresolved_hypothesis_count: number;
  disposition:
    | "BLOCKED_INCOMPLETE_EVIDENCE"
    | "HUMAN_INVESTIGATION_REQUIRED"
    | "PROCEED_WITH_OPEN_GAPS"
    | "PROCEED_NO_CONFLICT";
  policy_directive: "FAIL_CLOSED" | "CONTINUE_HOLD" | "ADVISORY_ONLY";
  root_cause_status: "NOT_ESTABLISHED";
  receipt_sha256: string;
  claim_boundary: string;
}

export interface AutonomyGuardReceipt {
  schema_version: "visiondata-gate.autonomy-guard-receipt.v1";
  case_id: string;
  runtime_profile_sha256: string | null;
  planner_mode: "off" | "shadow" | "gated" | "replay";
  selection_receipt_sha256: string;
  worker_budget: number;
  selected_worker_ids: string[];
  applied_worker_priority_ids: string[];
  model_call_count: number;
  context_budget_enforced: true;
  context_budget_exceeded: boolean;
  deterministic_fallback_used: boolean;
  allowed_model_effect: "NONE" | "ADVISORY_ONLY" | "WORKER_PRIORITY_ONLY";
  model_may_create_findings: false;
  model_may_approve_capa: false;
  model_may_release_production: false;
  model_may_write_machine: false;
  receipt_sha256: string;
}

export interface GovernedIncidentContext {
  context: {
    schema_version: "visiondata-gate.incident-advisor-context.v1";
    case_id: string;
    case_sha256: string;
    site_id: string;
    site_pack_sha256: string;
    current_case_facts: string[];
    current_evidence_gaps: string[];
    relevant_approved_memories: Array<{
      memory_id: string;
      memory_sha256: string;
      memory_type: string;
      pattern: string;
      recommended_first_check: string;
      avoid_first_action: string | null;
      source_case_ids: string[];
      historical_reference_only: true;
      may_set_current_case_fact: false;
      current_case_fact_eligible: false;
    }>;
    available_tools: string[];
    remaining_worker_budget: number;
    frozen_prohibitions: string[];
    precedence: string[];
    historical_memory_used_as_current_fact: false;
    context_sha256: string;
  };
  receipt: {
    schema_version: "visiondata-gate.context-receipt.v1";
    case_id: string;
    case_sha256: string;
    site_id: string;
    site_pack_sha256: string;
    context_sha256: string;
    memory_retrieval_receipt_sha256: string;
    governed_memory_planning_input_sha256: string | null;
    selected_memory_ids: string[];
    cross_site_memory_leakage_count: 0;
    stale_memory_acceptance_count: 0;
    historical_memory_used_as_fact_count: 0;
    may_set_current_case_fact: false;
    raw_prompt_retained: false;
    raw_image_retained: false;
    receipt_sha256: string;
  };
  retrieval_receipt: {
    schema_version:
      | "visiondata-gate.memory-retrieval-receipt.v1"
      | "visiondata-gate.memory-retrieval-receipt.v2";
    query_sha256: string;
    query_scope: {
      site_id: string;
      product_family: string | null;
      line_id: string | null;
      station_id?: string | null;
      camera_id: string | null;
    };
    candidate_count: number;
    eligible_count?: number;
    selected_count: number;
    rejected_count: number;
    selected: Array<{
      rank: number;
      memory_id: string;
      memory_sha256: string;
      selection_reasons: string[];
      source_case_ids: string[];
      lexical_score?: number;
      semantic_score?: number | null;
      historical_reference_only: true;
      may_set_current_case_fact: false;
    }>;
    rejected: Array<{
      memory_id: string;
      memory_sha256: string;
      reason_code: string;
    }>;
    channel_receipts?: Array<{
      channel: "keyword" | "bm25" | "ngram" | "embedding";
      status: "EXECUTED" | "DISABLED" | "UNAVAILABLE_FALLBACK";
      ranked: Array<{ memory_id: string; rank: number; score_micro: number }>;
      warning_code: string | null;
    }>;
    memory_admission_status?:
      | "STRICT_PROMOTION_CHAIN_VERIFIED"
      | "LEGACY_CARD_EXPLICITLY_ALLOWED"
      | "DIRECT_CALL_NOT_ADMISSION_VERIFIED";
    embedding_model_identity?: string;
    semantic_status?: "NOT_CONFIGURED" | "USED" | "FAILED_FALLBACK";
    fallback?: "NONE" | "DETERMINISTIC_LEXICAL";
    accepted_usage: "historical_reference_only";
    may_set_current_case_fact: false;
    policy_judge_input?: false;
    receipt_sha256: string;
  };
  planning_input: {
    schema_version: "visiondata-gate.governed-memory-planning-input.v1";
    planning_subject_sha256: string;
    accepted_historical_references: GovernedIncidentContext["context"]["relevant_approved_memories"];
    allowed_effects: Array<
      | "MISSING_EVIDENCE_PRIORITIZATION"
      | "COUNTEREVIDENCE_QUESTION"
      | "ALLOWLISTED_WORKER_PRIORITY"
    >;
    current_case_fact_authority: "none";
    root_cause_authority: "none";
    decision_authority: "none";
    policy_judge_input: false;
    machine_action_permitted: false;
    input_sha256: string;
  } | null;
}

export type IndustrialIncidentHumanDecision =
  | "CONTINUE_HOLD"
  | "ESCALATE_INVESTIGATION"
  | "SELECT_REMEDIATION_PLAN"
  | "REQUEST_REVERIFICATION"
  | "REJECT_RECOMMENDATION";

export interface IndustrialIncidentDecisionReceipt {
  schema_version: "visiondata-gate.industrial-incident-decision.v1";
  decision_id: string;
  case_id: string;
  case_sha256: string;
  task_id: string;
  actor_user_id: string;
  decision: IndustrialIncidentHumanDecision;
  note: string;
  selected_remediation_plan_id: string | null;
  linked_capa_case_id: string | null;
  decided_at: string;
  production_release_allowed: false;
  equipment_control_allowed: false;
  decision_sha256: string;
  claim_boundary: string;
}

export interface IncidentInteractionTurn {
  sequence: number;
  actor_kind: "AGENT" | "HUMAN";
  actor_id: string;
  action: string;
  input_refs: string[];
  output_refs: string[];
  observable_only: true;
}

export type IncidentQuestionDisposition =
  | "ANSWERED_BY_ADMITTED_EVIDENCE"
  | "SATISFIED_BY_NAMED_HUMAN_DECISION"
  | "REMAINS_OPEN";

export interface IncidentQuestionResolution {
  question_id: string;
  expected_evidence_type: string;
  disposition: IncidentQuestionDisposition;
  supporting_refs: string[];
  auto_closed_from_free_text: false;
}

export interface IncidentInteractionReceipt {
  schema_version: "visiondata-gate.incident-interaction-receipt.v1";
  interaction_id: string;
  task_id: string;
  parent_case_id: string;
  parent_case_sha256: string;
  decision_id: string;
  decision_sha256: string;
  child_case_id: string;
  child_case_sha256: string;
  consumption_sha256: string;
  turns: [IncidentInteractionTurn, IncidentInteractionTurn, IncidentInteractionTurn];
  admitted_evidence_refs: string[];
  question_resolutions: IncidentQuestionResolution[];
  answered_by_evidence_count: number;
  satisfied_by_human_decision_count: number;
  remaining_open_question_count: number;
  interaction_status:
    | "RESUMED_ALL_QUESTIONS_RESOLVED"
    | "RESUMED_WITH_OPEN_QUESTIONS";
  multi_turn_state_transition_verified: true;
  hidden_chain_of_thought_retained: false;
  production_release_allowed: false;
  machine_write_permitted: false;
  receipt_sha256: string;
  claim_boundary: string;
}

export interface IndustrialIncidentCommandResult<T> {
  value: T;
  commandId: string;
  resourceLocation?: string;
  resourceSha256: string;
}

export type IndustrialIncidentCommandStatus =
  | "COMPLETED"
  | "REJECTED"
  | "UNCERTAIN";

export interface IndustrialIncidentCommandReceipt {
  schema_version: "visiondata-gate.incident-command-receipt.v1";
  command_id: string;
  operation: "CREATE_CASE" | "RECORD_DECISION" | "RESUME_CASE";
  task_id: string;
  target_case_id: string | null;
  actor_user_id: string;
  idempotency_key_sha256: string;
  request_sha256: string;
  expected_case_sha256: string | null;
  status: IndustrialIncidentCommandStatus;
  admission_sha256: string;
  terminal_sha256: string | null;
  resource_kind: "incident_case" | "incident_decision" | null;
  resource_id: string | null;
  resource_sha256: string | null;
  error_code: string | null;
  error_message: string | null;
  admitted_at: string;
  terminal_at: string | null;
  boundary_notice: string;
}

export type IncidentPhaseName =
  | "PLAN"
  | "ACT"
  | "OBSERVE"
  | "EVALUATE"
  | "INTERRUPT";

export interface IncidentPhaseEvent {
  schema_version: "visiondata-gate.incident-phase-event.v1";
  event_id: string;
  case_id: string;
  case_sha256: string;
  sequence: number;
  iteration: number;
  phase: IncidentPhaseName;
  invocation_id: string;
  actor: string;
  input_sha256: string;
  output_sha256: string;
  status: "SUCCEEDED" | "FAILED" | "STOPPED" | "PAUSED";
  error_code: string | null;
  retryable: boolean;
  prev_event_sha256: string | null;
  event_sha256: string;
}

export interface IncidentControlPlaneBundle {
  schema_version: "visiondata-gate.incident-control-plane.v1";
  case_id: string;
  case_sha256: string;
  plan_tree: {
    schema_version: "visiondata-gate.typed-incident-plan-tree.v1";
    case_id: string;
    case_sha256: string;
    root_node_id: string;
    nodes: Array<{
      node_id: string;
      node_type:
        | "SEQUENCE"
        | "PARALLEL"
        | "FALLBACK"
        | "GUARD"
        | "INTERRUPT"
        | "REVALIDATE"
        | "WORKER";
      sequence: number;
      goal: string;
      selected: boolean;
      status: "COMPLETED" | "PAUSED" | "SKIPPED" | "FAILED" | "BLOCKED";
      node_sha256: string;
    }>;
    selected_path_node_ids: string[];
    dynamic_worker_budget: number;
    dynamic_workers_executed: number;
    remaining_worker_budget: number;
    execution_semantics: "OBSERVED_CASE_PROJECTION_V1";
    tree_sha256: string;
  };
  authority_ledger: {
    schema_version: "visiondata-gate.incident-authority-ledger.v1";
    case_id: string;
    case_sha256: string;
    initial_state: {
      case_id: string;
      case_sha256: string;
      authority_epoch: number;
      status: "ACTIVE";
      state_sha256: string;
    };
    capability_grants: Array<{
      case_id: string;
      case_sha256: string;
      authority_epoch: number;
      machine_write_permitted: false;
      production_release_permitted: false;
      grant_sha256: string;
    }>;
    accepted_receipts: Array<{
      outcome: "ACCEPTED";
      reason_code: "AUTHORIZED_AT_EPOCH";
      check_sha256: string;
    }>;
    current_state: {
      case_id: string;
      case_sha256: string;
      authority_epoch: number;
      status: "INTERRUPTED";
      state_sha256: string;
    };
    interrupt_reason: string;
    ledger_sha256: string;
  };
  decision_packet: {
    schema_version: "visiondata-gate.contrastive-decision-packet.v1";
    case_id: string;
    case_sha256: string;
    current_status: string;
    current_recommendation: string;
    recommendation_reason: string;
    observed_facts: string[];
    qualified_evidence_refs: string[];
    blocking_issue_codes: string[];
    hypothesis_contrasts: IncidentHypothesisContrast[];
    selected_workers: Array<{
      worker_role: string;
      invocation_id: string;
      trigger_reason_codes: string[];
      receipt_sha256: string;
      result: "SUCCEEDED" | "FAILED";
    }>;
    action_contrasts: IncidentActionContrast[];
    missing_evidence_refs: string[];
    what_would_change_decision: string[];
    maximum_causal_claim_level: "L1_ASSOCIATED" | "L4_INTERVENTION_SUPPORTED";
    root_cause_status: "NOT_ESTABLISHED";
    production_release_allowed: false;
    machine_write_permitted: false;
    plan_tree_sha256: string;
    authority_ledger_sha256: string;
    packet_sha256: string;
  };
  bundle_sha256: string;
  claim_boundary: string;
}

export interface IncidentReviewProjection {
  schema_version: "visiondata-gate.incident-review-projection.v1";
  task_id: string;
  case_id: string;
  case_sha256: string;
  transport_source_mode: "LIVE";
  evidence_source_mode: "REPLAY" | "OFFLINE_EXPORT";
  factory_live_connection_claimed: false;
  worker_budget: number;
  selected_workers: IncidentReviewWorker[];
  rejected_workers: IncidentReviewWorker[];
  triggering_evidence: Array<{
    worker_role: string;
    invocation_id: string;
    status: "SUCCEEDED" | "FAILED";
    trigger_reason_codes: string[];
    input_evidence_sha256: string[];
    receipt_sha256: string;
  }>;
  competing_hypotheses: IncidentHypothesisContrast[];
  missing_evidence_refs: string[];
  what_would_change_decision: string[];
  current_case: IncidentReviewCaseLink;
  parent_case: IncidentReviewCaseLink | null;
  child_cases: IncidentReviewCaseLink[];
  human_decisions: Array<{
    decision_id: string;
    case_id: string;
    case_sha256: string;
    actor_user_id: string;
    decision: string;
    linked_capa_case_id: string | null;
    decision_sha256: string;
    production_release_allowed: false;
    equipment_control_allowed: false;
  }>;
  capa_cases: Array<{
    case_id: string;
    status: string;
    selection_sha256: string;
    approval_binding_sha256: string | null;
    child_task_id: string | null;
    child_evidence_sha256: string | null;
    child_lineage_report_sha256: string | null;
    execution_receipt_sha256: string | null;
    recovery_receipt_sha256: string | null;
  }>;
  missing_linked_capa_case_ids: string[];
  task_lineage_nodes: Array<{
    task_id: string;
    parent_task_id: string | null;
    depth: number;
    execution_status: string;
    final_decision: string | null;
    evidence_sha256: string | null;
  }>;
  task_lineage_report_sha256: string;
  worker_selection_receipt_sha256: string;
  agent_behavior_receipt_sha256: string;
  control_plane_bundle_sha256: string;
  contrastive_decision_packet_sha256: string;
  production_release_allowed: false;
  machine_write_permitted: false;
  projection_sha256: string;
  claim_boundary: string;
}

export interface IncidentReviewWorker {
  worker_id: string;
  eligible: boolean;
  selected: boolean;
  rank: number | null;
  reason_codes: string[];
  blocking_severity: "NONE" | "WARNING" | "BLOCKING";
  discriminated_hypothesis_ids: string[];
  unresolved_evidence_refs: string[];
  measured_cost_bucket: "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN";
  exclusion_reasons: string[];
}

export interface IncidentReviewCaseLink {
  case_id: string;
  case_sha256: string;
  case_version: number;
  status: string;
  recommendation: string;
  parent_case_id: string | null;
  parent_case_sha256: string | null;
  authorizing_decision_id: string | null;
  authorizing_decision_sha256: string | null;
}

export interface IndustrialQualityDecisionPacket {
  schema_version:
    | "visiondata-gate.industrial-quality-decision-packet.v1"
    | "visiondata-gate.industrial-quality-decision-packet.v2"
    | "visiondata-gate.industrial-quality-decision-packet.v3";
  case_id: string;
  case_sha256: string;
  case_version: number;
  control_plane_sha256: string;
  disposition: string;
  recommendation: string;
  recommendation_reason: string;
  root_cause_status: "NOT_ESTABLISHED";
  named_quality_owner_id: string;
  named_quality_owner_role: string;
  evidence_index: Array<{
    evidence_ref: string;
    evidence_type: string;
    evidence_sha256: string;
    qualification: string;
    role_in_decision: string;
    current_case_eligible: boolean;
  }>;
  competing_hypotheses: Array<{
    hypothesis_id: string;
    category: string;
    status: string;
    supporting_issue_codes: string[];
    contradicting_issue_codes: string[];
    unresolved_evidence_refs: string[];
    next_discriminating_test: string;
  }>;
  current_evidence_gaps: string[];
  unresolved_risk_codes: string[];
  worker_selection_receipt?: WorkerSelectionReceipt;
  child_run_status: string;
  external_model_call_count: number;
  opcua_connection_status: string;
  visionmaster_connection_status: string;
  human_approval_required: true;
  production_release_allowed: false;
  machine_write_permitted: false;
  direct_equipment_control_permitted: false;
  packet_sha256: string;
  claim_boundary: string;
}

export interface IncidentRuntimeProfileBinding {
  schema_version: "visiondata-gate.incident-runtime-profile-binding.v1";
  case_id: string;
  case_sha256: string;
  profile: {
    schema_version: "visiondata-gate.incident-runtime-profile.v1";
    model_profile_id:
      | "deterministic-off"
      | "deepseek-chat"
      | "deepseek-replay"
      | "workspace-byok";
    provider_profile_id: string | null;
    planner_mode: "off" | "shadow" | "gated" | "replay";
    temperature: number;
    max_output_tokens: number;
    context_budget_tokens: number;
    memory_mode: "off" | "approved_site";
    memory_top_k: number;
    site_profile_id: string | null;
    human_approval_required: true;
    structured_output_schema: "visiondata-gate.incident-model-plan.v1";
  };
  profile_sha256: string;
  planner_config_sha256: string | null;
  planner_connection_status: string;
  governed_context_receipt_sha256: string | null;
  governed_memory_planning_input_sha256: string | null;
  governed_memory_retrieval_receipt_sha256: string | null;
  selected_memory_count: number;
  rejected_memory_count: number;
  model_context_limit: number | null;
  context_limit_status: "NOT_APPLICABLE" | "UNVERIFIED";
  binding_sha256: string;
  secrets_retained: false;
  raw_images_transmitted: false;
  production_decision_authority: "human_only";
}

export interface IncidentAuditDigest {
  algorithm: "sha256";
  canonicalization_profile: "rfc8785-jcs-v1";
  framing_profile: "visiondata-gate-domain-frame-v1";
  hash_domain: string;
  value: string;
}

export interface GovernedAuditEnvelope {
  schema_version: "visiondata-gate.governed-audit-envelope.v1";
  protocol: {
    protocol_id: "visiondata-gate.governed-audit-envelope.v1";
    digest_algorithm: "sha256";
    canonicalization_profile: "rfc8785-jcs-v1";
    framing_profile: "visiondata-gate-domain-frame-v1";
  };
  issuer: {
    issuer_type: "VISIONDATA_GATE_PRODUCT_SERVICE";
    actor_id: string;
    workspace_id: string;
    project_id: string;
    identity_assurance: "LOCAL_APPLICATION_RECORD_ONLY";
  };
  subject: {
    subject_type: "IndustrialIncidentCase";
    case_id: string;
    task_id: string;
    case_schema_version: string;
    legacy_case_sha256: string;
    audit_digest: IncidentAuditDigest;
  };
  phase_events: Array<{
    sequence: number;
    event_id: string;
    legacy_event_sha256: string;
    audit_digest: IncidentAuditDigest;
  }>;
  governance: Array<{
    artifact_type:
      | "RUNTIME_PROFILE_BINDING"
      | "SITE_PACK"
      | "GOVERNED_CONTEXT"
      | "CONTROL_PLANE";
    status: "BOUND" | "NOT_APPLICABLE";
    legacy_sha256: string | null;
    audit_digest: IncidentAuditDigest | null;
  }>;
  result: {
    schema_version: "visiondata-gate.incident-policy-contract.v1";
    case_status: string;
    recommendation: string;
    root_cause_status: "NOT_ESTABLISHED";
    human_approval_required: true;
    production_release_allowed: false;
    machine_write_permitted: false;
    direct_equipment_control_permitted: false;
    policy_contract_fingerprint: IncidentAuditDigest;
    claim_boundary: string;
  };
  signature: {
    status: "NOT_CONFIGURED";
    signature_algorithm: null;
    key_id: null;
    signature_value: null;
    trusted_timestamp: null;
    assurance_boundary: "DIGEST_INTEGRITY_ONLY_NO_SIGNER_IDENTITY_OR_TRUSTED_TIME";
  };
  claim_boundary: "TAMPER_EVIDENT_DETERMINISTIC_LINEAGE_NOT_CAUSAL_PROOF_OR_CERTIFICATION";
  audit_root: IncidentAuditDigest;
}

export interface IndustrialIncidentAuthoritySnapshot {
  phaseEvents: IncidentPhaseEvent[];
  controlPlane: IncidentControlPlaneBundle;
  decisionPacket: IndustrialQualityDecisionPacket;
  reviewProjection: IncidentReviewProjection;
  auditEnvelope: GovernedAuditEnvelope;
  runtimeProfileBinding: IncidentRuntimeProfileBinding;
}

export interface IndustrialIncidentEvidenceIssue {
  issue_code: string;
  severity: "BLOCKING" | "WARNING";
  evidence_source: string;
  summary: string;
  required_evidence_or_action: string;
  worker_role: string;
  blocks_disposition: boolean;
  producer_type: "WORKER_RECEIPT" | "DETERMINISTIC_PREFLIGHT";
  producer_invocation_id: string | null;
  producer_receipt_sha256: string | null;
  input_evidence_refs: string[];
}

export interface IndustrialIncident {
  schema_version:
    | "visiondata-gate.industrial-incident-case.v5"
    | "visiondata-gate.industrial-incident-case.v6";
  case_id: string;
  incident_root_id: string;
  case_version: number;
  parent_case_id: string | null;
  parent_case_sha256: string | null;
  authorizing_decision_id: string | null;
  authorizing_decision_sha256: string | null;
  task_id: string;
  request: {
    schema_version:
      | "visiondata-gate.industrial-incident-request.v1"
      | "visiondata-gate.industrial-incident-request.v2"
      | "visiondata-gate.industrial-incident-request.v3";
    trigger: {
      trigger_kind: string;
      triggered_at: string;
      operator_message: string;
      product_id: string;
      part_id: string | null;
      recipe_id: string;
      configuration_id: string;
      batch_id: string | null;
      lot_reference: string | null;
      work_order_id: string | null;
      line_id: string | null;
      baseline_ng_rate: number | null;
      observed_ng_rate: number | null;
      sample_count: number;
    };
    opcua_snapshot: {
      source_mode: "FIXTURE_REPLAY" | "OFFLINE_EXPORT";
      captured_at: string;
      real_endpoint_connected: false;
      read_only: true;
      machine_write_permitted: false;
    };
    operator_attests_inputs_authorized: true;
    raw_industrial_data_redistribution_allowed: false;
    supersedes_case_id: string | null;
    expected_parent_case_sha256: string | null;
    authorizing_decision_id: string | null;
    [key: string]: unknown;
  };
  status: string;
  recommendation: string;
  recommendation_reason: string;
  planning_mode: string;
  root_cause_status: "NOT_ESTABLISHED";
  external_model_call_count: number;
  human_approval_required: true;
  production_release_allowed: false;
  machine_write_permitted: false;
  direct_equipment_control_permitted: false;
  planning_belief_ledger: EvidenceBeliefLedger;
  worker_selection_receipt: WorkerSelectionReceipt;
  parent_belief_revision_receipt?: {
    disposition: string;
    fresh_replan_required: boolean;
    fail_closed: boolean;
    receipt_sha256: string;
  } | null;
  worker_execution_plan_receipt?: WorkerExecutionPlanReceipt | null;
  council_arbitration_receipt?: CouncilArbitrationReceipt | null;
  autonomy_guard_receipt?: AutonomyGuardReceipt | null;
  governed_memory_planning_input_sha256?: string | null;
  governed_memory_retrieval_receipt_sha256?: string | null;
  evidence_issues: IndustrialIncidentEvidenceIssue[];
  decision_summary: {
    observed_facts: string[];
    alternatives_kept_open: string[];
    prohibited_conclusions: string[];
    unresolved_reason_codes: string[];
    next_safe_action: string;
  };
  loop_control: {
    max_iterations: number;
    current_iteration: number;
    dynamic_worker_budget: number;
    dynamic_workers_executed: number;
    remaining_worker_budget: number;
    stop_reason: string;
    can_resume: boolean;
    resume_requires: string[];
  };
  operator_questions: Array<{
    question_id: string;
    prompt: string;
    reason_codes: string[];
    expected_evidence_type: string;
    required: boolean;
    status: string;
  }>;
  linked_remediation_plan_ids: string[];
  agent_actions: Array<{
    sequence: number;
    iteration: number;
    agent_role: string;
    action: string;
    status: "COMPLETED" | "DISPATCHED" | "PENDING_HUMAN" | "STOPPED" | "FAILED";
    dynamic: boolean;
    reason_codes: string[];
    input_refs: string[];
    expected_output: string;
    tool_contracts: string[];
    output_receipt_sha256: string | null;
    machine_action_permitted: false;
  }>;
  worker_receipts: Array<{
    schema_version: "visiondata-gate.incident-worker-receipt.v1";
    invocation_id: string;
    iteration: number;
    worker_role: string;
    worker_version: string;
    status: "SUCCEEDED" | "FAILED";
    attempt: number;
    trigger_reason_codes: string[];
    input_evidence_sha256: string[];
    tool_contracts: string[];
    output_issues: IndustrialIncidentEvidenceIssue[];
    observations: string[];
    output_artifact_sha256: string;
    error_code: string | null;
    retryable: boolean;
    receipt_sha256: string;
  }>;
  evidence_bundle_sha256: string;
  context_sha256: string;
  opcua_connection_status:
    | "OPC_UA_REAL_ENDPOINT_NOT_CONNECTED"
    | "OPC_UA_FIXTURE_REPLAY_ONLY";
  visionmaster_connection_status: "VISIONMASTER_SDK_NOT_CONNECTED";
  case_sha256: string;
  claim_boundary: string;
}

/** @deprecated Use IndustrialIncident. Kept for source compatibility only. */
export type IndustrialIncidentV5 = IndustrialIncident;

export type AgentCapaStatus =
  | "SELECTED"
  | "APPROVED"
  | "DERIVED_VERSION_READY"
  | "CHILD_RUN_COMPLETED"
  | "RECOVERED_TO_HUMAN_REVIEW"
  | "STILL_BLOCKED"
  | "TRANSFERRED_TO_INVESTIGATION";

export interface AgentCapaLineageRecord {
  schema_version: "visiondata-gate.capa-case.v1";
  case_id: string;
  parent_task_id: string;
  status: AgentCapaStatus;
  selection: {
    schema_version: "visiondata-gate.capa-selection.v1";
    case_id: string;
    parent_task_id: string;
    parent_request_sha256: string;
    parent_evidence_sha256: string;
    industrial_delivery_sha256: string;
    selected_by: string;
    selection_note: string;
    created_at: string;
    selection_sha256: string;
  };
  approval: {
    schema_version:
      | "visiondata-gate.capa-approval-binding.v1"
      | "visiondata-gate.capa-approval-binding.v2"
      | "visiondata-gate.capa-approval-binding.v3";
    case_id: string;
    parent_task_id: string;
    approved_by: string;
    approval_note: string;
    operator_attests_derived_processing: true;
    source_mutation_permitted: false;
    approved_at: string;
    binding_sha256: string;
  } | null;
  initial_queue: {
    schema_version: "visiondata-gate.capa-responsibility-queue.v1";
    case_id: string;
    parent_task_id: string;
    phase: "initial";
    open_count: number;
    closed_count: number;
    queue_sha256: string;
    claim_boundary: string;
  };
  derived_version: {
    schema_version: "visiondata-gate.derived-data-version.v1";
    case_id: string;
    version_id: string;
    parent_task_id: string;
    parent_source_mutated: false;
    source_assets_copied_into_product: true;
    public_export_allowed: false;
    receipt_sha256: string;
    claim_boundary: string;
  } | null;
  execution: {
    schema_version: "visiondata-gate.capa-execution.v1";
    case_id: string;
    parent_task_id: string;
    child_task_id: string;
    derived_version_id: string;
    derived_source_id: string;
    remediation_plan_sha256: string;
    capa_approval_binding_sha256: string;
    child_plan_approval_binding_sha256: string;
    parent_evidence_sha256_before: string;
    parent_evidence_sha256_after: string;
    parent_source_profile_sha256_before: string;
    parent_source_profile_sha256_after: string;
    parent_immutable: boolean;
    child_evidence_sha256: string;
    child_lineage_report_sha256: string;
    executed_at: string;
    receipt_sha256: string;
  } | null;
  final_queue: {
    schema_version: "visiondata-gate.capa-responsibility-queue.v1";
    case_id: string;
    parent_task_id: string;
    phase: "final";
    open_count: number;
    closed_count: number;
    queue_sha256: string;
    claim_boundary: string;
  } | null;
  recovery: {
    schema_version:
      | "visiondata-gate.capa-recovery.v1"
      | "visiondata-gate.capa-recovery.v2";
    case_id: string;
    parent_task_id: string;
    child_task_id: string;
    status:
      | "RECOVERED_TO_HUMAN_REVIEW"
      | "STILL_BLOCKED"
      | "TRANSFERRED_TO_INVESTIGATION";
    parent_decision: string;
    child_decision: string;
    recovery_success: boolean;
    production_release_allowed: false;
    required_human_action: string;
    parent_evidence_sha256: string;
    child_evidence_sha256: string;
    receipt_sha256: string;
    claim_boundary: string;
  } | null;
}

export interface AgentReleaseReadiness {
  schema_version: "visiondata-gate.release-readiness.v1";
  task_id: string;
  overall_status:
    | "READY_FOR_HUMAN_REVIEW"
    | "BLOCKED_GATE_DECISION"
    | "BLOCKED_SOURCE_STALE"
    | "BLOCKED_EVIDENCE_INTEGRITY"
    | "DEMO_ONLY";
  final_gate_decision: string;
  evidence_sha256: string | null;
  evidence_integrity: "VERIFIED" | "FAILED";
  source_freshness: "CURRENT" | "STALE" | "UNAVAILABLE" | "NOT_APPLICABLE";
  open_work_order_count: number | null;
  checks: AgentReadinessCheck[];
  production_release_allowed: false;
  required_human_action: string;
  report_sha256: string;
  claim_boundary: string;
}

export interface LocalTaskSource {
  source_id: string;
  workspace_id: string;
  display_name: string;
  status: "active" | "revoked" | "expired";
  source_kind: "local_authorized_directory";
  adapter_kind: "omni_ad_30_release" | "operator_project_snapshot";
  source_archive_sha256: string;
  root_path_sha256: string;
  source_assets_copied_into_product: boolean;
  data_profile: Record<string, unknown>;
  authorization_valid_until: string | null;
  authorization_event_count: number;
  latest_authorization_event_type: "GRANTED" | "REVOKED" | "EXPIRED";
  latest_authorization_event_sha256: string;
  created_at: string;
  claim_boundary: string;
}

export interface SourceAuthorizationEvent {
  schema_version: "visiondata-gate.source-authorization-event.v1";
  event_id: string;
  source_id: string;
  workspace_id: string;
  sequence: number;
  event_type: "GRANTED" | "REVOKED" | "EXPIRED";
  actor_kind: "operator" | "system";
  actor_id: string;
  reason: string;
  effective_at: string;
  created_at: string;
  previous_event_sha256: string | null;
  fail_closed_task_ids: string[];
  event_sha256: string;
  claim_boundary: string;
}

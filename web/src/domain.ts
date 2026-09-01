export type StatusTone =
  | "neutral"
  | "info"
  | "success"
  | "warning"
  | "danger"
  | "locked";

export type EvidenceSource = "LIVE_API" | "FROZEN_FIXTURE" | "LOCAL_CONTRACT" | "NOT_CONNECTED";

export type GateStatus =
  | "PASS"
  | "PASS_LOCAL"
  | "RECAPTURE"
  | "HOLD"
  | "TRANSFERRED_TO_INVESTIGATION"
  | "NOT_EVALUATED";

export interface ReleaseState {
  developmentState: "RC3_FROZEN_LOCAL";
  releaseState: "LOCAL_RELEASE_CANDIDATE";
  releaseCandidateReady: true;
  submissionEligible: false;
  localDecision: "PASS_LOCAL_RC3_RELEASE_CANDIDATE";
  officialSubmission: "PENDING";
  officialEvaluation: "NOT_EVALUATED";
  productionReleaseAllowed: false;
  updatedAt: string;
}

export interface StatItem {
  label: string;
  value: string;
  detail?: string;
}

export interface DatasetOption {
  id: string;
  title: string;
  subtitle: string;
  kind: "AUTHORIZED_LOCAL" | "FROZEN_PUBLIC" | "SYNTHETIC" | "NEW_SOURCE";
  source: EvidenceSource;
  access: string;
  status: string;
  statusTone: StatusTone;
  selectedByDefault?: boolean;
  available: boolean;
  stats: StatItem[];
  claimBoundary: string;
}

export interface CaseRecord {
  id: string;
  displayId: string;
  title: string;
  dataset: string;
  namespace: string;
  status: GateStatus;
  stage: string;
  findings: number;
  responsibilityOpen: number;
  responsibilityClosed: number;
  workOrders: number | null;
  owner: string;
  updatedAt: string;
  parentId?: string;
  childId?: string;
  productionReleaseAllowed: false;
  source: EvidenceSource;
  scopeNote: string;
}

export type FindingSeverity = "CRITICAL" | "MAJOR" | "MINOR" | "INFO";

export interface FindingRecord {
  id: string;
  code: string;
  title: string;
  family: string;
  severity: FindingSeverity;
  namespace: string;
  evidenceScope: string;
  measurement: string;
  threshold: string;
  disposition: string;
  owner: string;
  receiptId: string;
  state: "OPEN" | "CLOSED" | "INVESTIGATE";
  source: EvidenceSource;
  isAggregateOnly?: boolean;
}

export interface ToolReceipt {
  id: string;
  tool: string;
  role: string;
  state: "COMPLETED" | "BLOCKED" | "NOT_CONNECTED";
  duration: string;
  reason: string;
  authority: string;
  digest: string;
  source: EvidenceSource;
}

export interface RunRecord {
  id: string;
  namespace: string;
  title: string;
  status: GateStatus;
  input: string;
  findings: string;
  toolReceipts: number;
  replan: number;
  dynamicWorkers: number;
  modelCalls: number;
  startedAt: string;
  source: EvidenceSource;
  note: string;
}

export interface CapaPlan {
  id: string;
  title: string;
  coverage: string;
  responsibilityItems: number;
  executed: boolean;
  state: "NOT_EXECUTED" | "EXECUTED_NO_RELEASE";
  actions: string[];
  constraint: string;
}

export interface IntegrationRecord {
  id: string;
  name: string;
  category: "ANNOTATION" | "DATA" | "API" | "MODEL" | "AGENT" | "FORMAT";
  state:
    | "LOCAL_CONTRACT_VERIFIED"
    | "CONTRACT_READY_NOT_CONNECTED"
    | "LOCAL_API_AVAILABLE"
    | "ADAPTER_SDK_AVAILABLE"
    | "MAPPED_NOT_CONNECTED"
    | "NOT_TESTED";
  tone: StatusTone;
  protocol: string;
  capability: string;
  boundary: string;
  source: EvidenceSource;
}

export interface LineageNode {
  id: string;
  label: string;
  kind: "PARENT" | "HUMAN_DECISION" | "DERIVED" | "CHILD" | "OUTCOME";
  state: string;
  detail: string;
  digest?: string;
}

export interface BenchmarkRecord {
  id: string;
  title: string;
  denominator: string;
  result: string;
  boundary: string;
  tone: StatusTone;
}

export interface ReviewerSnapshotApi {
  schema_version: "visiondata-gate.reviewer-workbench.v1";
  case: Record<string, unknown>;
  public_pilot: Record<string, unknown>;
  synthetic_visual: Record<string, unknown>;
  phases: unknown[];
  runtime: Record<string, unknown>;
  snapshot_integrity: { sha256: string };
  external_model: {
    base_url?: string;
    mode?: string;
    key_configured?: boolean;
    connection_status?: string;
  };
}

export interface RuntimeConnectionState {
  api: "CONNECTED" | "UNAVAILABLE" | "CHECKING";
  reviewer: "CONNECTED" | "FALLBACK" | "CHECKING";
  apiBaseUrl: string;
  reviewerBaseUrl: string;
  checkedAt?: string;
  reviewerSnapshotSha256?: string;
}

export interface WorkspaceRecord {
  workspace_id: string;
  name: string;
  owner_user_id: string;
  role: string;
  created_at: string;
}

export type ScenarioProfile =
  | "generic"
  | "industrial"
  | "automotive"
  | "finance"
  | "education"
  | "wearable";

export type ProjectSourceKind =
  | "synthetic_demo"
  | "local_authorized_directory"
  | "external_residency_reference";

export interface ProjectRecord {
  project_id: string;
  workspace_id: string;
  name: string;
  description: string;
  scenario_profile: ScenarioProfile;
  source_kind: ProjectSourceKind;
  created_at: string;
  updated_at: string;
}

export type ProviderKind =
  | "deepseek"
  | "openai"
  | "opentoken"
  | "openai_compatible"
  | "ollama_local";

export interface ProviderProfileRecord {
  schema_version: "visiondata-gate.provider-profile.v1";
  profile_id: string;
  workspace_id: string;
  owner_user_id: string;
  display_name: string;
  provider_kind: ProviderKind;
  base_url: string;
  endpoint_host: string;
  model: string;
  default_planner_mode: "shadow" | "gated";
  timeout_seconds: number;
  max_retries: number;
  max_output_tokens: number;
  context_budget_tokens: number;
  is_default: boolean;
  secret_configured: boolean;
  status: "ACTIVE" | "REVOKED";
  config_sha256: string;
  last_test_status: "NOT_TESTED" | "CONNECTED" | "FAILED" | "BLOCKED";
  last_tested_at: string | null;
  created_at: string;
  revoked_at: string | null;
}

export interface ProviderProfileInput {
  workspaceId: string;
  displayName: string;
  providerKind: ProviderKind;
  baseUrl: string;
  model: string;
  apiKey: string;
  defaultPlannerMode: "shadow" | "gated";
  timeoutSeconds?: number;
  maxRetries?: number;
  maxOutputTokens?: number;
  contextBudgetTokens?: number;
  makeDefault?: boolean;
}

export interface ProviderConnectionTestResult {
  schema_version: "visiondata-gate.provider-connection-test.v1";
  status: "CONNECTED" | "FAILED" | "BLOCKED";
  reason_code: string;
  provider_kind: ProviderKind;
  endpoint_host: string;
  model: string;
  latency_ms: number;
  tested_at: string;
  exchange_receipt_sha256: string | null;
  secrets_retained: false;
}

export type CausalReplayStepId = "T0" | "T1" | "T2" | "T3" | "T4";

export type CausalReplayStepStatus = "COMPLETED" | "PENDING" | "BLOCKED";

export interface CausalReplayStep {
  step_id: CausalReplayStepId;
  sequence: number;
  label: string;
  status: CausalReplayStepStatus;
  occurred: boolean;
  actor: string;
  decision: string | null;
  finding_count: number | null;
  work_order_count: number | null;
  responsibility_closed: number | null;
  responsibility_open: number | null;
  dynamic_worker_count: number | null;
  regressed_atomic_finding_count: number | null;
  evidence_refs: string[];
  evidence_digests: Record<string, string>;
  summary: string;
  source_scope: "SHA_VERIFIED_LOCAL_PRODUCT_EVIDENCE";
}

export interface CausalReplayReport {
  schema_version: "visiondata-gate.causal-replay.v1";
  parent_task_id: string;
  capa_case_id: string;
  child_task_id: string | null;
  current_step_id: CausalReplayStepId;
  steps: CausalReplayStep[];
  read_only: true;
  production_release_allowed: false;
  report_sha256: string;
  claim_boundary: string;
}

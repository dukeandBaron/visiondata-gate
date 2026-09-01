export interface SemifinalManifestVisualAsset {
  asset_id: string;
  filename: "synthetic-fixture-before.png" | "synthetic-fixture-recheck.png";
  source_sha256: string;
  preview_sha256: string;
  width: number;
  height: number;
}

export interface VerifiedSemifinalDemoManifest {
  schema_version: "visiondata-gate.semifinal-demo-manifest.v1";
  status: "PASS_LOCAL_DEMO_PREPARED";
  source_scope: "SYNTHETIC_FIXTURE_REPLAY_ONLY";
  actor_user_id: "usr_local_demo";
  workspace_id: string;
  project_id: string;
  project_source_kind: "synthetic_demo";
  task_id: string;
  review_start_path: string;
  task_request_sha256: string;
  task_evidence_sha256: string;
  task_execution_status: "COMPLETED";
  task_final_decision: "PASS";
  task_release_readiness_status: "DEMO_ONLY";
  task_release_readiness_sha256: string;
  event_count: number;
  parent_case_id: string;
  parent_case_sha256: string;
  decision_id: string;
  decision_sha256: string;
  decision_kind: "CONTINUE_HOLD";
  child_case_id: string;
  child_case_sha256: string;
  child_incident_status: "INVESTIGATION_REQUIRED";
  child_incident_recommendation: "CONTINUE_HOLD";
  interaction_id: string;
  interaction_receipt_sha256: string;
  interaction_status: "RESUMED_WITH_OPEN_QUESTIONS";
  remaining_open_question_count: 1;
  visual_assets: [SemifinalManifestVisualAsset, SemifinalManifestVisualAsset];
  production_release_allowed: false;
  machine_write_permitted: false;
  customer_validation: "NOT_CLAIMED";
  factory_shadow_metrics: "NOT_MEASURED_PENDING_ADJUDICATION";
  claim_boundary: string;
  manifest_sha256: string;
}

export type SemifinalManifestFailureCode =
  | "MANIFEST_MISSING"
  | "MANIFEST_NOT_REGULAR_FILE"
  | "MANIFEST_UNREADABLE"
  | "MANIFEST_INVALID_JSON"
  | "MANIFEST_CONTRACT_INVALID"
  | "PRODUCT_STATE_INVALID"
  | "PROJECTION_BUILD_FAILED_CLOSED";

export interface SemifinalDemoManifestProjection {
  schema_version: "visiondata-gate.semifinal-demo-manifest-projection.v1";
  status: "PASS_LOCAL_DEMO_VERIFIED" | "HOLD";
  availability: "AVAILABLE" | "UNAVAILABLE";
  verification_status: "VERIFIED" | "FAILED_CLOSED";
  failure_code: SemifinalManifestFailureCode | null;
  manifest: VerifiedSemifinalDemoManifest | null;
  manifest_sha256: string | null;
  local_demo_only: true;
  product_root_exposed: false;
  production_release_allowed: false;
  machine_write_permitted: false;
  submission_eligible: false;
  customer_validation: "NOT_CLAIMED";
  factory_shadow_metrics: "NOT_MEASURED_PENDING_ADJUDICATION";
  read_only: true;
  claim_boundary: string;
  projection_hash_profile: "visiondata-gate.rfc8785-jcs-projection-sha256.v1";
  projection_sha256: string;
}

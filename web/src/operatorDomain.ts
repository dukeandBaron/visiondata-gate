export interface ImageInspectionMetrics {
  mean_luma: number;
  contrast_std: number;
  edge_energy: number;
  black_clip_ratio: number;
  white_clip_ratio: number;
  sample_width: number;
  sample_height: number;
}

export interface OperatorImageAsset {
  asset_id: string;
  workspace_id: string;
  project_id?: string | null;
  original_name: string;
  format: string;
  content_type: string;
  byte_size: number;
  width: number;
  height: number;
  mode: string;
  source_sha256: string;
  preview_sha256: string;
  source_url: string;
  preview_url: string;
  duplicate_of_asset_id?: string | null;
  annotation_count: number;
  annotation_revision: number;
  inspection: ImageInspectionMetrics;
  created_at: string;
  local_only: true;
  external_transmission: false;
}

export interface OperatorImageUploadBatch {
  workspace_id: string;
  project_id?: string | null;
  uploaded_count: number;
  assets: OperatorImageAsset[];
  raw_images_transmitted: false;
}

export interface BoundingBoxAnnotation {
  annotation_id: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  source: "MANUAL" | "IMPORTED";
}

export interface OperatorAnnotationState {
  asset_id: string;
  asset_sha256: string;
  revision: number;
  updated_at?: string | null;
  annotations: BoundingBoxAnnotation[];
  document_sha256: string;
}

export type OperatorAgentEventStage =
  | "INTAKE"
  | "TOOL"
  | "KNOWLEDGE"
  | "DELIVERY"
  | "HUMAN_GATE";

export interface OperatorAgentEvent {
  sequence: number;
  stage: OperatorAgentEventStage;
  actor: "operator-agent" | "deterministic-tool" | "governance";
  action: string;
  status: "COMPLETED" | "WARNING" | "WAITING";
  summary: string;
  tool_name?: string | null;
  duration_ms: number;
  evidence_refs: string[];
  receipt_sha256: string;
}

export interface OperatorKnowledgeHit {
  card_id: string;
  title: string;
  excerpt: string;
  source: string;
  permission_scope: "local-read-only";
  evidence_ref: string;
}

export interface OperatorAgentRecommendation {
  code: string;
  severity: "LOW" | "MEDIUM" | "HIGH";
  title: string;
  summary: string;
  next_action: string;
  evidence_refs: string[];
  decision_authority: "none";
}

export interface OperatorAnalysisRun {
  schema_version: "visiondata-gate.operator-analysis-run.v1";
  analysis_run_id: string;
  workspace_id: string;
  project_id?: string | null;
  asset_id: string;
  asset_sha256: string;
  annotation_revision: number;
  annotation_document_sha256: string;
  started_at: string;
  completed_at: string;
  goal: string;
  intent: string;
  backend: "local-deterministic";
  backend_connected: true;
  fallback_used: false;
  execution_status: "COMPLETED";
  workflow_status: "AWAITING_HUMAN_REVIEW";
  model_call_count: 0;
  tool_call_count: number;
  raw_images_transmitted: false;
  events: OperatorAgentEvent[];
  knowledge_hits: OperatorKnowledgeHit[];
  recommendation: OperatorAgentRecommendation;
  human_gate: {
    required: true;
    status: "AWAITING_HUMAN_REVIEW";
    required_action: string;
    production_authority: "human_only";
  };
  boundary_notice: string;
  document_sha256: string;
}

export interface OperatorCopilotTurn {
  schema_version: "visiondata-gate.operator-copilot-turn.v1";
  turn_id: string;
  analysis_run_id: string;
  workspace_id: string;
  project_id?: string | null;
  asset_id: string;
  asset_sha256: string;
  question: string;
  answer: string;
  evidence_refs: string[];
  answer_mode: "LOCAL_EVIDENCE_GROUNDED";
  model_call_count: 0;
  raw_images_transmitted: false;
  created_by: string;
  created_at: string;
  boundary_notice: string;
  document_sha256: string;
}

export interface PixelBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type OperatorWorkOrderStatus =
  | "OPEN"
  | "ACKNOWLEDGED"
  | "IN_CAPA"
  | "REJECTED"
  | "CLOSED";

export interface OperatorWorkOrder {
  work_order_id: string;
  workspace_id: string;
  project_id?: string | null;
  asset_id: string;
  asset_sha256: string;
  image_name: string;
  annotation_revision: number;
  annotation: BoundingBoxAnnotation;
  pixel_bbox: PixelBoundingBox;
  crop_sha256: string;
  crop_url: string;
  revision: number;
  status: OperatorWorkOrderStatus;
  assignee: string;
  note: string;
  operator_attests_reviewed_evidence: boolean;
  verification_annotation_revision?: number | null;
  verification_annotation_sha256?: string | null;
  production_authority: "human_only";
  created_by: string;
  created_at: string;
  updated_by: string;
  updated_at: string;
  document_sha256: string;
}

export interface OpticalProbeSample {
  position: number;
  luminance: number;
  gradient: number;
}

export interface OpticalProbeProfile {
  start: { x: number; y: number };
  end: { x: number; y: number };
  length_pixels: number;
  mean_luminance: number;
  max_gradient: number;
  samples: OpticalProbeSample[];
  sampling_basis: "LOCAL_PREVIEW";
}

export type TwinComparisonMode = "OFF" | "CURTAIN" | "DIFF";
export type CanvasTool = "SELECT" | "BOX" | "PAN" | "PROBE";

export interface TaskVisualEvidenceMeasurement {
  source_kind: string;
  finding_id: string;
  code: string;
  tool: string;
  evidence_ref: string;
  evidence_sha256: string;
  observed: Record<string, unknown>;
}

export interface TaskVisualEvidenceItem {
  sample_id: string;
  original_name: string;
  width: number;
  height: number;
  source_sha256: string;
  preview_sha256: string;
  annotation_revision: number;
  annotation_document_sha256: string;
  annotation_count: number;
  mask_sha256?: string | null;
  preview_url: string;
  mask_url?: string | null;
  affected: boolean;
  finding_ids: string[];
  issue_codes: string[];
  tools: string[];
  work_order_ids: string[];
  measurements: TaskVisualEvidenceMeasurement[];
  item_sha256: string;
}

export interface TaskVisualEvidenceManifest {
  schema_version: "visiondata-gate.task-visual-evidence.v1";
  task_id: string;
  workspace_id: string;
  project_id: string;
  source_id: string;
  task_request_sha256: string;
  task_evidence_sha256: string;
  source_profile_sha256: string;
  operator_snapshot_receipt_sha256: string;
  visual_count: number;
  affected_count: number;
  items: TaskVisualEvidenceItem[];
  read_only: true;
  raw_images_transmitted: false;
  production_release_allowed: false;
  manifest_sha256: string;
  claim_boundary: string;
}

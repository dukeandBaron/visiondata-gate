import type {
  SemifinalDemoManifestProjection,
  SemifinalManifestVisualAsset,
  VerifiedSemifinalDemoManifest,
} from "../semifinalManifestDomain";
import { OperatorApiError, operatorFetch } from "./api";
import { detachedJcsSha256 } from "./jcs";

const sha256Pattern = /^[0-9a-f]{64}$/;
const taskPattern = /^tsk_[0-9a-f]{20}$/;
const casePattern = /^incident_[0-9a-f]{20}$/;
const decisionPattern = /^incident_decision_[0-9a-f]{20}$/;
const interactionPattern = /^interaction_[0-9a-f]{20}$/;
const assetPattern = /^img_[0-9a-f]{20}$/;
const failureCodes = new Set([
  "MANIFEST_MISSING",
  "MANIFEST_NOT_REGULAR_FILE",
  "MANIFEST_UNREADABLE",
  "MANIFEST_INVALID_JSON",
  "MANIFEST_CONTRACT_INVALID",
  "PRODUCT_STATE_INVALID",
  "PROJECTION_BUILD_FAILED_CLOSED",
]);

const projectionKeys = [
  "schema_version", "status", "availability", "verification_status", "failure_code",
  "manifest", "manifest_sha256", "local_demo_only", "product_root_exposed",
  "production_release_allowed", "machine_write_permitted", "submission_eligible",
  "customer_validation", "factory_shadow_metrics", "read_only", "claim_boundary",
  "projection_hash_profile", "projection_sha256",
] as const;

const manifestKeys = [
  "schema_version", "status", "source_scope", "actor_user_id", "workspace_id",
  "project_id", "project_source_kind", "task_id", "review_start_path",
  "task_request_sha256", "task_evidence_sha256", "task_execution_status",
  "task_final_decision", "task_release_readiness_status", "task_release_readiness_sha256",
  "event_count", "parent_case_id", "parent_case_sha256", "decision_id",
  "decision_sha256", "decision_kind", "child_case_id", "child_case_sha256",
  "child_incident_status", "child_incident_recommendation", "interaction_id",
  "interaction_receipt_sha256", "interaction_status", "remaining_open_question_count",
  "visual_assets", "production_release_allowed", "machine_write_permitted",
  "customer_validation", "factory_shadow_metrics", "claim_boundary", "manifest_sha256",
] as const;

const assetKeys = [
  "asset_id", "filename", "source_sha256", "preview_sha256", "width", "height",
] as const;

function fail(message: string): never {
  throw new OperatorApiError("SEMIFINAL_MANIFEST_CONTRACT_DRIFT", message, 502);
}

function requireContract(condition: boolean, message: string): asserts condition {
  if (!condition) fail(message);
}

function object(value: unknown, label: string): Record<string, unknown> {
  requireContract(typeof value === "object" && value !== null && !Array.isArray(value), `${label} 不是对象`);
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[], label: string): void {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  requireContract(
    actual.length === sortedExpected.length && actual.every((key, index) => key === sortedExpected[index]),
    `${label} 字段集合漂移`,
  );
}

function normalizeEtag(value: string | null): string {
  return value?.trim().replace(/^W\//, "").replace(/^\"|\"$/g, "").toLowerCase() ?? "";
}

function parseAsset(value: unknown): SemifinalManifestVisualAsset {
  const asset = object(value, "semifinal visual asset");
  exactKeys(asset, assetKeys, "semifinal visual asset");
  requireContract(typeof asset.asset_id === "string" && assetPattern.test(asset.asset_id), "visual asset id 无效");
  requireContract(asset.filename === "synthetic-fixture-before.png" || asset.filename === "synthetic-fixture-recheck.png", "visual asset filename 越界");
  requireContract(typeof asset.source_sha256 === "string" && sha256Pattern.test(asset.source_sha256), "visual source SHA 无效");
  requireContract(typeof asset.preview_sha256 === "string" && sha256Pattern.test(asset.preview_sha256), "visual preview SHA 无效");
  requireContract(Number.isInteger(asset.width) && Number(asset.width) > 0, "visual width 无效");
  requireContract(Number.isInteger(asset.height) && Number(asset.height) > 0, "visual height 无效");
  return asset as unknown as SemifinalManifestVisualAsset;
}

function parseManifest(value: unknown): VerifiedSemifinalDemoManifest {
  const manifest = object(value, "verified semifinal manifest");
  exactKeys(manifest, manifestKeys, "verified semifinal manifest");
  requireContract(!(Object.prototype.hasOwnProperty.call(manifest, "product_root")), "ProductRoot 路径不得暴露到浏览器");
  requireContract(manifest.schema_version === "visiondata-gate.semifinal-demo-manifest.v1", "manifest schema 漂移");
  requireContract(manifest.status === "PASS_LOCAL_DEMO_PREPARED", "manifest 准备状态漂移");
  requireContract(manifest.source_scope === "SYNTHETIC_FIXTURE_REPLAY_ONLY", "manifest 来源越界");
  requireContract(manifest.actor_user_id === "usr_local_demo" && manifest.project_source_kind === "synthetic_demo", "manifest demo 身份漂移");
  requireContract(typeof manifest.workspace_id === "string" && manifest.workspace_id.length > 0, "manifest workspace 无效");
  requireContract(typeof manifest.project_id === "string" && manifest.project_id.length > 0, "manifest project 无效");
  requireContract(typeof manifest.task_id === "string" && taskPattern.test(manifest.task_id), "manifest task id 无效");
  requireContract(manifest.review_start_path === `/review?task=${manifest.task_id}`, "manifest review path 未绑定 Task");
  for (const key of ["task_request_sha256", "task_evidence_sha256", "task_release_readiness_sha256", "parent_case_sha256", "decision_sha256", "child_case_sha256", "interaction_receipt_sha256", "manifest_sha256"] as const) {
    requireContract(typeof manifest[key] === "string" && sha256Pattern.test(manifest[key]), `manifest ${key} 无效`);
  }
  requireContract(manifest.task_execution_status === "COMPLETED" && manifest.task_final_decision === "PASS", "manifest Task 终态漂移");
  requireContract(manifest.task_release_readiness_status === "DEMO_ONLY", "manifest readiness 必须保持 DEMO_ONLY");
  requireContract(Number.isInteger(manifest.event_count) && Number(manifest.event_count) > 0, "manifest event_count 无效");
  requireContract(typeof manifest.parent_case_id === "string" && casePattern.test(manifest.parent_case_id), "parent case id 无效");
  requireContract(typeof manifest.child_case_id === "string" && casePattern.test(manifest.child_case_id) && manifest.child_case_id !== manifest.parent_case_id, "child case id 无效");
  requireContract(typeof manifest.decision_id === "string" && decisionPattern.test(manifest.decision_id) && manifest.decision_kind === "CONTINUE_HOLD", "human decision 合同漂移");
  requireContract(manifest.child_incident_status === "INVESTIGATION_REQUIRED" && manifest.child_incident_recommendation === "CONTINUE_HOLD", "child incident 边界漂移");
  requireContract(typeof manifest.interaction_id === "string" && interactionPattern.test(manifest.interaction_id), "interaction id 无效");
  requireContract(manifest.interaction_status === "RESUMED_WITH_OPEN_QUESTIONS" && manifest.remaining_open_question_count === 1, "interaction 未保留开放问题");
  requireContract(Array.isArray(manifest.visual_assets) && manifest.visual_assets.length === 2, "manifest 必须绑定两个视觉资产");
  const assets = manifest.visual_assets.map(parseAsset);
  requireContract(new Set(assets.map((item) => item.filename)).size === 2, "manifest 视觉资产集合重复");
  requireContract(manifest.production_release_allowed === false && manifest.machine_write_permitted === false, "manifest 生产权限越界");
  requireContract(manifest.customer_validation === "NOT_CLAIMED" && manifest.factory_shadow_metrics === "NOT_MEASURED_PENDING_ADJUDICATION", "manifest 真实验证边界漂移");
  requireContract(typeof manifest.claim_boundary === "string" && manifest.claim_boundary.length >= 80, "manifest 声明边界缺失");
  return { ...manifest, visual_assets: assets } as unknown as VerifiedSemifinalDemoManifest;
}

function validateProjection(value: unknown): SemifinalDemoManifestProjection {
  const projection = object(value, "semifinal manifest projection");
  exactKeys(projection, projectionKeys, "semifinal manifest projection");
  requireContract(projection.schema_version === "visiondata-gate.semifinal-demo-manifest-projection.v1", "semifinal projection schema 漂移");
  requireContract(projection.status === "PASS_LOCAL_DEMO_VERIFIED" || projection.status === "HOLD", "semifinal projection status 无效");
  requireContract(projection.local_demo_only === true && projection.product_root_exposed === false, "semifinal 本地演示或路径边界漂移");
  requireContract(projection.production_release_allowed === false && projection.machine_write_permitted === false && projection.submission_eligible === false, "semifinal projection 权限越界");
  requireContract(projection.customer_validation === "NOT_CLAIMED" && projection.factory_shadow_metrics === "NOT_MEASURED_PENDING_ADJUDICATION", "semifinal projection 验证边界漂移");
  requireContract(projection.read_only === true, "semifinal projection 必须只读");
  requireContract(typeof projection.claim_boundary === "string" && projection.claim_boundary.length >= 80, "semifinal projection 声明边界缺失");
  requireContract(projection.projection_hash_profile === "visiondata-gate.rfc8785-jcs-projection-sha256.v1", "semifinal projection 哈希规范漂移");
  requireContract(typeof projection.projection_sha256 === "string" && sha256Pattern.test(projection.projection_sha256), "semifinal projection SHA 无效");
  if (projection.status === "PASS_LOCAL_DEMO_VERIFIED") {
    requireContract(projection.availability === "AVAILABLE" && projection.verification_status === "VERIFIED" && projection.failure_code === null, "semifinal PASS 状态不一致");
    const manifest = parseManifest(projection.manifest);
    requireContract(typeof projection.manifest_sha256 === "string" && projection.manifest_sha256 === manifest.manifest_sha256, "semifinal source manifest SHA 绑定失败");
    return { ...projection, manifest } as unknown as SemifinalDemoManifestProjection;
  }
  requireContract(projection.availability === "UNAVAILABLE" && projection.verification_status === "FAILED_CLOSED", "semifinal HOLD 未失败关闭");
  requireContract(typeof projection.failure_code === "string" && failureCodes.has(projection.failure_code), "semifinal HOLD 缺少受控失败代码");
  requireContract(projection.manifest === null && projection.manifest_sha256 === null, "semifinal HOLD 携带未验证 manifest");
  return projection as unknown as SemifinalDemoManifestProjection;
}

export async function getSemifinalDemoManifestProjection(): Promise<SemifinalDemoManifestProjection> {
  const response = await operatorFetch("/v1/review/semifinal-demo-manifest");
  const raw = await response.json() as unknown;
  const projection = validateProjection(raw);
  const computed = await detachedJcsSha256(raw as Record<string, unknown>, "projection_sha256");
  requireContract(computed === projection.projection_sha256, "semifinal projection payload JCS SHA-256 不一致");
  const contentSha = response.headers.get("X-Content-SHA256")?.trim().toLowerCase() ?? "";
  requireContract(contentSha === projection.projection_sha256, "semifinal projection X-Content-SHA256 不一致");
  requireContract(normalizeEtag(response.headers.get("ETag")) === projection.projection_sha256, "semifinal projection ETag 不一致");
  const manifestHeader = response.headers.get("X-Semifinal-Manifest-SHA256")?.trim().toLowerCase() ?? "";
  if (projection.status === "PASS_LOCAL_DEMO_VERIFIED") {
    requireContract(manifestHeader === projection.manifest_sha256, "semifinal source manifest Header 不一致");
  } else {
    requireContract(manifestHeader === "", "semifinal HOLD 不得发布 source manifest Header");
  }
  return projection;
}

import {
  ArrowRight,
  CheckCircle2,
  FileCheck2,
  Fingerprint,
  GitBranch,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  UserCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { getSemifinalDemoManifestProjection } from "../data/semifinalManifestApi";
import type { SemifinalDemoManifestProjection } from "../semifinalManifestDomain";
import { Digest, Panel, PanelHeader, StatusBadge } from "./ui";

type LoadState = "IDLE" | "LOADING" | "READY" | "UNAVAILABLE";

function compact(value: string): string {
  return `${value.slice(0, 11)}…${value.slice(-7)}`;
}

export function SemifinalManifestEvidence({ enabled }: { enabled: boolean }) {
  const [refreshToken, setRefreshToken] = useState(0);
  const [loadState, setLoadState] = useState<LoadState>(enabled ? "LOADING" : "IDLE");
  const [projection, setProjection] = useState<SemifinalDemoManifestProjection>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    let current = true;
    if (!enabled) {
      setProjection(undefined);
      setLoadState("IDLE");
      setError("本地 API 未连接；页面不会用磁盘文案补位。");
      return () => { current = false; };
    }
    setLoadState("LOADING");
    setProjection(undefined);
    setError(undefined);
    void getSemifinalDemoManifestProjection()
      .then((next) => {
        if (!current) return;
        setProjection(next);
        setLoadState("READY");
      })
      .catch((caught: unknown) => {
        if (!current) return;
        setProjection(undefined);
        setLoadState("UNAVAILABLE");
        setError(caught instanceof Error ? caught.message : "复赛 manifest 回执未通过浏览器合同核验");
      });
    return () => { current = false; };
  }, [enabled, refreshToken]);

  const verified = projection?.status === "PASS_LOCAL_DEMO_VERIFIED" && projection.manifest !== null;
  const manifest = verified ? projection.manifest : null;
  const status = loadState === "LOADING" ? "VERIFYING" : verified ? "PASS_LOCAL_DEMO_VERIFIED" : "HOLD";
  const chainLabel = loadState === "LOADING" ? "CHAIN VERIFYING" : verified ? "CHAIN VERIFIED" : "CHAIN HOLD";

  return (
    <Panel
      id="semifinal-manifest-evidence"
      className={`semifinal-manifest is-compact${verified ? " is-verified" : " is-hold"}`}
      variant="raised"
      dataStatus={status}
    >
      <PanelHeader
        eyebrow="SEMIFINAL PRODUCTROOT RECEIPT · READ ONLY"
        title="Goal ↔ Goal3 演示主链"
        detail="从当前服务的 ProductRoot 重新核对 Task、Parent / Child Case、具名人工决定与交互回执。"
        actions={(
          <div className="semifinal-manifest__actions">
            <StatusBadge tone={loadState === "LOADING" ? "neutral" : verified ? "success" : "danger"} compact>{chainLabel}</StatusBadge>
            {manifest ? <StatusBadge tone="warning" compact>OUTCOME · HOLD</StatusBadge> : null}
            <button type="button" onClick={() => setRefreshToken((value) => value + 1)} disabled={!enabled || loadState === "LOADING"}>
              {loadState === "LOADING" ? <LoaderCircle className="is-spinning" size={14} /> : <RefreshCw size={14} />}
              <span>重新核验</span>
            </button>
          </div>
        )}
      />

      {loadState === "LOADING" ? (
        <div className="semifinal-manifest__state" role="status">
          <LoaderCircle className="is-spinning" size={19} />
          <span><strong>正在核对当前 ProductRoot</strong>仅在 manifest 合同、数据库终态和不可变链同时一致时显示主链。</span>
        </div>
      ) : !verified || !projection || !manifest ? (
        <div className="semifinal-manifest__state is-error" role="alert">
          <TriangleAlert size={20} />
          <span>
            <strong>HOLD · SEMIFINAL MANIFEST UNAVAILABLE</strong>
            {projection?.failure_code ?? error ?? "当前 ProductRoot 未提供可核对的复赛 manifest。"}
            <small>不使用 README、fixture 数字或旧截图补位。</small>
          </span>
        </div>
      ) : (
        <>
          <div className="semifinal-manifest__scope">
            <LockKeyhole size={15} />
            <strong>SYNTHETIC FIXTURE REPLAY ONLY</strong>
            <span>{manifest.workspace_id} / {manifest.project_id} / {manifest.task_id}</span>
            <em><ShieldCheck size={14} /> PAYLOAD JCS SHA + ETAG VERIFIED</em>
          </div>

          <div className="semifinal-manifest__rail" aria-label="Goal 与 Goal3 复赛演示主链">
            <article>
              <span><FileCheck2 size={16} /></span>
              <small>01 · GOAL TASK</small>
              <strong>{manifest.task_final_decision} · {manifest.task_release_readiness_status}</strong>
              <code>{compact(manifest.task_release_readiness_sha256)}</code>
            </article>
            <ArrowRight aria-hidden="true" />
            <article>
              <span><GitBranch size={16} /></span>
              <small>02 · PARENT CASE</small>
              <strong>{compact(manifest.parent_case_id)}</strong>
              <code>{compact(manifest.parent_case_sha256)}</code>
            </article>
            <ArrowRight aria-hidden="true" />
            <article className="is-human">
              <span><UserCheck size={16} /></span>
              <small>03 · HUMAN GATE</small>
              <strong>{manifest.decision_kind}</strong>
              <code>{compact(manifest.decision_sha256)}</code>
            </article>
            <ArrowRight aria-hidden="true" />
            <article>
              <span><GitBranch size={16} /></span>
              <small>04 · CHILD CASE</small>
              <strong>{manifest.child_incident_status}</strong>
              <code>{compact(manifest.child_case_sha256)}</code>
            </article>
            <ArrowRight aria-hidden="true" />
            <article>
              <span><CheckCircle2 size={16} /></span>
              <small>05 · INTERACTION</small>
              <strong>{manifest.interaction_status}</strong>
              <code>{compact(manifest.interaction_receipt_sha256)}</code>
            </article>
          </div>

          <div className="semifinal-manifest__facts">
            <span><strong>{manifest.visual_assets.length}</strong><small>FROZEN VISUAL ASSETS</small></span>
            <span><strong>{manifest.event_count}</strong><small>APPEND-ONLY EVENTS</small></span>
            <span><strong>{manifest.remaining_open_question_count}</strong><small>OPEN QUESTION · RETAINED</small></span>
            <span><strong>{String(projection.submission_eligible)}</strong><small>SUBMISSION ELIGIBLE</small></span>
          </div>

          <div className="semifinal-manifest__digests">
            <Digest label="SOURCE MANIFEST SHA-256 · SERVER RECONCILED" value={projection.manifest_sha256 ?? ""} />
            <Digest label="BROWSER-VERIFIED PROJECTION SHA-256" value={projection.projection_sha256} />
          </div>
          <footer>
            <Fingerprint size={14} />
            <span>production_release_allowed={String(projection.production_release_allowed)} · machine_write_permitted={String(projection.machine_write_permitted)} · customer_validation={projection.customer_validation}</span>
            <code>{projection.factory_shadow_metrics}</code>
          </footer>
        </>
      )}
    </Panel>
  );
}

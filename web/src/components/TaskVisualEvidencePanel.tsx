import {
  AlertTriangle,
  CheckCircle2,
  FileCheck2,
  Image as ImageIcon,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  ScanSearch,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  getTaskVisualEvidence,
  loadTaskVisualEvidenceMask,
  loadTaskVisualEvidencePreview,
} from "../data/api";
import type { OpticalProbeProfile } from "../operatorDomain";
import type {
  TaskVisualEvidenceItem,
  TaskVisualEvidenceManifest,
} from "../visualEvidenceDomain";
import { InteractiveImageCanvas, type CanvasImageAsset } from "./InteractiveImageCanvas";
import { Digest, Panel, PanelHeader, StatusBadge } from "./ui";

interface TaskVisualEvidencePanelProps {
  taskId: string;
  expectedWorkspaceId: string;
  expectedProjectId: string;
  compact?: boolean;
  onSummaryChange?: (summary: TaskVisualEvidenceSummary | undefined) => void;
}

export interface TaskVisualEvidenceSummary {
  task_id: string;
  visual_count: number;
  affected_count: number;
}

type LoadState = "LOADING" | "READY" | "ERROR";

function compact(value: string, head = 9, tail = 6): string {
  return value.length > head + tail + 1
    ? `${value.slice(0, head)}…${value.slice(-tail)}`
    : value;
}

function errorMessage(value: unknown): string {
  return value instanceof Error ? value.message : "冻结视觉证据读取失败";
}

function canvasAsset(item: TaskVisualEvidenceItem): CanvasImageAsset {
  const extension = item.original_name.split(".").pop()?.toUpperCase() || "IMAGE";
  return {
    asset_id: item.sample_id,
    original_name: item.original_name,
    width: item.width,
    height: item.height,
    format: extension,
    mode: "FROZEN PREVIEW",
  };
}

function printableMeasurement(value: unknown): string | undefined {
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  }
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  if (Array.isArray(value) && value.length <= 8) return value.map(String).join(", ");
  return undefined;
}

export function TaskVisualEvidencePanel({
  taskId,
  expectedWorkspaceId,
  expectedProjectId,
  compact: compactLayout = false,
  onSummaryChange,
}: TaskVisualEvidencePanelProps) {
  const [loadState, setLoadState] = useState<LoadState>("LOADING");
  const [manifest, setManifest] = useState<TaskVisualEvidenceManifest>();
  const [selectedSampleId, setSelectedSampleId] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string>();
  const [maskUrl, setMaskUrl] = useState<string>();
  const [imageLoadState, setImageLoadState] = useState<LoadState>("LOADING");
  const [error, setError] = useState<string>();
  const [probe, setProbe] = useState<OpticalProbeProfile>();
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [imageRefreshRevision, setImageRefreshRevision] = useState(0);
  const manifestGeneration = useRef(0);
  const imageGeneration = useRef(0);
  const onSummaryChangeRef = useRef(onSummaryChange);
  onSummaryChangeRef.current = onSummaryChange;

  useEffect(() => {
    const generation = ++manifestGeneration.current;
    onSummaryChangeRef.current?.(undefined);
    setLoadState("LOADING");
    setManifest(undefined);
    setSelectedSampleId("");
    setError(undefined);
    void getTaskVisualEvidence(taskId)
      .then((payload) => {
        if (generation !== manifestGeneration.current) return;
        if (
          payload.workspace_id !== expectedWorkspaceId ||
          payload.project_id !== expectedProjectId
        ) {
          throw new Error("冻结视觉证据与当前 workspace / project 绑定不一致。");
        }
        setManifest(payload);
        onSummaryChangeRef.current?.({
          task_id: payload.task_id,
          visual_count: payload.visual_count,
          affected_count: payload.affected_count,
        });
        const first = payload.items.find((item) => item.affected) ?? payload.items[0];
        setSelectedSampleId(first?.sample_id ?? "");
        setLoadState("READY");
      })
      .catch((caught: unknown) => {
        if (generation !== manifestGeneration.current) return;
        onSummaryChangeRef.current?.(undefined);
        setError(errorMessage(caught));
        setLoadState("ERROR");
      });
    return () => {
      manifestGeneration.current += 1;
    };
  }, [expectedProjectId, expectedWorkspaceId, refreshRevision, taskId]);

  const selected = useMemo(
    () => manifest?.items.find((item) => item.sample_id === selectedSampleId),
    [manifest?.items, selectedSampleId],
  );

  useEffect(() => {
    const generation = ++imageGeneration.current;
    setPreviewUrl(undefined);
    setMaskUrl(undefined);
    setProbe(undefined);
    setError(undefined);
    setImageLoadState("LOADING");
    if (!selected) return undefined;
    let activePreview: string | undefined;
    let activeMask: string | undefined;
    void (async () => {
      let nextPreview: string | undefined;
      let nextMask: string | undefined;
      try {
        nextPreview = await loadTaskVisualEvidencePreview(selected);
        nextMask = await loadTaskVisualEvidenceMask(selected);
        if (generation !== imageGeneration.current) {
          URL.revokeObjectURL(nextPreview);
          if (nextMask) URL.revokeObjectURL(nextMask);
          return;
        }
        activePreview = nextPreview;
        activeMask = nextMask;
        setPreviewUrl(nextPreview);
        setMaskUrl(nextMask);
        setImageLoadState("READY");
      } catch (caught: unknown) {
        if (nextPreview) URL.revokeObjectURL(nextPreview);
        if (nextMask) URL.revokeObjectURL(nextMask);
        if (generation !== imageGeneration.current) return;
        setPreviewUrl(undefined);
        setMaskUrl(undefined);
        setError(errorMessage(caught));
        setImageLoadState("ERROR");
      }
    })();
    return () => {
      imageGeneration.current += 1;
      if (activePreview) URL.revokeObjectURL(activePreview);
      if (activeMask) URL.revokeObjectURL(activeMask);
    };
  }, [imageRefreshRevision, selected]);

  const observedRows = useMemo(
    () =>
      selected?.measurements.flatMap((measurement) =>
        Object.entries(measurement.observed)
          .map(([key, value]) => ({
            key,
            value: printableMeasurement(value),
            tool: measurement.tool,
            evidenceSha256: measurement.evidence_sha256,
          }))
          .filter((item): item is typeof item & { value: string } => item.value !== undefined),
      ) ?? [],
    [selected],
  );

  if (loadState !== "READY" || !manifest || !selected) {
    return (
      <Panel className="task-visual-evidence task-visual-evidence--state">
        <PanelHeader
          eyebrow="FROZEN VISUAL EVIDENCE"
          title={loadState === "LOADING" ? "正在核验任务图像" : "冻结视觉证据不可用"}
          detail={loadState === "LOADING" ? "校验 Evidence ZIP、Operator Snapshot 与样本字节 SHA。" : `${error ?? "当前任务没有可展示的 Operator Snapshot。"} 页面不会用 fixture 补位。`}
          actions={loadState === "ERROR" ? <button type="button" onClick={() => setRefreshRevision((value) => value + 1)}><RefreshCw size={13} />重试</button> : undefined}
        />
        <div className="task-visual-evidence__empty">
          {loadState === "LOADING" ? <LoaderCircle className="is-spinning" size={22} /> : <AlertTriangle size={22} />}
        </div>
      </Panel>
    );
  }

  return (
    <Panel className={`task-visual-evidence${compactLayout ? " task-visual-evidence--compact" : ""}`} variant="raised">
      <PanelHeader
        eyebrow="FROZEN VISUAL EVIDENCE"
        title="Agent 实际检查的样本"
        detail={`${manifest.visual_count} 个冻结预览 · ${manifest.affected_count} 个命中 finding；浏览器再次校验字节 SHA-256。`}
        actions={<><StatusBadge tone="info" compact><LockKeyhole size={11} />READ ONLY</StatusBadge><button type="button" onClick={() => setRefreshRevision((value) => value + 1)}><RefreshCw size={12} />刷新</button></>}
      />
      {error ? <div className="task-visual-evidence__error"><AlertTriangle size={13} />{error}</div> : null}
      <div className="task-visual-evidence__layout">
        <aside className="task-visual-evidence__samples">
          <header><ImageIcon size={13} /><span>SAMPLES</span><small>{manifest.items.length}</small></header>
          <div>
            {manifest.items.map((item) => (
              <button type="button" className={item.sample_id === selected.sample_id ? "is-active" : ""} onClick={() => setSelectedSampleId(item.sample_id)} key={item.sample_id}>
                <span className={item.affected ? "is-affected" : ""} />
                <div><strong>{item.original_name}</strong><code>{compact(item.sample_id)}</code><small>{item.issue_codes.join(" · ") || "NO SAMPLE FINDING"}</small></div>
                <StatusBadge tone={item.affected ? "danger" : "neutral"} compact>{item.affected ? "FLAGGED" : "NO SAMPLE FINDING"}</StatusBadge>
              </button>
            ))}
          </div>
        </aside>

        <main className="task-visual-evidence__canvas">
          {previewUrl && imageLoadState === "READY" ? (
            <InteractiveImageCanvas
              asset={canvasAsset(selected)}
              previewUrl={previewUrl}
              annotations={[]}
              readOnly
              onAnnotationsChange={() => undefined}
              onSelectedAnnotationChange={() => undefined}
              onProbeProfileChange={setProbe}
            />
          ) : imageLoadState === "ERROR" ? (
            <div className="task-visual-evidence__image-loading is-error" role="alert">
              <AlertTriangle size={21} />
              <span>{error ?? "冻结预览下载或 SHA-256 校验失败。"}</span>
              <button type="button" onClick={() => setImageRefreshRevision((value) => value + 1)}>
                <RefreshCw size={12} />重试预览
              </button>
            </div>
          ) : (
            <div className="task-visual-evidence__image-loading"><LoaderCircle className="is-spinning" size={21} /><span>下载并核验冻结预览…</span></div>
          )}
        </main>

        <aside className="task-visual-evidence__inspector">
          <header><ScanSearch size={13} /><span>MEASUREMENTS</span></header>
          <div className="task-visual-evidence__codes">
            {(selected.issue_codes.length ? selected.issue_codes : ["NO_SAMPLE_FINDING"]).map((code) => <StatusBadge tone={selected.affected ? "danger" : "neutral"} compact key={code}>{code}</StatusBadge>)}
          </div>
          <dl>
            {observedRows.slice(0, 10).map((row) => <div key={`${row.evidenceSha256}:${row.key}`}><dt>{row.tool} · {row.key}</dt><dd>{row.value}</dd></div>)}
            {probe ? <><div><dt>local probe mean</dt><dd>{probe.mean_luminance.toFixed(3)}</dd></div><div><dt>local probe max Δ</dt><dd>{probe.max_gradient.toFixed(3)}</dd></div></> : null}
          </dl>
          {maskUrl ? <figure><img src={maskUrl} alt={`${selected.original_name} 冻结标注 mask`} /><figcaption>冻结 annotation mask · revision {selected.annotation_revision}</figcaption></figure> : <p>该任务快照没有冻结标注 mask；页面不会从当前工作簿补写。</p>}
          <Digest label="preview SHA" value={selected.preview_sha256} />
          <Digest label="item SHA" value={selected.item_sha256} />
          <div className="task-visual-evidence__links"><Link to={`/workspace?asset=${encodeURIComponent(selected.sample_id)}`}><ImageIcon size={12} />打开当前工作簿资产</Link><Link to={`/evidence?task=${encodeURIComponent(taskId)}`}><FileCheck2 size={12} />打开完整证据包</Link></div>
        </aside>
      </div>
      <footer className="task-visual-evidence__boundary"><CheckCircle2 size={13} /><span>{manifest.claim_boundary}</span><code>{compact(manifest.manifest_sha256)}</code></footer>
    </Panel>
  );
}

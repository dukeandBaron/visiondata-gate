import {
  Activity,
  AlertTriangle,
  Bot,
  Check,
  Clipboard,
  ClipboardPlus,
  CloudOff,
  ExternalLink,
  FileImage,
  Files,
  FolderOpen,
  HardDrive,
  ImagePlus,
  LoaderCircle,
  RefreshCcw,
  Save,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Tag,
  Trash2,
  Upload,
  UserCheck,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
  type DragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useProduct } from "../ProductContext";
import { InteractiveImageCanvas } from "../components/InteractiveImageCanvas";
import {
  DatasetImportDialog,
  type DatasetImportResult,
} from "../components/DatasetImportDialog";
import {
  OperatorAgentPanel,
  type AgentPanelView,
} from "../components/OperatorAgentPanel";
import { OperatorWorkspaceTour } from "../components/OperatorWorkspaceTour";
import {
  authorizeOperatorProjectSnapshot,
  createOperatorAnalysisRun,
  createOperatorCopilotTurn,
  createOperatorWorkOrder,
  listOperatorAnalysisRuns,
  listOperatorCopilotTurns,
  listOperatorImages,
  loadOperatorAnnotations,
  loadOperatorPreview,
  OperatorApiError,
  saveOperatorAnnotations,
  uploadOperatorImages,
} from "../data/api";
import type {
  BoundingBoxAnnotation,
  OperatorAnalysisRun,
  OperatorAnnotationState,
  OperatorCopilotTurn,
  OperatorImageAsset,
  OpticalProbeProfile,
  TwinComparisonMode,
} from "../operatorDomain";

type InspectorTab = "PROPERTIES" | "AGENT";
type AssetSlice = "ALL" | "UNANNOTATED" | "DUPLICATE" | "FLAGGED";

const DEFAULT_INSPECTOR_WIDTH = 430;
const MIN_INSPECTOR_WIDTH = 360;
const MAX_INSPECTOR_WIDTH = 560;
const INSPECTOR_WIDTH_STORAGE_KEY = "visiondata-gate.operator-inspector-width";

function clampInspectorWidth(value: number): number {
  return Math.min(MAX_INSPECTOR_WIDTH, Math.max(MIN_INSPECTOR_WIDTH, Math.round(value)));
}

interface WorkbookAsyncContext {
  generation: number;
  workspaceId: string;
  projectId: string;
  assetId: string;
  analysisRunId?: string;
}

function isFlaggedAsset(asset: OperatorImageAsset): boolean {
  return (
    asset.inspection.black_clip_ratio >= 0.05 ||
    asset.inspection.white_clip_ratio >= 0.05 ||
    asset.inspection.contrast_std < 12 ||
    asset.inspection.edge_energy < 3
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;
}

function shortDigest(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function messageForError(error: unknown): string {
  if (error instanceof OperatorApiError) return `${error.code}: ${error.message}`;
  if (error instanceof DOMException && error.name === "AbortError") {
    return "本地 API 响应超时，请检查服务状态。";
  }
  return "无法连接本地图片工作区。请先启动 VisionData Gate API。";
}

interface DropZoneProps {
  compact?: boolean;
  disabled: boolean;
  onFiles: (files: File[]) => void;
  onBrowse: () => void;
}

function DropZone({ compact = false, disabled, onFiles, onBrowse }: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    onFiles(Array.from(event.dataTransfer.files));
  };
  return (
    <div
      className={`operator-dropzone${compact ? " is-compact" : ""}${dragging ? " is-dragging" : ""}`}
      onDragEnter={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={handleDrop}
    >
      <ImagePlus size={compact ? 17 : 28} />
      <div>
        <strong>{compact ? "拖入图像资产" : "把图像资产拖到当前项目"}</strong>
        {!compact ? <span>JPEG / PNG / BMP / TIFF / WebP · 单文件最大 32 MiB</span> : null}
      </div>
      <button type="button" onClick={onBrowse} disabled={disabled}>
        <FolderOpen size={15} />
        选择文件
      </button>
    </div>
  );
}

function OpticalProbeChart({ profile }: { profile: OpticalProbeProfile }) {
  const width = 250;
  const height = 78;
  const luminancePoints = profile.samples
    .map(
      (sample) =>
        `${(sample.position * width).toFixed(1)},${(
          height - (sample.luminance / 255) * height
        ).toFixed(1)}`,
    )
    .join(" ");
  const gradientScale = Math.max(1, profile.max_gradient);
  const gradientPoints = profile.samples
    .map(
      (sample) =>
        `${(sample.position * width).toFixed(1)},${(
          height - (sample.gradient / gradientScale) * height
        ).toFixed(1)}`,
    )
    .join(" ");
  return (
    <div className="optical-probe">
      <div className="optical-probe__metrics">
        <span><small>length</small><strong>{profile.length_pixels.toFixed(1)} px</strong></span>
        <span><small>mean I(x)</small><strong>{profile.mean_luminance.toFixed(2)}</strong></span>
        <span><small>max |∇I|</small><strong>{profile.max_gradient.toFixed(2)}</strong></span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="光度与梯度剖面曲线">
        <line x1="0" y1={height / 2} x2={width} y2={height / 2} />
        <polyline className="is-luminance" points={luminancePoints} />
        <polyline className="is-gradient" points={gradientPoints} />
      </svg>
      <div className="optical-probe__legend">
        <span><i className="is-luminance" />I(x) luminance</span>
        <span><i className="is-gradient" />|∇I| gradient</span>
      </div>
      <small>LOCAL_PREVIEW · 本机像素剖面，不是模型推断。</small>
    </div>
  );
}

export function ImageWorkspacePage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const annotationLedgerRef = useRef<HTMLDivElement>(null);
  const assetListRequestRef = useRef(0);
  const navigate = useNavigate();
  const {
    activeWorkspace,
    activeProject,
    workspaceLoading,
    registerScopeChangeGuard,
  } = useProduct();
  const workspaceId = activeWorkspace?.workspace_id;
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedAssetId = searchParams.get("asset");
  const requestedAssetIdRef = useRef(requestedAssetId);
  const activeProjectIdRef = useRef(activeProject?.project_id);
  const activeWorkspaceIdRef = useRef(workspaceId);
  const selectedAssetIdRef = useRef<string | undefined>(undefined);
  const analysisRunIdRef = useRef<string | undefined>(undefined);
  const dirtyRef = useRef(false);
  const contextGenerationRef = useRef(0);
  const [tourOpen, setTourOpen] = useState(searchParams.get("tour") === "1");
  const [datasetImportOpen, setDatasetImportOpen] = useState(searchParams.get("import") === "1");
  const [assets, setAssets] = useState<OperatorImageAsset[]>([]);
  const [selectedAssetId, setSelectedAssetId] = useState<string>();
  const [previewUrl, setPreviewUrl] = useState<string>();
  const [annotationState, setAnnotationState] = useState<OperatorAnnotationState>();
  const [annotations, setAnnotations] = useState<BoundingBoxAnnotation[]>([]);
  const [selectedAnnotationId, setSelectedAnnotationId] = useState<string>();
  const [highlightedAnnotationId, setHighlightedAnnotationId] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [snapshotting, setSnapshotting] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [query, setQuery] = useState("");
  const [assetSlice, setAssetSlice] = useState<AssetSlice>("ALL");
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [probeProfile, setProbeProfile] = useState<OpticalProbeProfile>();
  const [comparisonMode, setComparisonMode] = useState<TwinComparisonMode>("OFF");
  const [twinPreviewUrl, setTwinPreviewUrl] = useState<string>();
  const [issuingWorkOrder, setIssuingWorkOrder] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("PROPERTIES");
  const [agentPanelView, setAgentPanelView] = useState<AgentPanelView>("OVERVIEW");
  const [inspectorWidth, setInspectorWidth] = useState(DEFAULT_INSPECTOR_WIDTH);
  const inspectorWidthRef = useRef(DEFAULT_INSPECTOR_WIDTH);
  const [inspectorResizing, setInspectorResizing] = useState(false);
  const inspectorResizeRef = useRef<{
    pointerId: number;
    startX: number;
    startWidth: number;
  } | undefined>(undefined);
  const [analysisRun, setAnalysisRun] = useState<OperatorAnalysisRun>();
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string>();
  const [copilotTurns, setCopilotTurns] = useState<OperatorCopilotTurn[]>([]);
  const [askingCopilot, setAskingCopilot] = useState(false);
  const [revealedEventCount, setRevealedEventCount] = useState(0);
  const [replayRunId, setReplayRunId] = useState<string>();
  const [workOrderDraft, setWorkOrderDraft] = useState<{
    annotationId: string;
    label: string;
  }>();
  const [workOrderAssignee, setWorkOrderAssignee] = useState("Annotation Lead");
  const [workOrderNote, setWorkOrderNote] = useState("");
  const [workOrderAttested, setWorkOrderAttested] = useState(false);
  const [contextMenu, setContextMenu] = useState<{
    annotationId: string;
    clientX: number;
    clientY: number;
  }>();

  requestedAssetIdRef.current = requestedAssetId;
  activeProjectIdRef.current = activeProject?.project_id;
  activeWorkspaceIdRef.current = workspaceId;
  selectedAssetIdRef.current = selectedAssetId;
  analysisRunIdRef.current = analysisRun?.analysis_run_id;
  dirtyRef.current = dirty;

  useEffect(() => {
    try {
      const savedWidth = Number(window.localStorage.getItem(INSPECTOR_WIDTH_STORAGE_KEY));
      if (Number.isFinite(savedWidth) && savedWidth > 0) {
        const next = clampInspectorWidth(savedWidth);
        inspectorWidthRef.current = next;
        setInspectorWidth(next);
      }
    } catch {
      // Local UI preference is optional; the workbench remains functional without it.
    }
    return () => {
      document.documentElement.classList.remove("is-resizing-inspector");
    };
  }, []);

  useEffect(() => {
    setAgentPanelView("OVERVIEW");
  }, [selectedAssetId, analysisRun?.analysis_run_id]);

  const invalidateWorkbookContext = useCallback(() => {
    contextGenerationRef.current += 1;
  }, []);

  const captureWorkbookContext = useCallback(
    (assetId: string, analysisRunId?: string): WorkbookAsyncContext | undefined => {
      const projectId = activeProjectIdRef.current;
      const currentWorkspaceId = activeWorkspaceIdRef.current;
      if (
        !currentWorkspaceId ||
        !projectId ||
        selectedAssetIdRef.current !== assetId
      ) {
        return undefined;
      }
      return {
        generation: contextGenerationRef.current,
        workspaceId: currentWorkspaceId,
        projectId,
        assetId,
        analysisRunId,
      };
    },
    [],
  );

  const isWorkbookContextCurrent = useCallback((context: WorkbookAsyncContext): boolean => {
    return (
      context.generation === contextGenerationRef.current &&
      context.workspaceId === activeWorkspaceIdRef.current &&
      context.projectId === activeProjectIdRef.current &&
      context.assetId === selectedAssetIdRef.current &&
      (!context.analysisRunId || context.analysisRunId === analysisRunIdRef.current)
    );
  }, []);

  const changeSelectedAsset = useCallback((assetId?: string) => {
    if (selectedAssetIdRef.current === assetId) return;
    invalidateWorkbookContext();
    selectedAssetIdRef.current = assetId;
    setSelectedAssetId(assetId);
  }, [invalidateWorkbookContext]);

  useEffect(
    () =>
      registerScopeChangeGuard((change) => {
        if (!dirtyRef.current) return true;
        const target =
          change.kind === "WORKSPACE"
            ? "工作空间"
            : change.kind === "CREATE_PROJECT"
              ? "新项目"
              : "项目";
        const confirmed = window.confirm(
          `当前标注尚未保存。放弃修改并切换到${target}吗？`,
        );
        if (confirmed) invalidateWorkbookContext();
        return confirmed;
      }),
    [invalidateWorkbookContext, registerScopeChangeGuard],
  );

  const selectedAsset = assets.find((asset) => asset.asset_id === selectedAssetId);
  const twinAsset = assets.find(
    (asset) => asset.asset_id === selectedAsset?.duplicate_of_asset_id,
  );
  const selectedAnnotation = annotations.find(
    (annotation) => annotation.annotation_id === selectedAnnotationId,
  );
  const sliceCounts = useMemo<Record<AssetSlice, number>>(() => ({
    ALL: assets.length,
    UNANNOTATED: assets.filter((asset) => asset.annotation_count === 0).length,
    DUPLICATE: assets.filter((asset) => Boolean(asset.duplicate_of_asset_id)).length,
    FLAGGED: assets.filter(isFlaggedAsset).length,
  }), [assets]);
  const filteredAssets = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return assets.filter((asset) => {
      const matchesQuery =
        !normalized ||
        `${asset.original_name} ${asset.format} ${asset.source_sha256}`
          .toLowerCase()
          .includes(normalized);
      if (!matchesQuery) return false;
      if (assetSlice === "UNANNOTATED") return asset.annotation_count === 0;
      if (assetSlice === "DUPLICATE") return Boolean(asset.duplicate_of_asset_id);
      if (assetSlice === "FLAGGED") return isFlaggedAsset(asset);
      return true;
    });
  }, [assetSlice, assets, query]);

  const refreshAssets = useCallback(async () => {
    const requestVersion = assetListRequestRef.current + 1;
    assetListRequestRef.current = requestVersion;
    setLoading(true);
    setError(undefined);
    setAssets([]);
    changeSelectedAsset(undefined);
    const projectId = activeProject?.project_id;
    if (!workspaceId || !projectId) {
      setLoading(false);
      return;
    }
    try {
      const next = await listOperatorImages(
        workspaceId,
        projectId,
        activeProject.source_kind === "synthetic_demo",
      );
      if (assetListRequestRef.current !== requestVersion) return;
      setAssets(next);
      const requested = requestedAssetIdRef.current;
      const preferred = next.find((asset) => asset.asset_id === requested)?.asset_id;
      changeSelectedAsset(preferred ?? next[0]?.asset_id);
    } catch (caught) {
      if (assetListRequestRef.current === requestVersion) {
        setError(messageForError(caught));
      }
    } finally {
      if (assetListRequestRef.current === requestVersion) setLoading(false);
    }
  }, [
    activeProject?.project_id,
    activeProject?.source_kind,
    changeSelectedAsset,
    workspaceId,
  ]);

  useEffect(() => {
    void refreshAssets();
  }, [refreshAssets]);

  useEffect(() => {
    if (!requestedAssetId || requestedAssetId === selectedAssetId || dirty) return;
    if (filteredAssets.some((asset) => asset.asset_id === requestedAssetId)) {
      changeSelectedAsset(requestedAssetId);
    }
  }, [changeSelectedAsset, dirty, filteredAssets, requestedAssetId, selectedAssetId]);

  useEffect(() => {
    if (loading || dirty) return;
    if (filteredAssets.some((asset) => asset.asset_id === selectedAssetId)) return;
    const nextAssetId = filteredAssets[0]?.asset_id;
    changeSelectedAsset(nextAssetId);
    setSearchParams(nextAssetId ? { asset: nextAssetId } : {}, { replace: true });
  }, [
    changeSelectedAsset,
    dirty,
    filteredAssets,
    loading,
    selectedAssetId,
    setSearchParams,
  ]);

  useEffect(() => {
    const assetToLoad = selectedAsset;
    if (!assetToLoad || !workspaceId) {
      setPreviewUrl(undefined);
      setAnnotationState(undefined);
      setAnnotations([]);
      setDirty(false);
      return undefined;
    }
    let active = true;
    let objectUrl: string | undefined;
    setError(undefined);
    setSelectedAnnotationId(undefined);
    void Promise.all([
      loadOperatorPreview(assetToLoad),
      loadOperatorAnnotations(workspaceId, assetToLoad.asset_id),
    ])
      .then(([nextPreviewUrl, nextAnnotationState]) => {
        objectUrl = nextPreviewUrl;
        if (!active) {
          URL.revokeObjectURL(nextPreviewUrl);
          return;
        }
        setPreviewUrl(nextPreviewUrl);
        setAnnotationState(nextAnnotationState);
        setAnnotations(nextAnnotationState.annotations);
        setDirty(false);
      })
      .catch((caught) => {
        if (active) setError(messageForError(caught));
      });
    return () => {
      active = false;
      const urlToRevoke = objectUrl;
      if (urlToRevoke) {
        window.setTimeout(() => URL.revokeObjectURL(urlToRevoke), 2_000);
      }
    };
  }, [activeProject?.project_id, selectedAsset?.asset_id, workspaceId]);

  useEffect(() => {
    const assetId = selectedAsset?.asset_id;
    const requestContext = assetId ? captureWorkbookContext(assetId) : undefined;
    if (!assetId || !workspaceId || !requestContext) {
      setAnalysisRun(undefined);
      setCopilotTurns([]);
      setAnalysisLoading(false);
      return undefined;
    }
    let active = true;
    setAnalysisLoading(true);
    setAnalysisError(undefined);
    setAnalysisRun(undefined);
    setCopilotTurns([]);
    void listOperatorAnalysisRuns(workspaceId, assetId)
      .then(async (runs) => {
        const latest = runs[0];
        const turns = latest
          ? await listOperatorCopilotTurns(
              requestContext.workspaceId,
              requestContext.assetId,
              latest.analysis_run_id,
            )
          : [];
        if (!active || !isWorkbookContextCurrent(requestContext)) return;
        setAnalysisRun(latest);
        setCopilotTurns(turns);
        setRevealedEventCount(latest?.events.length ?? 0);
        setReplayRunId(undefined);
      })
      .catch((caught) => {
        if (active && isWorkbookContextCurrent(requestContext)) {
          setAnalysisRun(undefined);
          setCopilotTurns([]);
          setAnalysisError(messageForError(caught));
        }
      })
      .finally(() => {
        if (active && isWorkbookContextCurrent(requestContext)) {
          setAnalysisLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [
    activeProject?.project_id,
    captureWorkbookContext,
    isWorkbookContextCurrent,
    selectedAsset?.asset_id,
    workspaceId,
  ]);

  useEffect(() => {
    if (!analysisRun) {
      setRevealedEventCount(0);
      return undefined;
    }
    if (analysisRun.analysis_run_id !== replayRunId) {
      setRevealedEventCount(analysisRun.events.length);
      return undefined;
    }
    let current = 0;
    setRevealedEventCount(0);
    const interval = window.setInterval(() => {
      current += 1;
      setRevealedEventCount(Math.min(current, analysisRun.events.length));
      if (current >= analysisRun.events.length) {
        window.clearInterval(interval);
        setReplayRunId(undefined);
      }
    }, 240);
    return () => window.clearInterval(interval);
  }, [analysisRun, replayRunId]);

  useEffect(() => {
    setProbeProfile(undefined);
    setComparisonMode("OFF");
    setContextMenu(undefined);
    setWorkOrderDraft(undefined);
    setWorkOrderAttested(false);
    setHighlightedAnnotationId(undefined);
    setSaving(false);
    setAnalyzing(false);
    setAskingCopilot(false);
    setIssuingWorkOrder(false);
  }, [activeProject?.project_id, selectedAsset?.asset_id, workspaceId]);

  const handleSelectedAnnotationChange = useCallback((annotationId?: string) => {
    setSelectedAnnotationId(annotationId);
    if (annotationId) setInspectorTab("PROPERTIES");
  }, []);

  useEffect(() => {
    if (!selectedAnnotationId || inspectorTab !== "PROPERTIES") return;
    const target = Array.from(
      annotationLedgerRef.current?.querySelectorAll<HTMLButtonElement>("[data-annotation-id]") ?? [],
    ).find((element) => element.dataset.annotationId === selectedAnnotationId);
    target?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [inspectorTab, selectedAnnotationId]);

  useEffect(() => {
    if (comparisonMode === "OFF" || !twinAsset) {
      setTwinPreviewUrl(undefined);
      return undefined;
    }
    let active = true;
    let objectUrl: string | undefined;
    void loadOperatorPreview(twinAsset)
      .then((nextUrl) => {
        objectUrl = nextUrl;
        if (!active) {
          URL.revokeObjectURL(nextUrl);
          return;
        }
        setTwinPreviewUrl(nextUrl);
      })
      .catch((caught) => {
        if (active) {
          setComparisonMode("OFF");
          setError(messageForError(caught));
        }
      });
    return () => {
      active = false;
      const urlToRevoke = objectUrl;
      if (urlToRevoke) window.setTimeout(() => URL.revokeObjectURL(urlToRevoke), 2_000);
    };
  }, [comparisonMode, twinAsset]);

  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if ((event.target as Element | null)?.closest?.(".canvas-context-menu")) return;
      setContextMenu(undefined);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setContextMenu(undefined);
        setWorkOrderDraft(undefined);
      }
    };
    window.addEventListener("pointerdown", closeOutside, true);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOutside, true);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  const chooseAsset = (assetId: string) => {
    if (assetId === selectedAssetId) return;
    if (dirty && !window.confirm("当前标注尚未保存。放弃修改并切换图片吗？")) return;
    changeSelectedAsset(assetId);
    setSearchParams({ asset: assetId }, { replace: true });
    setNotice(undefined);
  };

  const uploadFiles = async (files: File[]) => {
    if (!files.length) return;
    if (!workspaceId) {
      setError("请先选择一个可用工作空间。");
      return;
    }
    if (!activeProject) {
      setError("请先从左侧项目区创建或选择一个项目。");
      return;
    }
    const uploadWorkspaceId = workspaceId;
    const uploadProjectId = activeProject.project_id;
    if (dirty && !window.confirm("当前标注尚未保存。放弃修改并上传新图片吗？")) return;
    setUploading(true);
    setError(undefined);
    setNotice(undefined);
    try {
      const result = await uploadOperatorImages(uploadWorkspaceId, uploadProjectId, files);
      if (
        activeWorkspaceIdRef.current !== uploadWorkspaceId ||
        activeProjectIdRef.current !== uploadProjectId
      ) return;
      const next = [...result.assets, ...assets];
      setAssets(next);
      const first = result.assets[0];
      if (first) {
        changeSelectedAsset(first.asset_id);
        setSearchParams({ asset: first.asset_id }, { replace: true });
      }
      setNotice(
        `已导入 ${result.uploaded_count} 张图片到 ${activeWorkspace?.name ?? "当前工作空间"}；未自动运行 Agent。`,
      );
    } catch (caught) {
      if (
        activeWorkspaceIdRef.current === uploadWorkspaceId &&
        activeProjectIdRef.current === uploadProjectId
      ) {
        setError(messageForError(caught));
      }
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleFileInput = (event: ChangeEvent<HTMLInputElement>) => {
    void uploadFiles(Array.from(event.target.files ?? []));
  };

  const handleDatasetImported = (result: DatasetImportResult) => {
    if (
      result.workspaceId !== activeWorkspaceIdRef.current
      || result.projectId !== activeProjectIdRef.current
    ) {
      closeDatasetImport();
      setNotice(
        `数据集 ${result.datasetName} 已写入原项目，但当前项目已切换；为防止资产串台，当前列表未合并结果。切回原项目后刷新即可查看。`,
      );
      return;
    }
    const importedIds = new Set(result.assets.map((asset) => asset.asset_id));
    setAssets((current) => [
      ...result.assets,
      ...current.filter((asset) => !importedIds.has(asset.asset_id)),
    ]);
    const first = result.assets[0];
    if (first && !dirtyRef.current) {
      changeSelectedAsset(first.asset_id);
      setSearchParams({ asset: first.asset_id }, { replace: true });
    }
    setError(undefined);
    const rejected = result.rejectedImageCount > 0
      ? `；${result.rejectedImageCount} 张未导入`
      : "";
    const annotations = result.annotationFileCount > 0
      ? `；解析 ${result.annotationFileCount} 个标注文件并写入 ${result.importedBoxCount} 个框`
      : "；未发现可匹配标注";
    const warnings = result.warnings.length > 0
      ? `；${result.warnings.length} 项警告请在导入窗口查看`
      : "";
    setNotice(
      `数据集 ${result.datasetName} 已导入本地工作簿：${result.assets.length}/${result.selectedImageCount} 张图片${rejected}${annotations}${warnings}。未自动运行 Agent。`,
    );
  };

  const updateAnnotations = (next: BoundingBoxAnnotation[]) => {
    setAnnotations(next);
    setDirty(true);
    setNotice(undefined);
  };

  const save = useCallback(async () => {
    if (!selectedAsset || !annotationState || saving) return undefined;
    const requestContext = captureWorkbookContext(selectedAsset.asset_id);
    if (!requestContext) return undefined;
    if (!dirty) return annotationState;
    setSaving(true);
    setError(undefined);
    try {
      const saved = await saveOperatorAnnotations(
        requestContext.workspaceId,
        requestContext.assetId,
        annotationState.revision,
        annotations,
      );
      if (!isWorkbookContextCurrent(requestContext)) return undefined;
      setAnnotationState(saved);
      setAnnotations(saved.annotations);
      setDirty(false);
      setAssets((current) =>
        current.map((asset) =>
          asset.asset_id === requestContext.assetId
            ? {
                ...asset,
                annotation_count: saved.annotations.length,
                annotation_revision: saved.revision,
              }
            : asset,
        ),
      );
      setNotice(`标注 revision ${saved.revision} 已保存并生成 SHA-256 回执。`);
      return saved;
    } catch (caught) {
      if (isWorkbookContextCurrent(requestContext)) setError(messageForError(caught));
      return undefined;
    } finally {
      if (isWorkbookContextCurrent(requestContext)) setSaving(false);
    }
  }, [
    annotationState,
    annotations,
    captureWorkbookContext,
    dirty,
    isWorkbookContextCurrent,
    saving,
    selectedAsset,
  ]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement ||
        event.target instanceof HTMLSelectElement
      ) {
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save();
      }
      if (!event.ctrlKey && !event.metaKey && ["j", "k"].includes(event.key.toLowerCase())) {
        const currentIndex = filteredAssets.findIndex((asset) => asset.asset_id === selectedAssetId);
        const direction = event.key.toLowerCase() === "j" ? 1 : -1;
        const nextIndex = Math.max(0, Math.min(filteredAssets.length - 1, currentIndex + direction));
        const nextAsset = filteredAssets[nextIndex];
        if (nextAsset && nextAsset.asset_id !== selectedAssetId) {
          event.preventDefault();
          chooseAsset(nextAsset.asset_id);
        }
      }
      if (
        (event.key === "Delete" || event.key === "Backspace") &&
        selectedAnnotationId &&
        !(event.target instanceof HTMLInputElement)
      ) {
        event.preventDefault();
        updateAnnotations(
          annotations.filter((item) => item.annotation_id !== selectedAnnotationId),
        );
        setSelectedAnnotationId(undefined);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [annotations, filteredAssets, save, selectedAnnotationId, selectedAssetId]);

  const updateSelectedLabel = (label: string) => {
    if (!selectedAnnotationId) return;
    updateAnnotations(
      annotations.map((annotation) =>
        annotation.annotation_id === selectedAnnotationId ? { ...annotation, label } : annotation,
      ),
    );
  };

  const removeSelectedAnnotation = () => {
    if (!selectedAnnotationId) return;
    updateAnnotations(
      annotations.filter((annotation) => annotation.annotation_id !== selectedAnnotationId),
    );
    setSelectedAnnotationId(undefined);
  };

  const runAgentAnalysis = async () => {
    if (!selectedAsset || analyzing) return;
    const requestContext = captureWorkbookContext(selectedAsset.asset_id);
    if (!requestContext) return;
    setAnalyzing(true);
    setAnalysisError(undefined);
    setInspectorTab("AGENT");
    try {
      const savedState = await save();
      if (!savedState || !isWorkbookContextCurrent(requestContext)) return;
      const run = await createOperatorAnalysisRun(
        requestContext.workspaceId,
        requestContext.assetId,
      );
      if (!isWorkbookContextCurrent(requestContext)) return;
      analysisRunIdRef.current = run.analysis_run_id;
      setAnalysisRun(run);
      setCopilotTurns([]);
      setReplayRunId(run.analysis_run_id);
      setNotice(
        `Agent Trace ${run.analysis_run_id} 已落盘；${run.tool_call_count} 个本地工具，外发原图 0。`,
      );
    } catch (caught) {
      if (isWorkbookContextCurrent(requestContext)) {
        setAnalysisError(messageForError(caught));
      }
    } finally {
      if (isWorkbookContextCurrent(requestContext)) setAnalyzing(false);
    }
  };

  const handoffProjectToAgent = async () => {
    if (!workspaceId || !activeProject || assets.length === 0 || snapshotting) return;
    const handoffWorkspaceId = workspaceId;
    const handoffProjectId = activeProject.project_id;
    setSnapshotting(true);
    setError(undefined);
    try {
      if (dirty) {
        const saved = await save();
        if (!saved) return;
      }
      if (
        activeWorkspaceIdRef.current !== handoffWorkspaceId
        || activeProjectIdRef.current !== handoffProjectId
      ) return;
      const source = await authorizeOperatorProjectSnapshot({
        workspaceId: handoffWorkspaceId,
        projectId: handoffProjectId,
        displayName: `${activeProject.name} · 工作簿受控快照`,
      });
      if (
        activeWorkspaceIdRef.current !== handoffWorkspaceId
        || activeProjectIdRef.current !== handoffProjectId
      ) return;
      const binding = typeof source.data_profile.operator_snapshot_receipt_sha256 === "string"
        ? source.data_profile.operator_snapshot_receipt_sha256
        : source.source_archive_sha256;
      setNotice(`项目快照 ${source.source_id} 已封存 · binding ${shortDigest(binding)}；正在交给 Agent Task 工作台。`);
      navigate(`/command-center?create=1&source=${encodeURIComponent(source.source_id)}`);
    } catch (caught) {
      if (
        activeWorkspaceIdRef.current === handoffWorkspaceId
        && activeProjectIdRef.current === handoffProjectId
      ) setError(messageForError(caught));
    } finally {
      if (
        activeWorkspaceIdRef.current === handoffWorkspaceId
        && activeProjectIdRef.current === handoffProjectId
      ) setSnapshotting(false);
    }
  };

  const askCopilot = async (question: string) => {
    if (!selectedAsset || !analysisRun || askingCopilot) return;
    const requestContext = captureWorkbookContext(
      selectedAsset.asset_id,
      analysisRun.analysis_run_id,
    );
    if (!requestContext) return;
    setAskingCopilot(true);
    setAnalysisError(undefined);
    try {
      const turn = await createOperatorCopilotTurn(
        requestContext.workspaceId,
        requestContext.assetId,
        requestContext.analysisRunId!,
        question,
      );
      if (!isWorkbookContextCurrent(requestContext)) return;
      setCopilotTurns((current) => [...current, turn]);
    } catch (caught) {
      if (isWorkbookContextCurrent(requestContext)) {
        setAnalysisError(messageForError(caught));
      }
    } finally {
      if (isWorkbookContextCurrent(requestContext)) setAskingCopilot(false);
    }
  };

  const openWorkOrderReview = (annotationId?: string) => {
    const annotation = annotations.find(
      (item) => item.annotation_id === (annotationId ?? contextMenu?.annotationId),
    );
    if (!annotation) return;
    setWorkOrderDraft({
      annotationId: annotation.annotation_id,
      label: annotation.label,
    });
    setWorkOrderAssignee("Annotation Lead");
    setWorkOrderNote(`从像素现场签发：${annotation.label}`);
    setWorkOrderAttested(false);
    setContextMenu(undefined);
  };

  const issueWorkOrder = async () => {
    const annotationId = workOrderDraft?.annotationId;
    if (!selectedAsset || !annotationId || issuingWorkOrder) return;
    const requestContext = captureWorkbookContext(selectedAsset.asset_id);
    if (!requestContext) return;
    if (!workOrderAttested) {
      setError("必须由现场专业人员完成复核并勾选 AI 辅助边界确认。");
      return;
    }
    setIssuingWorkOrder(true);
    setError(undefined);
    try {
      const savedState = await save();
      if (!savedState || !isWorkbookContextCurrent(requestContext)) return;
      const annotation = savedState.annotations.find(
        (item) => item.annotation_id === annotationId,
      );
      if (!annotation) {
        if (isWorkbookContextCurrent(requestContext)) {
          setError("选中的标注不在已保存版本中，无法签发工单。");
        }
        return;
      }
      const workOrder = await createOperatorWorkOrder(
        requestContext.workspaceId,
        requestContext.assetId,
        annotation.annotation_id,
        savedState.revision,
        {
          assignee: workOrderAssignee.trim() || "Annotation Lead",
          note: workOrderNote.trim(),
          operatorAttestsReviewedEvidence: true,
        },
      );
      if (!isWorkbookContextCurrent(requestContext)) return;
      setNotice(
        `工单 ${workOrder.work_order_id} 已写入本地 CAPA 队列；绑定 annotation revision ${workOrder.annotation_revision}。`,
      );
      setWorkOrderDraft(undefined);
      setInspectorTab("AGENT");
    } catch (caught) {
      if (isWorkbookContextCurrent(requestContext)) setError(messageForError(caught));
    } finally {
      if (isWorkbookContextCurrent(requestContext)) setIssuingWorkOrder(false);
    }
  };

  const openTwinComparison = () => {
    if (!twinAsset) return;
    setComparisonMode((current) => (current === "OFF" ? "CURTAIN" : "OFF"));
  };

  const persistInspectorWidth = (value: number) => {
    const next = clampInspectorWidth(value);
    inspectorWidthRef.current = next;
    setInspectorWidth(next);
    try {
      window.localStorage.setItem(INSPECTOR_WIDTH_STORAGE_KEY, String(next));
    } catch {
      // A denied storage write must not block direct manipulation.
    }
  };

  const startInspectorResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    inspectorResizeRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: inspectorWidth,
    };
    setInspectorResizing(true);
    document.documentElement.classList.add("is-resizing-inspector");
  };

  const resizeInspector = (event: ReactPointerEvent<HTMLDivElement>) => {
    const active = inspectorResizeRef.current;
    if (!active || active.pointerId !== event.pointerId) return;
    const next = clampInspectorWidth(active.startWidth + active.startX - event.clientX);
    inspectorWidthRef.current = next;
    setInspectorWidth(next);
  };

  const finishInspectorResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    const active = inspectorResizeRef.current;
    if (!active || active.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    inspectorResizeRef.current = undefined;
    setInspectorResizing(false);
    document.documentElement.classList.remove("is-resizing-inspector");
    persistInspectorWidth(inspectorWidthRef.current);
  };

  const resizeInspectorWithKeyboard = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 24 : 8;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      persistInspectorWidth(inspectorWidth + step);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      persistInspectorWidth(inspectorWidth - step);
    } else if (event.key === "Home") {
      event.preventDefault();
      persistInspectorWidth(DEFAULT_INSPECTOR_WIDTH);
    }
  };

  const contextAnnotation = annotations.find(
    (annotation) => annotation.annotation_id === contextMenu?.annotationId,
  );
  const traceStale = Boolean(
    analysisRun &&
      (dirty || analysisRun.annotation_revision !== (annotationState?.revision ?? 0)),
  );
  const operatorGridStyle = {
    "--operator-inspector-width": inspectorWidth + "px",
  } as CSSProperties;

  const closeTour = () => {
    setTourOpen(false);
    if (searchParams.has("tour")) {
      const next = new URLSearchParams(searchParams);
      next.delete("tour");
      setSearchParams(next, { replace: true });
    }
  };

  function closeDatasetImport() {
    setDatasetImportOpen(false);
    if (searchParams.has("import")) {
      const next = new URLSearchParams(searchParams);
      next.delete("import");
      setSearchParams(next, { replace: true });
    }
  }

  return (
    <div className="operator-workspace">
      <input
        ref={inputRef}
        className="sr-only"
        type="file"
        accept=".jpg,.jpeg,.png,.bmp,.tif,.tiff,.webp,image/*"
        multiple
        onChange={handleFileInput}
      />
      <header className="operator-commandbar">
        <div className="operator-commandbar__title">
          <span className="operator-kicker">CURRENT WORKBOOK</span>
          <strong>{activeProject?.name ?? "工业视觉工作簿"}</strong>
          <span>{activeWorkspace?.name ?? "未选择工作空间"} · {assets.length} assets · J/K navigate</span>
        </div>
        <div className="operator-commandbar__actions">
          <button type="button" onClick={() => setTourOpen(true)}>
            <Sparkles size={15} />
            工作台指南
          </button>
          <button type="button" onClick={() => void refreshAssets()} disabled={loading}>
            <RefreshCcw size={15} className={loading ? "is-spinning" : ""} />
            刷新
          </button>
          <button
            type="button"
            onClick={() => setDatasetImportOpen(true)}
            disabled={uploading || !workspaceId || !activeProject}
          >
            <FolderOpen size={15} />
            导入数据集
          </button>
          <button
            type="button"
            data-tour-target="upload"
            onClick={() => inputRef.current?.click()}
            disabled={uploading || !activeProject}
          >
            {uploading ? <LoaderCircle size={15} className="is-spinning" /> : <Upload size={15} />}
            导入图像
          </button>
          <button
            type="button"
            className="is-primary"
            onClick={() => void save()}
            disabled={!dirty || saving}
          >
            {saving ? <LoaderCircle size={15} className="is-spinning" /> : <Save size={15} />}
            保存标注 <kbd>Ctrl S</kbd>
          </button>
          <button
            type="button"
            className="is-primary"
            onClick={() => void handoffProjectToAgent()}
            disabled={snapshotting || saving || assets.length === 0 || !activeProject}
            title="服务端核验全部项目资产与标注 revision，封存不可变快照后交给 Product Agent"
          >
            {snapshotting ? <LoaderCircle size={15} className="is-spinning" /> : <ShieldCheck size={15} />}
            {snapshotting ? "正在封存快照…" : "冻结项目并交给 Agent"}
          </button>
        </div>
      </header>

      {error ? (
        <div className="operator-message is-error" role="alert">
          <AlertTriangle size={16} />
          <span>{error}</span>
          <button type="button" onClick={() => setError(undefined)} aria-label="关闭错误">
            <X size={15} />
          </button>
        </div>
      ) : null}
      {notice ? (
        <div className="operator-message is-success" role="status">
          <Check size={16} />
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice(undefined)} aria-label="关闭提示">
            <X size={15} />
          </button>
        </div>
      ) : null}

      <div className="operator-grid" style={operatorGridStyle}>
        <aside className="asset-browser" aria-label="本地图像列表" data-tour-target="assets">
          <div className="asset-browser__header">
            <strong><Files size={14} /> INPUT IMAGES</strong>
            <span>{filteredAssets.length}/{assets.length}</span>
          </div>
          <label className="asset-search">
            <Search size={14} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="按文件名或 SHA 搜索"
            />
          </label>
          <div className="asset-slice-bar" aria-label="资产切片">
            {([
              ["ALL", "全部"],
              ["UNANNOTATED", "未标注"],
              ["DUPLICATE", "重复"],
              ["FLAGGED", "异常"],
            ] as const).map(([value, label]) => (
              <button
                type="button"
                key={value}
                className={assetSlice === value ? "is-active" : ""}
                onClick={() => setAssetSlice(value)}
                aria-pressed={assetSlice === value}
                title={`${label} · 当前项目 ${sliceCounts[value]} 张`}
              >
                <span>{label}</span>
                <em>{sliceCounts[value]}</em>
              </button>
            ))}
          </div>
          <DropZone
            compact
            disabled={uploading || !activeProject}
            onFiles={(files) => void uploadFiles(files)}
            onBrowse={() => inputRef.current?.click()}
          />
          <div className="asset-list">
            {loading || workspaceLoading ? (
              <div className="asset-list__empty"><LoaderCircle size={18} className="is-spinning" /> 读取本地资产…</div>
            ) : null}
            {!loading && filteredAssets.length === 0 ? (
              <div className="asset-list__empty"><FileImage size={18} /> 暂无匹配图片</div>
            ) : null}
            {filteredAssets.map((asset) => (
              <button
                type="button"
                key={asset.asset_id}
                className={asset.asset_id === selectedAssetId ? "is-active" : ""}
                onClick={() => chooseAsset(asset.asset_id)}
              >
                <FileImage size={16} />
                <span>
                  <strong>{asset.original_name}</strong>
                  <small>{asset.width}×{asset.height} · {formatBytes(asset.byte_size)}</small>
                </span>
                <em>{asset.annotation_count}</em>
              </button>
            ))}
          </div>
          <footer className="asset-browser__footer">
            <HardDrive size={13} /> output/product/operator_workspace
          </footer>
        </aside>

        <main className="operator-editor" data-tour-target="canvas">
          {selectedAsset && previewUrl ? (
            <InteractiveImageCanvas
              asset={selectedAsset}
              previewUrl={previewUrl}
              annotations={annotations}
              selectedAnnotationId={selectedAnnotationId}
              highlightedAnnotationId={highlightedAnnotationId}
              twinAsset={twinAsset}
              twinPreviewUrl={twinPreviewUrl}
              comparisonMode={comparisonMode}
              onComparisonModeChange={setComparisonMode}
              onAnnotationsChange={updateAnnotations}
              onSelectedAnnotationChange={handleSelectedAnnotationChange}
              onHighlightedAnnotationChange={setHighlightedAnnotationId}
              onProbeProfileChange={setProbeProfile}
              onAnnotationContextMenu={(annotationId, position) =>
                setContextMenu({ annotationId, ...position })
              }
            />
          ) : (
            <div className="operator-empty-canvas">
              {loading || workspaceLoading ? (
                <><LoaderCircle size={28} className="is-spinning" /><strong>正在连接本地工作区…</strong></>
              ) : !workspaceId ? (
                <><CloudOff size={32} /><strong>没有可用工作空间</strong><span>请检查本地 API 与工作空间配置。</span></>
              ) : !activeProject ? (
                <><Files size={32} /><strong>先创建一个项目</strong><span>从左侧 PROJECTS 的加号建立空项目；系统不会自动填入数据。</span></>
              ) : error && assets.length === 0 ? (
                <><CloudOff size={32} /><strong>本地 API 未连接</strong><span>启动 API 后即可继续当前工作。</span></>
              ) : (
                <section className="operator-empty-guide" aria-label="图像工作簿开始步骤">
                  <header>
                    <span><ImagePlus size={22} /></span>
                    <div>
                      <small>START WITH SOURCE DATA</small>
                      <strong>把真实图像放进当前项目</strong>
                      <p>文件先在本地完成摘要与解码校验；导入本身不会生成检测结论。</p>
                    </div>
                  </header>
                  <DropZone
                    disabled={uploading || !activeProject}
                    onFiles={(files) => void uploadFiles(files)}
                    onBrowse={() => inputRef.current?.click()}
                  />
                  <ol>
                    <li><span>01</span><div><strong>导入</strong><small>图片或数据集清单</small></div></li>
                    <li><span>02</span><div><strong>检查</strong><small>像素、标注与重复项</small></div></li>
                    <li><span>03</span><div><strong>交接</strong><small>人工确认后封存给 Agent</small></div></li>
                  </ol>
                </section>
              )}
            </div>
          )}
        </main>

        <div
          className={"operator-inspector-resizer" + (inspectorResizing ? " is-active" : "")}
          role="separator"
          aria-label="调整图片检查器与 Agent 面板宽度"
          aria-orientation="vertical"
          aria-valuemin={MIN_INSPECTOR_WIDTH}
          aria-valuemax={MAX_INSPECTOR_WIDTH}
          aria-valuenow={inspectorWidth}
          aria-valuetext={inspectorWidth + " 像素"}
          tabIndex={0}
          title="拖动调整右侧面板宽度 · 双击恢复默认"
          onPointerDown={startInspectorResize}
          onPointerMove={resizeInspector}
          onPointerUp={finishInspectorResize}
          onPointerCancel={finishInspectorResize}
          onDoubleClick={() => persistInspectorWidth(DEFAULT_INSPECTOR_WIDTH)}
          onKeyDown={resizeInspectorWithKeyboard}
        >
          <span aria-hidden="true" />
          <output aria-hidden="true">{inspectorWidth}px</output>
        </div>

        <aside className="operator-inspector" aria-label="图片检查器与 Agent Copilot">
          <div className="inspector-tabbar" role="tablist" aria-label="右侧工作面板">
            <button
              type="button"
              role="tab"
              aria-selected={inspectorTab === "PROPERTIES"}
              className={inspectorTab === "PROPERTIES" ? "is-active" : ""}
              onClick={() => setInspectorTab("PROPERTIES")}
            >
              <SlidersHorizontal size={12} /> INSPECTOR
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={inspectorTab === "AGENT"}
              data-tour-target="agent"
              className={inspectorTab === "AGENT" ? "is-active" : ""}
              onClick={() => setInspectorTab("AGENT")}
            >
              <Bot size={12} /> AGENT
              {analysisRun ? <i className="agent-live-dot" /> : null}
            </button>
            {dirty ? <strong className="unsaved-dot">UNSAVED</strong> : <strong>SAVED</strong>}
          </div>
          {inspectorTab === "AGENT" ? (
            selectedAsset ? (
              <OperatorAgentPanel
                asset={selectedAsset}
                run={analysisRun}
                turns={copilotTurns}
                loading={analysisLoading}
                analyzing={analyzing}
                asking={askingCopilot}
                error={analysisError}
                traceStale={traceStale}
                revealedEventCount={revealedEventCount}
                selectedAnnotationLabel={selectedAnnotation?.label}
                activeView={agentPanelView}
                onActiveViewChange={setAgentPanelView}
                onRun={() => void runAgentAnalysis()}
                onAsk={(question) => void askCopilot(question)}
                onCreateWorkOrder={() => openWorkOrderReview(selectedAnnotationId)}
                onOpenCapa={() => navigate("/capa")}
                onOpenEvidence={() => navigate("/evidence")}
                onOpenTaskWorkbench={() => navigate("/command-center")}
              />
            ) : (
              <div className="inspector-empty"><Bot size={22} />选择一张图片运行 Agent 取证</div>
            )
          ) : !selectedAsset ? (
            <div className="inspector-empty"><FileImage size={22} />选择一张图片查看属性</div>
          ) : (
            <>
              <section className="inspector-section">
                <header><FileImage size={14} /> IMAGE</header>
                <dl className="property-list">
                  <div><dt>name</dt><dd>{selectedAsset.original_name}</dd></div>
                  <div><dt>size</dt><dd>{selectedAsset.width} × {selectedAsset.height}</dd></div>
                  <div><dt>format</dt><dd>{selectedAsset.format} / {selectedAsset.mode}</dd></div>
                  <div><dt>bytes</dt><dd>{formatBytes(selectedAsset.byte_size)}</dd></div>
                  <div><dt>sha256</dt><dd title={selectedAsset.source_sha256}>{shortDigest(selectedAsset.source_sha256)}</dd></div>
                  <div><dt>storage</dt><dd>LOCAL_ONLY</dd></div>
                </dl>
                {selectedAsset.duplicate_of_asset_id ? (
                  <button
                    type="button"
                    className={`duplicate-warning${comparisonMode !== "OFF" ? " is-active" : ""}`}
                    onClick={openTwinComparison}
                    disabled={!twinAsset}
                    title="打开真实双图卷帘与像素差值比对"
                  >
                    <Clipboard size={13} />
                    <span>与 {selectedAsset.duplicate_of_asset_id} 字节重复</span>
                    <em>{comparisonMode === "OFF" ? "COMPARE" : "CLOSE"}</em>
                  </button>
                ) : null}
              </section>

              <section className="inspector-section">
                <header><ShieldCheck size={14} /> DETERMINISTIC INSPECTION</header>
                <div className="inspection-metrics">
                  <article><span>Mean luma</span><strong>{selectedAsset.inspection.mean_luma.toFixed(2)}</strong></article>
                  <article><span>Contrast σ</span><strong>{selectedAsset.inspection.contrast_std.toFixed(2)}</strong></article>
                  <article><span>Edge energy</span><strong>{selectedAsset.inspection.edge_energy.toFixed(2)}</strong></article>
                  <article><span>Clip B/W</span><strong>{(selectedAsset.inspection.black_clip_ratio * 100).toFixed(2)} / {(selectedAsset.inspection.white_clip_ratio * 100).toFixed(2)}%</strong></article>
                </div>
                <small className="metric-boundary">确定性像素统计，不是模型结论或质量放行。</small>
              </section>

              <section className="inspector-section">
                <header><Activity size={14} /> OPTICAL PROFILE <span>SHIFT + DRAG</span></header>
                {probeProfile ? (
                  <OpticalProbeChart profile={probeProfile} />
                ) : (
                  <p className="annotation-hint">
                    选择“剖面探针”或按住 Shift 穿过缺陷划线，读取真实本地预览的 I(x) 与 |∇I|。
                  </p>
                )}
              </section>

              <section className="inspector-section annotation-inspector">
                <header><Tag size={14} /> ANNOTATIONS <span>{annotations.length}</span></header>
                {selectedAnnotation ? (
                  <div className="annotation-form">
                    <label>
                      <span>Label</span>
                      <input
                        value={selectedAnnotation.label}
                        onChange={(event) => updateSelectedLabel(event.target.value)}
                      />
                    </label>
                    <div className="box-coordinates">
                      <span>x {(selectedAnnotation.x * selectedAsset.width).toFixed(1)}</span>
                      <span>y {(selectedAnnotation.y * selectedAsset.height).toFixed(1)}</span>
                      <span>w {(selectedAnnotation.width * selectedAsset.width).toFixed(1)}</span>
                      <span>h {(selectedAnnotation.height * selectedAsset.height).toFixed(1)}</span>
                    </div>
                    <div className="annotation-form__actions">
                      <button
                        type="button"
                        className="capa-text-button"
                        onClick={() => openWorkOrderReview(selectedAnnotation.annotation_id)}
                        disabled={issuingWorkOrder}
                      >
                        <ClipboardPlus size={14} /> 创建整改工单
                      </button>
                      <button type="button" className="danger-text-button" onClick={removeSelectedAnnotation}>
                        <Trash2 size={14} /> 删除选中框
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="annotation-hint">点击工具栏“框选”，在图片上拖动创建真实标注。</p>
                )}
                <div className="annotation-ledger" ref={annotationLedgerRef}>
                  {annotations.map((annotation, index) => (
                    <button
                      type="button"
                      key={annotation.annotation_id}
                      data-annotation-id={annotation.annotation_id}
                      className={[
                        annotation.annotation_id === selectedAnnotationId ? "is-active" : "",
                        annotation.annotation_id === highlightedAnnotationId
                          ? "is-highlighted"
                          : "",
                      ].filter(Boolean).join(" ")}
                      onClick={() => setSelectedAnnotationId(annotation.annotation_id)}
                      onContextMenu={(event) => {
                        event.preventDefault();
                        setSelectedAnnotationId(annotation.annotation_id);
                        setContextMenu({
                          annotationId: annotation.annotation_id,
                          clientX: event.clientX,
                          clientY: event.clientY,
                        });
                      }}
                      onMouseEnter={() => setHighlightedAnnotationId(annotation.annotation_id)}
                      onMouseLeave={() => setHighlightedAnnotationId(undefined)}
                    >
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <strong>{annotation.label}</strong>
                      <small>MANUAL</small>
                    </button>
                  ))}
                </div>
              </section>

              <footer className="inspector-receipt">
                <span>annotation revision</span>
                <strong>{annotationState?.revision ?? 0}</strong>
                <code title={annotationState?.document_sha256}>{annotationState ? shortDigest(annotationState.document_sha256) : "not loaded"}</code>
              </footer>
            </>
          )}
        </aside>
      </div>
      {contextMenu && contextAnnotation && selectedAsset ? (
        <div
          className="canvas-context-menu"
          style={{
            left: Math.min(contextMenu.clientX, window.innerWidth - 258),
            top: Math.min(contextMenu.clientY, window.innerHeight - 190),
          }}
          role="menu"
          aria-label="缺陷标注操作"
        >
          <header>
            <strong>{contextAnnotation.label}</strong>
            <small>
              x {Math.round(contextAnnotation.x * selectedAsset.width)} · y{" "}
              {Math.round(contextAnnotation.y * selectedAsset.height)} · w{" "}
              {Math.round(contextAnnotation.width * selectedAsset.width)} · h{" "}
              {Math.round(contextAnnotation.height * selectedAsset.height)}
            </small>
          </header>
          <button
            type="button"
            onClick={() => openWorkOrderReview()}
            role="menuitem"
          >
            <ClipboardPlus size={15} />
            <span>创建整改工单草稿</span>
            <kbd>CAPA</kbd>
          </button>
          <button
            type="button"
            onClick={() => {
              const next = window.prompt("输入新的缺陷类别", contextAnnotation.label)?.trim();
              if (next) {
                updateAnnotations(
                  annotations.map((annotation) =>
                    annotation.annotation_id === contextAnnotation.annotation_id
                      ? { ...annotation, label: next }
                      : annotation,
                  ),
                );
              }
              setContextMenu(undefined);
            }}
            role="menuitem"
          >
            <Tag size={15} />
            <span>快速更名类别</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setContextMenu(undefined);
              navigate("/capa");
            }}
            role="menuitem"
          >
            <ExternalLink size={15} />
            <span>打开 CAPA 队列</span>
          </button>
        </div>
      ) : null}
      {workOrderDraft && selectedAsset ? (
        <div className="human-review-overlay" role="presentation">
          <section
            className="human-review-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="human-review-title"
          >
            <header>
              <span><UserCheck size={18} /></span>
              <div>
                <small>HUMAN-IN-THE-LOOP GATE</small>
                <strong id="human-review-title">复核并创建本地 CAPA 工单</strong>
              </div>
              <button type="button" onClick={() => setWorkOrderDraft(undefined)} aria-label="关闭">
                <X size={16} />
              </button>
            </header>
            <div className="human-review-binding">
              <span>缺陷标注</span><strong>{workOrderDraft.label}</strong>
              <span>图片 SHA</span><code>{shortDigest(selectedAsset.source_sha256)}</code>
              <span>annotation rev</span>
              <code>
                {dirty
                  ? `待保存（当前 ${annotationState?.revision ?? 0}）`
                  : annotationState?.revision ?? 0}
              </code>
            </div>
            <label className="human-review-field">
              <span>责任人</span>
              <input
                value={workOrderAssignee}
                onChange={(event) => setWorkOrderAssignee(event.target.value)}
                maxLength={120}
                required
              />
            </label>
            <label className="human-review-field">
              <span>复核说明</span>
              <textarea
                value={workOrderNote}
                onChange={(event) => setWorkOrderNote(event.target.value)}
                maxLength={1000}
                rows={3}
                required
              />
              <small>提交时会先保存标注，并把工单绑定到后端返回的最新 revision。</small>
            </label>
            <label className={`human-review-attestation${workOrderAttested ? " is-checked" : ""}`}>
              <input
                type="checkbox"
                checked={workOrderAttested}
                onChange={(event) => setWorkOrderAttested(event.target.checked)}
              />
              <span>
                <strong>我已完成现场专业复核</strong>
                <small>
                  我已知晓 AI/Agent 建议仅供辅助参考；该操作只创建本地工单，
                  不授予生产放行或设备写入权限。
                </small>
              </span>
            </label>
            <footer>
              <button type="button" onClick={() => setWorkOrderDraft(undefined)} disabled={issuingWorkOrder}>
                取消
              </button>
              <button
                type="button"
                className="is-primary"
                onClick={() => void issueWorkOrder()}
                disabled={
                  issuingWorkOrder ||
                  !workOrderAttested ||
                  !workOrderAssignee.trim() ||
                  !workOrderNote.trim()
                }
              >
                {issuingWorkOrder ? <LoaderCircle size={15} className="is-spinning" /> : <ClipboardPlus size={15} />}
                {issuingWorkOrder ? "正在写入账本…" : "确认并创建工单"}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
      {datasetImportOpen && workspaceId && activeProject ? (
        <DatasetImportDialog
          workspaceId={workspaceId}
          projectId={activeProject.project_id}
          onClose={closeDatasetImport}
          onImported={handleDatasetImported}
        />
      ) : null}
      {tourOpen ? <OperatorWorkspaceTour onClose={closeTour} /> : null}
    </div>
  );
}

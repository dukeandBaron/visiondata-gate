import {
  AlertTriangle,
  Download,
  FileImage,
  Focus,
  Gauge,
  ImagePlus,
  LockKeyhole,
  MousePointer2,
  ScanLine,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Panel, PanelHeader, StatusBadge } from "./ui";
import "../styles/browser-local-image-lab.css";

const MAX_FILE_BYTES = 32 * 1024 * 1024;
const MAX_IMAGE_PIXELS = 48_000_000;
const MAX_ASSETS = 8;
const MEASUREMENT_EDGE = 720;
const ACCEPTED_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/bmp",
]);
const ACCEPTED_EXTENSIONS = /\.(?:jpe?g|png|webp|bmp)$/i;

interface PixelMeasurements {
  meanLuma: number;
  underexposedRatio: number;
  overexposedRatio: number;
  laplacianVariance: number;
  sampledWidth: number;
  sampledHeight: number;
  signal: "UNDEREXPOSED" | "OVEREXPOSED" | "LOW_SHARPNESS" | "MEASURED";
}

interface LocalAsset {
  id: string;
  name: string;
  type: string;
  sizeBytes: number;
  width: number;
  height: number;
  sha256: string;
  objectUrl: string;
  duplicateOf?: string;
  measurements: PixelMeasurements;
}

interface LocalBox {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
}

interface DraftBox {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 / 1024).toFixed(2)} MiB`;
}

function compactDigest(value: string): string {
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

function percentage(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function toHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
}

function detectRasterType(bytes: ArrayBuffer): LocalAsset["type"] | undefined {
  const value = new Uint8Array(bytes);
  if (value.length >= 8 && value[0] === 0x89 && value[1] === 0x50 && value[2] === 0x4e && value[3] === 0x47 && value[4] === 0x0d && value[5] === 0x0a && value[6] === 0x1a && value[7] === 0x0a) return "image/png";
  if (value.length >= 3 && value[0] === 0xff && value[1] === 0xd8 && value[2] === 0xff) return "image/jpeg";
  if (value.length >= 12 && String.fromCharCode(...value.slice(0, 4)) === "RIFF" && String.fromCharCode(...value.slice(8, 12)) === "WEBP") return "image/webp";
  if (value.length >= 2 && value[0] === 0x42 && value[1] === 0x4d) return "image/bmp";
  return undefined;
}

function classifyMeasurement(
  underexposedRatio: number,
  overexposedRatio: number,
  laplacianVariance: number,
): PixelMeasurements["signal"] {
  if (underexposedRatio >= 0.35) return "UNDEREXPOSED";
  if (overexposedRatio >= 0.35) return "OVEREXPOSED";
  if (laplacianVariance < 80) return "LOW_SHARPNESS";
  return "MEASURED";
}

async function inspectFile(file: File): Promise<LocalAsset> {
  const normalizedType = file.type.toLowerCase();
  if (
    !ACCEPTED_EXTENSIONS.test(file.name) ||
    (normalizedType !== "" && !ACCEPTED_TYPES.has(normalizedType))
  ) {
    throw new Error(`${file.name}：仅支持 JPEG、PNG、WebP 或 BMP。`);
  }
  if (file.size <= 0 || file.size > MAX_FILE_BYTES) {
    throw new Error(`${file.name}：文件必须小于或等于 32 MiB。`);
  }

  const bytes = await file.arrayBuffer();
  const detectedType = detectRasterType(bytes);
  if (!detectedType) {
    throw new Error(`${file.name}：文件签名不是受支持的栅格图片。`);
  }
  const sha256 = toHex(await crypto.subtle.digest("SHA-256", bytes));
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new Error(`${file.name}：当前浏览器无法安全解码该图片。`);
  }
  try {
    if (
      bitmap.width <= 0 ||
      bitmap.height <= 0 ||
      bitmap.width * bitmap.height > MAX_IMAGE_PIXELS
    ) {
      throw new Error(`${file.name}：图片像素总量超过 4800 万限制。`);
    }

    const scale = Math.min(1, MEASUREMENT_EDGE / Math.max(bitmap.width, bitmap.height));
    const sampledWidth = Math.max(3, Math.round(bitmap.width * scale));
    const sampledHeight = Math.max(3, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = sampledWidth;
    canvas.height = sampledHeight;
    const context = canvas.getContext("2d", {
      alpha: false,
      willReadFrequently: true,
    });
    if (!context) throw new Error(`${file.name}：浏览器 Canvas 不可用。`);
    context.drawImage(bitmap, 0, 0, sampledWidth, sampledHeight);
    const rgba = context.getImageData(0, 0, sampledWidth, sampledHeight).data;
    const gray = new Float32Array(sampledWidth * sampledHeight);
    let lumaSum = 0;
    let underexposed = 0;
    let overexposed = 0;
    for (let pixel = 0, offset = 0; pixel < gray.length; pixel += 1, offset += 4) {
      const luma =
        rgba[offset]! * 0.2126 +
        rgba[offset + 1]! * 0.7152 +
        rgba[offset + 2]! * 0.0722;
      gray[pixel] = luma;
      lumaSum += luma;
      if (luma < 32) underexposed += 1;
      if (luma > 235) overexposed += 1;
    }

    let laplacianSum = 0;
    let laplacianSquareSum = 0;
    let laplacianCount = 0;
    for (let y = 1; y < sampledHeight - 1; y += 1) {
      const row = y * sampledWidth;
      for (let x = 1; x < sampledWidth - 1; x += 1) {
        const index = row + x;
        const laplacian =
          4 * gray[index]! -
          gray[index - 1]! -
          gray[index + 1]! -
          gray[index - sampledWidth]! -
          gray[index + sampledWidth]!;
        laplacianSum += laplacian;
        laplacianSquareSum += laplacian * laplacian;
        laplacianCount += 1;
      }
    }
    const laplacianMean = laplacianCount ? laplacianSum / laplacianCount : 0;
    const laplacianVariance = laplacianCount
      ? Math.max(0, laplacianSquareSum / laplacianCount - laplacianMean ** 2)
      : 0;
    const underexposedRatio = underexposed / gray.length;
    const overexposedRatio = overexposed / gray.length;

    return {
      id: crypto.randomUUID(),
      name: file.name,
      type: detectedType,
      sizeBytes: file.size,
      width: bitmap.width,
      height: bitmap.height,
      sha256,
      objectUrl: URL.createObjectURL(file),
      measurements: {
        meanLuma: lumaSum / gray.length,
        underexposedRatio,
        overexposedRatio,
        laplacianVariance,
        sampledWidth,
        sampledHeight,
        signal: classifyMeasurement(
          underexposedRatio,
          overexposedRatio,
          laplacianVariance,
        ),
      },
    };
  } finally {
    bitmap.close();
  }
}

function normalizedDraft(draft: DraftBox): Omit<LocalBox, "id" | "label"> {
  return {
    x: Math.min(draft.startX, draft.endX),
    y: Math.min(draft.startY, draft.endY),
    width: Math.abs(draft.endX - draft.startX),
    height: Math.abs(draft.endY - draft.startY),
  };
}

export function BrowserLocalImageLab() {
  const [assets, setAssets] = useState<LocalAsset[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [annotations, setAnnotations] = useState<Record<string, LocalBox[]>>({});
  const [draft, setDraft] = useState<DraftBox>();
  const [busy, setBusy] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string>();
  const inputRef = useRef<HTMLInputElement>(null);
  const assetsRef = useRef<LocalAsset[]>([]);

  useEffect(() => {
    assetsRef.current = assets;
  }, [assets]);

  useEffect(() => () => {
    assetsRef.current.forEach((asset) => URL.revokeObjectURL(asset.objectUrl));
  }, []);

  const activeAsset = assets.find((asset) => asset.id === selectedId) ?? assets[0];
  const activeBoxes = activeAsset ? annotations[activeAsset.id] ?? [] : [];
  const signalTone = activeAsset?.measurements.signal === "MEASURED" ? "success" : "warning";
  const trace = useMemo(() => {
    if (!activeAsset) return [];
    const items = [
      ["INPUT", "图片由当前标签页解码", `${activeAsset.width} × ${activeAsset.height}`],
      ["HASH", "原始文件字节 SHA-256", compactDigest(activeAsset.sha256)],
      ["PIXEL", "浏览器本地快速筛查", activeAsset.measurements.signal],
    ];
    if (activeAsset.duplicateOf) {
      items.push(["DUPLICATE", "发现同会话完全相同字节", activeAsset.duplicateOf]);
    }
    if (activeBoxes.length) {
      items.push(["ANNOTATION", "本地框选区域", `${activeBoxes.length} boxes`]);
    }
    return items;
  }, [activeAsset, activeBoxes.length]);

  const addFiles = async (incoming: FileList | File[]) => {
    if (busy) return;
    const candidates = Array.from(incoming).slice(0, Math.max(0, MAX_ASSETS - assets.length));
    if (!candidates.length) {
      setError(assets.length >= MAX_ASSETS ? "当前会话最多导入 8 张图片。" : undefined);
      return;
    }
    setBusy(true);
    setError(undefined);
    const inspected: LocalAsset[] = [];
    const failures: string[] = [];
    for (const file of candidates) {
      try {
        const asset = await inspectFile(file);
        const duplicate = [...assets, ...inspected].find(
          (candidate) => candidate.sha256 === asset.sha256,
        );
        inspected.push({ ...asset, duplicateOf: duplicate?.name });
      } catch (caught) {
        failures.push(caught instanceof Error ? caught.message : `${file.name}：读取失败。`);
      }
    }
    if (inspected.length) {
      setAssets((current) => [...current, ...inspected]);
      setSelectedId(inspected[0]!.id);
    }
    if (failures.length) setError(failures.join(" "));
    setBusy(false);
  };

  const clearSession = () => {
    assets.forEach((asset) => URL.revokeObjectURL(asset.objectUrl));
    setAssets([]);
    setSelectedId(undefined);
    setAnnotations({});
    setDraft(undefined);
    setError(undefined);
  };

  const imagePoint = (
    event: ReactPointerEvent<SVGSVGElement>,
    asset: LocalAsset,
  ) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(asset.width, ((event.clientX - rect.left) / rect.width) * asset.width)),
      y: Math.max(0, Math.min(asset.height, ((event.clientY - rect.top) / rect.height) * asset.height)),
    };
  };

  const beginBox = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!activeAsset || event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = imagePoint(event, activeAsset);
    setDraft({ startX: point.x, startY: point.y, endX: point.x, endY: point.y });
  };

  const moveBox = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!activeAsset || !draft) return;
    const point = imagePoint(event, activeAsset);
    setDraft((current) => current ? { ...current, endX: point.x, endY: point.y } : current);
  };

  const finishBox = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!activeAsset || !draft) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    const point = imagePoint(event, activeAsset);
    const box = normalizedDraft({ ...draft, endX: point.x, endY: point.y });
    setDraft(undefined);
    if (box.width < 4 || box.height < 4) return;
    setAnnotations((current) => ({
      ...current,
      [activeAsset.id]: [
        ...(current[activeAsset.id] ?? []),
        { ...box, id: crypto.randomUUID(), label: "review-region" },
      ],
    }));
  };

  const exportReceipt = () => {
    if (!activeAsset) return;
    const payload = {
      schema_version: "visiondata-gate.browser-local-evidence.v1",
      source_mode: "BROWSER_LOCAL",
      evidence_status: "UNVERIFIED_LOCAL_INPUT",
      artifact_state: "UNSEALED_BROWSER_LOCAL",
      created_at: new Date().toISOString(),
      asset: {
        name: activeAsset.name,
        media_type: activeAsset.type,
        size_bytes: activeAsset.sizeBytes,
        width: activeAsset.width,
        height: activeAsset.height,
        sha256: activeAsset.sha256,
      },
      measurements: activeAsset.measurements,
      measurement_contract: {
        algorithm_version: "browser-screening.v1",
        sampling: `longest edge <= ${MEASUREMENT_EDGE}px`,
        luma_formula: "0.2126R + 0.7152G + 0.0722B",
        underexposed_threshold: "luma < 32; signal when ratio >= 0.35",
        overexposed_threshold: "luma > 235; signal when ratio >= 0.35",
        sharpness_operator: "variance of 4-neighbour Laplacian; signal when < 80",
        reproducibility: "BROWSER_ENGINE_DEPENDENT",
      },
      annotations: activeBoxes,
      boundary: {
        network_upload_performed: false,
        backend_connected: false,
        model_call_count: 0,
        persisted_by_site: false,
        server_sealed: false,
        production_release_allowed: false,
        production_decision: "NOT_EVALUATED",
      },
    };
    const url = URL.createObjectURL(
      new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${activeAsset.name.replace(/\.[^.]+$/, "")}.browser-local-evidence.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const draftBox = draft ? normalizedDraft(draft) : undefined;

  return (
    <section className="browser-local-lab" aria-label="浏览器本地图像取证台">
      <div className="browser-local-airgap">
        <div>
          <ShieldCheck size={17} />
          <span><strong>BROWSER-LOCAL AIR GAP</strong> 文件 → 当前标签页内存 → 本地证据</span>
        </div>
        <small>无网络上传 · 无后端 · 无模型调用 · 刷新即清空</small>
      </div>

      <Panel variant="raised">
        <PanelHeader
          eyebrow="REAL INPUT · EPHEMERAL SESSION"
          title="浏览器本地图像取证台"
          detail="选择你自己的图片，现场计算真实文件哈希和像素测量；结果不与冻结合成案件混算。"
          actions={<StatusBadge tone="success">BROWSER LOCAL</StatusBadge>}
        />

        <div className="browser-local-grid">
          <aside className="browser-local-assets">
            <button
              type="button"
              className={`browser-local-dropzone${dragActive ? " is-active" : ""}`}
              onClick={() => inputRef.current?.click()}
              onDragEnter={(event) => { event.preventDefault(); setDragActive(true); }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => { event.preventDefault(); setDragActive(false); }}
              onDrop={(event: DragEvent<HTMLButtonElement>) => {
                event.preventDefault();
                setDragActive(false);
                void addFiles(event.dataTransfer.files);
              }}
              disabled={busy || assets.length >= MAX_ASSETS}
            >
              <ImagePlus size={22} />
              <strong>{busy ? "正在本地测量…" : "选择或拖入图片"}</strong>
              <span>JPEG / PNG / WebP / BMP · ≤ 32 MiB</span>
            </button>
            <input
              ref={inputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/bmp"
              multiple
              hidden
              onChange={(event: ChangeEvent<HTMLInputElement>) => {
                if (event.target.files) void addFiles(event.target.files);
                event.target.value = "";
              }}
            />

            <div className="browser-local-asset-list" aria-label="当前标签页图片">
              {assets.map((asset, index) => (
                <button
                  type="button"
                  key={asset.id}
                  className={asset.id === activeAsset?.id ? "is-active" : ""}
                  onClick={() => { setSelectedId(asset.id); setDraft(undefined); }}
                >
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <div><strong>{asset.name}</strong><small>{asset.width}×{asset.height} · {formatBytes(asset.sizeBytes)}</small></div>
                  {asset.duplicateOf ? <em>DUP</em> : <FileImage size={14} />}
                </button>
              ))}
            </div>

            {assets.length ? (
              <button type="button" className="browser-local-clear" onClick={clearSession}>
                <Trash2 size={14} /> 清空当前标签页
              </button>
            ) : null}
          </aside>

          <div className="browser-local-canvas">
            {activeAsset ? (
              <>
                <header>
                  <div><MousePointer2 size={14} /><span>在图像上拖动以框选复核区域</span></div>
                  <strong>{activeBoxes.length} BOXES</strong>
                </header>
                <div className="browser-local-canvas__viewport">
                  <div className="browser-local-canvas__stage">
                    <img src={activeAsset.objectUrl} alt={`当前本地图片：${activeAsset.name}`} />
                    <svg
                      viewBox={`0 0 ${activeAsset.width} ${activeAsset.height}`}
                      preserveAspectRatio="none"
                      onPointerDown={beginBox}
                      onPointerMove={moveBox}
                      onPointerUp={finishBox}
                      onPointerCancel={() => setDraft(undefined)}
                      aria-label="浏览器本地框选画布"
                    >
                      {activeBoxes.map((box) => (
                        <g key={box.id}>
                          <rect x={box.x} y={box.y} width={box.width} height={box.height} />
                          <text x={box.x + 5} y={Math.max(14, box.y + 14)}>{box.label}</text>
                        </g>
                      ))}
                      {draftBox ? <rect className="is-draft" {...draftBox} /> : null}
                    </svg>
                  </div>
                </div>
              </>
            ) : (
              <div className="browser-local-empty">
                <ScanLine size={36} />
                <strong>等待真实图片输入</strong>
                <span>图片只在当前浏览器标签页解码，不会发送到 GitHub 或第三方服务。</span>
              </div>
            )}
          </div>

          <aside className="browser-local-inspector">
            {activeAsset ? (
              <>
                <div className="browser-local-signal">
                  <span>SCREENING SIGNAL</span>
                  <StatusBadge tone={signalTone}>{activeAsset.measurements.signal}</StatusBadge>
                </div>
                <div className="browser-local-metrics">
                  <article><Gauge size={15} /><span>平均亮度</span><strong>{activeAsset.measurements.meanLuma.toFixed(1)}</strong></article>
                  <article><Focus size={15} /><span>Laplacian 方差</span><strong>{activeAsset.measurements.laplacianVariance.toFixed(1)}</strong></article>
                  <article><ScanLine size={15} /><span>欠曝光像素</span><strong>{percentage(activeAsset.measurements.underexposedRatio)}</strong></article>
                  <article><ScanLine size={15} /><span>过曝光像素</span><strong>{percentage(activeAsset.measurements.overexposedRatio)}</strong></article>
                </div>
                <div className="browser-local-digest">
                  <small>FILE SHA-256</small>
                  <code title={activeAsset.sha256}>{activeAsset.sha256}</code>
                </div>
                <div className="browser-local-trace">
                  {trace.map(([kind, label, value]) => (
                    <article key={kind}><span>{kind}</span><div><strong>{label}</strong><small>{value}</small></div></article>
                  ))}
                </div>
                <button type="button" className="browser-local-export" onClick={exportReceipt}>
                  <Download size={15} /> 导出本地证据 JSON
                </button>
                {activeBoxes.length ? (
                  <button
                    type="button"
                    className="browser-local-undo"
                    onClick={() => setAnnotations((current) => ({ ...current, [activeAsset.id]: [] }))}
                  >
                    清除框选
                  </button>
                ) : null}
              </>
            ) : (
              <div className="browser-local-boundary">
                <LockKeyhole size={24} />
                <strong>本地会话尚未建立</strong>
                <span>不创建账户，不保存 Cookie 身份，不读取 API Key。</span>
              </div>
            )}
          </aside>
        </div>

        {error ? <div className="browser-local-error" role="alert"><AlertTriangle size={15} />{error}</div> : null}
        <footer className="browser-local-footnote">
          当前阈值仅用于浏览器端快速筛查，不是生产门禁策略；这里不生成 Agent 裁决、CAPA 批准或生产 PASS。
        </footer>
      </Panel>
    </section>
  );
}

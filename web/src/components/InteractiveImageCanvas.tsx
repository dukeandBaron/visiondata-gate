import {
  Activity,
  AlertTriangle,
  Blend,
  BoxSelect,
  Crosshair,
  Hand,
  LocateFixed,
  MousePointer2,
  RotateCcw,
  SplitSquareVertical,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import type {
  BoundingBoxAnnotation,
  CanvasTool,
  OperatorImageAsset,
  OpticalProbeProfile,
  TwinComparisonMode,
} from "../operatorDomain";

interface Point {
  x: number;
  y: number;
}

interface DraftLine {
  start: Point;
  end: Point;
}

interface CanvasGeometry {
  width: number;
  height: number;
  scale: number;
  fitScale: number;
  originX: number;
  originY: number;
}

interface ComparisonMetrics {
  meanAbsoluteDifference: number;
  maxChannelDifference: number;
  changedPixelRatio: number;
}

export type CanvasImageAsset = Pick<
  OperatorImageAsset,
  "asset_id" | "original_name" | "width" | "height" | "format" | "mode"
>;

interface InteractiveImageCanvasProps {
  asset: CanvasImageAsset;
  previewUrl: string;
  annotations: BoundingBoxAnnotation[];
  selectedAnnotationId?: string;
  highlightedAnnotationId?: string;
  twinAsset?: CanvasImageAsset;
  twinPreviewUrl?: string;
  readOnly?: boolean;
  comparisonMode?: TwinComparisonMode;
  onComparisonModeChange?: (mode: TwinComparisonMode) => void;
  onAnnotationsChange: (annotations: BoundingBoxAnnotation[]) => void;
  onSelectedAnnotationChange: (annotationId?: string) => void;
  onHighlightedAnnotationChange?: (annotationId?: string) => void;
  onProbeProfileChange?: (profile?: OpticalProbeProfile) => void;
  onAnnotationContextMenu?: (
    annotationId: string,
    position: { clientX: number; clientY: number },
  ) => void;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function normalizedBox(
  draft: DraftLine,
): Omit<BoundingBoxAnnotation, "annotation_id" | "label" | "source"> {
  return {
    x: Math.min(draft.start.x, draft.end.x),
    y: Math.min(draft.start.y, draft.end.y),
    width: Math.abs(draft.end.x - draft.start.x),
    height: Math.abs(draft.end.y - draft.start.y),
  };
}

function annotationAtPoint(
  annotations: BoundingBoxAnnotation[],
  point: Point,
): BoundingBoxAnnotation | undefined {
  return [...annotations].reverse().find(
    (annotation) =>
      point.x >= annotation.x &&
      point.x <= annotation.x + annotation.width &&
      point.y >= annotation.y &&
      point.y <= annotation.y + annotation.height,
  );
}

function comparisonMetrics(
  image: HTMLImageElement,
  twin: HTMLImageElement,
  asset: CanvasImageAsset,
): ComparisonMetrics | undefined {
  const longest = Math.max(asset.width, asset.height);
  const scale = Math.min(1, 256 / longest);
  const width = Math.max(1, Math.round(asset.width * scale));
  const height = Math.max(1, Math.round(asset.height * scale));
  const first = document.createElement("canvas");
  const second = document.createElement("canvas");
  first.width = second.width = width;
  first.height = second.height = height;
  const firstContext = first.getContext("2d", { willReadFrequently: true });
  const secondContext = second.getContext("2d", { willReadFrequently: true });
  if (!firstContext || !secondContext) return undefined;
  firstContext.drawImage(image, 0, 0, width, height);
  secondContext.drawImage(twin, 0, 0, width, height);
  const firstData = firstContext.getImageData(0, 0, width, height).data;
  const secondData = secondContext.getImageData(0, 0, width, height).data;
  let absoluteTotal = 0;
  let maxDifference = 0;
  let changedPixels = 0;
  for (let index = 0; index < firstData.length; index += 4) {
    let pixelDifference = 0;
    for (let channel = 0; channel < 3; channel += 1) {
      const difference = Math.abs(
        firstData[index + channel]! - secondData[index + channel]!,
      );
      absoluteTotal += difference;
      pixelDifference = Math.max(pixelDifference, difference);
      maxDifference = Math.max(maxDifference, difference);
    }
    if (pixelDifference > 0) changedPixels += 1;
  }
  return {
    meanAbsoluteDifference: absoluteTotal / (width * height * 3),
    maxChannelDifference: maxDifference,
    changedPixelRatio: changedPixels / (width * height),
  };
}

export function InteractiveImageCanvas({
  asset,
  previewUrl,
  annotations,
  selectedAnnotationId,
  highlightedAnnotationId,
  twinAsset,
  twinPreviewUrl,
  readOnly = false,
  comparisonMode = "OFF",
  onComparisonModeChange,
  onAnnotationsChange,
  onSelectedAnnotationChange,
  onHighlightedAnnotationChange,
  onProbeProfileChange,
  onAnnotationContextMenu,
}: InteractiveImageCanvasProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | undefined>(undefined);
  const twinImageRef = useRef<HTMLImageElement | undefined>(undefined);
  const [viewport, setViewport] = useState({ width: 800, height: 600 });
  const [tool, setTool] = useState<CanvasTool>("SELECT");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<Point>({ x: 0, y: 0 });
  const [draft, setDraft] = useState<DraftLine>();
  const [probeDraft, setProbeDraft] = useState<DraftLine>();
  const [probeLine, setProbeLine] = useState<DraftLine>();
  const [panDrag, setPanDrag] = useState<{ start: Point; origin: Point }>();
  const [cursor, setCursor] = useState<Point>();
  const [imageReady, setImageReady] = useState(false);
  const [twinImageReady, setTwinImageReady] = useState(false);
  const [imageLoadError, setImageLoadError] = useState<string>();
  const [twinImageLoadError, setTwinImageLoadError] = useState<string>();
  const [decodeAttempt, setDecodeAttempt] = useState(0);
  const [comparisonDivider, setComparisonDivider] = useState(0.5);
  const [comparisonDragging, setComparisonDragging] = useState(false);
  const [twinMetrics, setTwinMetrics] = useState<ComparisonMetrics>();

  const geometry = useMemo<CanvasGeometry>(() => {
    const availableWidth = Math.max(120, viewport.width - 48);
    const availableHeight = Math.max(120, viewport.height - 48);
    const fitScale = Math.min(availableWidth / asset.width, availableHeight / asset.height);
    const scale = fitScale * zoom;
    return {
      width: viewport.width,
      height: viewport.height,
      scale,
      fitScale,
      originX: (viewport.width - asset.width * scale) / 2 + pan.x,
      originY: (viewport.height - asset.height * scale) / 2 + pan.y,
    };
  }, [asset.height, asset.width, pan.x, pan.y, viewport.height, viewport.width, zoom]);

  const resetView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  useEffect(() => {
    resetView();
    setDraft(undefined);
    setProbeDraft(undefined);
    setProbeLine(undefined);
    setCursor(undefined);
    setComparisonDivider(0.5);
    onProbeProfileChange?.(undefined);
  }, [asset.asset_id, onProbeProfileChange, resetView]);

  useEffect(() => {
    if (readOnly && tool === "BOX") {
      setTool("SELECT");
      setDraft(undefined);
    }
  }, [readOnly, tool]);

  useEffect(() => {
    const viewportElement = viewportRef.current;
    if (!viewportElement) return undefined;
    const updateSize = () => {
      const bounds = viewportElement.getBoundingClientRect();
      setViewport({
        width: Math.max(1, Math.round(bounds.width)),
        height: Math.max(1, Math.round(bounds.height)),
      });
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(viewportElement);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setImageReady(false);
    setImageLoadError(undefined);
    imageRef.current = undefined;
    const image = new Image();
    let settled = false;
    const fail = (message: string) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      imageRef.current = undefined;
      setImageReady(false);
      setImageLoadError(message);
    };
    const timeout = window.setTimeout(
      () => fail("浏览器在 15 秒内未完成解码。请重试；若仍失败，请重新导入原始文件。"),
      15_000,
    );
    image.decoding = "async";
    image.onload = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      imageRef.current = image;
      setImageReady(true);
      setImageLoadError(undefined);
    };
    image.onerror = () => fail("文件已读取，但浏览器无法解码该图像格式或图像内容已损坏。");
    image.src = previewUrl;
    return () => {
      settled = true;
      window.clearTimeout(timeout);
      image.onload = null;
      image.onerror = null;
      if (imageRef.current === image) imageRef.current = undefined;
    };
  }, [decodeAttempt, previewUrl]);

  useEffect(() => {
    setTwinImageReady(false);
    setTwinImageLoadError(undefined);
    setTwinMetrics(undefined);
    if (!twinPreviewUrl) {
      twinImageRef.current = undefined;
      return undefined;
    }
    twinImageRef.current = undefined;
    const image = new Image();
    let settled = false;
    const fail = (message: string) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      twinImageRef.current = undefined;
      setTwinImageReady(false);
      setTwinImageLoadError(message);
    };
    const timeout = window.setTimeout(
      () => fail("孪生样本在 15 秒内未完成解码。可重试或先关闭比对继续审阅当前图像。"),
      15_000,
    );
    image.decoding = "async";
    image.onload = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      twinImageRef.current = image;
      setTwinImageReady(true);
      setTwinImageLoadError(undefined);
    };
    image.onerror = () => fail("孪生样本无法解码。当前图像仍可继续审阅。可重试或关闭比对。");
    image.src = twinPreviewUrl;
    return () => {
      settled = true;
      window.clearTimeout(timeout);
      image.onload = null;
      image.onerror = null;
      if (twinImageRef.current === image) twinImageRef.current = undefined;
    };
  }, [decodeAttempt, twinPreviewUrl]);

  useEffect(() => {
    const image = imageRef.current;
    const twin = twinImageRef.current;
    if (!image || !twin || !imageReady || !twinImageReady) return;
    try {
      setTwinMetrics(comparisonMetrics(image, twin, asset));
    } catch {
      setTwinMetrics(undefined);
    }
  }, [asset, imageReady, twinImageReady]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "v") setTool("SELECT");
      if (key === "b" && !readOnly) setTool("BOX");
      if (key === "h") setTool("PAN");
      if (key === "p") setTool("PROBE");
      if (key === "f") resetView();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [readOnly, resetView]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const image = imageRef.current;
    if (!canvas || !image || !imageReady) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(geometry.width * ratio));
    canvas.height = Math.max(1, Math.round(geometry.height * ratio));
    canvas.style.width = `${geometry.width}px`;
    canvas.style.height = `${geometry.height}px`;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, geometry.width, geometry.height);
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";

    const drawImage = (target: HTMLImageElement) => {
      context.drawImage(
        target,
        geometry.originX,
        geometry.originY,
        asset.width * geometry.scale,
        asset.height * geometry.scale,
      );
    };

    const twin = twinImageRef.current;
    const comparisonActive = comparisonMode !== "OFF" && twin && twinImageReady;
    drawImage(image);
    if (comparisonActive && comparisonMode === "CURTAIN") {
      const dividerX = geometry.originX + asset.width * geometry.scale * comparisonDivider;
      context.save();
      context.beginPath();
      context.rect(
        dividerX,
        geometry.originY,
        geometry.originX + asset.width * geometry.scale - dividerX,
        asset.height * geometry.scale,
      );
      context.clip();
      drawImage(twin);
      context.restore();
      context.save();
      context.strokeStyle = "#6ee7ff";
      context.lineWidth = 2;
      context.shadowColor = "rgba(110, 231, 255, 0.75)";
      context.shadowBlur = 8;
      context.beginPath();
      context.moveTo(dividerX, geometry.originY);
      context.lineTo(dividerX, geometry.originY + asset.height * geometry.scale);
      context.stroke();
      context.shadowBlur = 0;
      context.fillStyle = "#0c5c75";
      context.fillRect(dividerX - 18, geometry.originY + 8, 36, 18);
      context.fillStyle = "#e5fbff";
      context.font = "700 9px ui-monospace, SFMono-Regular, Consolas, monospace";
      context.fillText("DRAG", dividerX - 12, geometry.originY + 20);
      context.restore();
    }
    if (comparisonActive && comparisonMode === "DIFF") {
      context.save();
      context.globalCompositeOperation = "difference";
      drawImage(twin);
      context.restore();
    }

    if (comparisonActive) {
      context.save();
      context.font = "700 9px ui-monospace, SFMono-Regular, Consolas, monospace";
      context.fillStyle = "rgba(7, 17, 24, 0.82)";
      context.fillRect(geometry.originX + 8, geometry.originY + 8, 68, 19);
      context.fillStyle = "#6ee7ff";
      context.fillText(
        comparisonMode === "DIFF" ? "ABS DIFF" : "CURRENT",
        geometry.originX + 15,
        geometry.originY + 21,
      );
      if (comparisonMode === "CURTAIN") {
        const right = geometry.originX + asset.width * geometry.scale;
        context.fillStyle = "rgba(7, 17, 24, 0.82)";
        context.fillRect(right - 58, geometry.originY + 8, 50, 19);
        context.fillStyle = "#ffd166";
        context.fillText("TWIN", right - 46, geometry.originY + 21);
      }
      context.restore();
    }

    const drawBox = (
      box: Pick<BoundingBoxAnnotation, "x" | "y" | "width" | "height">,
      label: string,
      selected: boolean,
      dashed = false,
    ) => {
      const x = geometry.originX + box.x * asset.width * geometry.scale;
      const y = geometry.originY + box.y * asset.height * geometry.scale;
      const width = box.width * asset.width * geometry.scale;
      const height = box.height * asset.height * geometry.scale;
      context.save();
      context.lineWidth = selected ? 2.5 : 1.5;
      context.strokeStyle = selected ? "#ffd166" : "#ff5f6d";
      context.fillStyle = selected ? "rgba(255, 209, 102, 0.10)" : "rgba(255, 95, 109, 0.08)";
      if (dashed) context.setLineDash([6, 4]);
      context.fillRect(x, y, width, height);
      context.strokeRect(x, y, width, height);
      if (label) {
        context.font = "600 11px ui-monospace, SFMono-Regular, Consolas, monospace";
        const labelWidth = Math.min(
          Math.max(54, context.measureText(label).width + 14),
          width || 120,
        );
        context.fillStyle = selected ? "#d7a935" : "#d74857";
        context.fillRect(x, Math.max(0, y - 21), labelWidth, 20);
        context.fillStyle = "#fff";
        context.fillText(label, x + 6, Math.max(14, y - 7));
      }
      context.restore();
    };

    annotations.forEach((annotation) =>
      drawBox(
        annotation,
        annotation.label,
        annotation.annotation_id === selectedAnnotationId ||
          annotation.annotation_id === highlightedAnnotationId,
      ),
    );
    if (draft) drawBox(normalizedBox(draft), "new box", true, true);

    const activeProbe = probeDraft ?? probeLine;
    if (activeProbe) {
      const startX = geometry.originX + activeProbe.start.x * asset.width * geometry.scale;
      const startY = geometry.originY + activeProbe.start.y * asset.height * geometry.scale;
      const endX = geometry.originX + activeProbe.end.x * asset.width * geometry.scale;
      const endY = geometry.originY + activeProbe.end.y * asset.height * geometry.scale;
      context.save();
      context.strokeStyle = "#53e1ff";
      context.fillStyle = "#07151c";
      context.lineWidth = 2;
      context.setLineDash(probeDraft ? [5, 4] : []);
      context.beginPath();
      context.moveTo(startX, startY);
      context.lineTo(endX, endY);
      context.stroke();
      for (const point of [
        { x: startX, y: startY },
        { x: endX, y: endY },
      ]) {
        context.beginPath();
        context.arc(point.x, point.y, 4, 0, Math.PI * 2);
        context.fill();
        context.stroke();
      }
      context.restore();
    }
  }, [
    annotations,
    asset.height,
    asset.width,
    comparisonDivider,
    comparisonMode,
    draft,
    geometry,
    highlightedAnnotationId,
    imageReady,
    probeDraft,
    probeLine,
    selectedAnnotationId,
    twinImageReady,
  ]);

  const eventPoint = useCallback(
    (
      event: ReactPointerEvent<HTMLCanvasElement> | ReactMouseEvent<HTMLCanvasElement>,
    ): { screen: Point; normalized: Point; inside: boolean } => {
      const bounds = event.currentTarget.getBoundingClientRect();
      const screen = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
      const normalized = {
        x: (screen.x - geometry.originX) / (asset.width * geometry.scale),
        y: (screen.y - geometry.originY) / (asset.height * geometry.scale),
      };
      return {
        screen,
        normalized: { x: clamp(normalized.x, 0, 1), y: clamp(normalized.y, 0, 1) },
        inside:
          normalized.x >= 0 &&
          normalized.x <= 1 &&
          normalized.y >= 0 &&
          normalized.y <= 1,
      };
    },
    [asset.height, asset.width, geometry],
  );

  const buildProbeProfile = useCallback(
    (line: DraftLine): OpticalProbeProfile | undefined => {
      const image = imageRef.current;
      if (!image) return undefined;
      const diagnosticCanvas = document.createElement("canvas");
      diagnosticCanvas.width = image.naturalWidth;
      diagnosticCanvas.height = image.naturalHeight;
      const context = diagnosticCanvas.getContext("2d", { willReadFrequently: true });
      if (!context) return undefined;
      context.drawImage(image, 0, 0);
      const pixels = context.getImageData(0, 0, image.naturalWidth, image.naturalHeight).data;
      const lengthPixels = Math.hypot(
        (line.end.x - line.start.x) * asset.width,
        (line.end.y - line.start.y) * asset.height,
      );
      const sampleCount = Math.round(clamp(lengthPixels, 32, 256));
      const luminance: number[] = [];
      for (let index = 0; index < sampleCount; index += 1) {
        const ratio = sampleCount === 1 ? 0 : index / (sampleCount - 1);
        const normalizedX = line.start.x + (line.end.x - line.start.x) * ratio;
        const normalizedY = line.start.y + (line.end.y - line.start.y) * ratio;
        const x = clamp(Math.round(normalizedX * (image.naturalWidth - 1)), 0, image.naturalWidth - 1);
        const y = clamp(Math.round(normalizedY * (image.naturalHeight - 1)), 0, image.naturalHeight - 1);
        const offset = (y * image.naturalWidth + x) * 4;
        luminance.push(
          0.2126 * pixels[offset]! +
            0.7152 * pixels[offset + 1]! +
            0.0722 * pixels[offset + 2]!,
        );
      }
      const samples = luminance.map((value, index) => ({
        position: sampleCount === 1 ? 0 : index / (sampleCount - 1),
        luminance: value,
        gradient: index === 0 ? 0 : Math.abs(value - luminance[index - 1]!),
      }));
      return {
        start: line.start,
        end: line.end,
        length_pixels: lengthPixels,
        mean_luminance: luminance.reduce((total, value) => total + value, 0) / luminance.length,
        max_gradient: Math.max(...samples.map((sample) => sample.gradient)),
        samples,
        sampling_basis: "LOCAL_PREVIEW",
      };
    },
    [asset.height, asset.width],
  );

  const handlePointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (event.button === 2) return;
    const point = eventPoint(event);
    const dividerX = geometry.originX + asset.width * geometry.scale * comparisonDivider;
    if (
      comparisonMode === "CURTAIN" &&
      twinImageReady &&
      Math.abs(point.screen.x - dividerX) <= 14
    ) {
      event.currentTarget.setPointerCapture(event.pointerId);
      setComparisonDragging(true);
      return;
    }
    if (tool === "PAN" || event.button === 1 || event.altKey) {
      event.currentTarget.setPointerCapture(event.pointerId);
      setPanDrag({ start: point.screen, origin: pan });
      return;
    }
    if (!point.inside) {
      onSelectedAnnotationChange(undefined);
      return;
    }
    if (tool === "PROBE" || event.shiftKey) {
      event.currentTarget.setPointerCapture(event.pointerId);
      setProbeDraft({ start: point.normalized, end: point.normalized });
      return;
    }
    if (tool === "BOX" && !readOnly) {
      event.currentTarget.setPointerCapture(event.pointerId);
      setDraft({ start: point.normalized, end: point.normalized });
      return;
    }
    onSelectedAnnotationChange(annotationAtPoint(annotations, point.normalized)?.annotation_id);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const point = eventPoint(event);
    setCursor(point.inside ? point.normalized : undefined);
    if (comparisonDragging) {
      setComparisonDivider(point.normalized.x);
    } else if (panDrag) {
      setPan({
        x: panDrag.origin.x + point.screen.x - panDrag.start.x,
        y: panDrag.origin.y + point.screen.y - panDrag.start.y,
      });
    } else if (draft) {
      setDraft({ ...draft, end: point.normalized });
    } else if (probeDraft) {
      setProbeDraft({ ...probeDraft, end: point.normalized });
    } else if (tool === "SELECT" && point.inside) {
      onHighlightedAnnotationChange?.(
        annotationAtPoint(annotations, point.normalized)?.annotation_id,
      );
    } else {
      onHighlightedAnnotationChange?.(undefined);
    }
  };

  const handlePointerUp = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setComparisonDragging(false);
    setPanDrag(undefined);
    if (probeDraft) {
      const line = probeDraft;
      setProbeDraft(undefined);
      const length = Math.hypot(
        (line.end.x - line.start.x) * asset.width,
        (line.end.y - line.start.y) * asset.height,
      );
      if (length >= 2) {
        setProbeLine(line);
        onProbeProfileChange?.(buildProbeProfile(line));
      }
      return;
    }
    if (!draft || readOnly) {
      setDraft(undefined);
      return;
    }
    const box = normalizedBox(draft);
    setDraft(undefined);
    if (box.width < 0.004 || box.height < 0.004) return;
    const annotation: BoundingBoxAnnotation = {
      annotation_id: `box_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
      label: "defect",
      ...box,
      source: "MANUAL",
    };
    onAnnotationsChange([...annotations, annotation]);
    onSelectedAnnotationChange(annotation.annotation_id);
    setTool("SELECT");
  };

  const handleContextMenu = (event: ReactMouseEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    const point = eventPoint(event);
    if (!point.inside) return;
    const selected = annotationAtPoint(annotations, point.normalized);
    if (!selected) return;
    onSelectedAnnotationChange(selected.annotation_id);
    onAnnotationContextMenu?.(selected.annotation_id, {
      clientX: event.clientX,
      clientY: event.clientY,
    });
  };

  const handleWheel = (event: ReactWheelEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.12 : 0.89;
    setZoom((value) => clamp(value * factor, 0.25, 12));
  };

  const setActualPixels = () => {
    setZoom(clamp(1 / geometry.fitScale, 0.25, 12));
    setPan({ x: 0, y: 0 });
  };

  return (
    <section className="image-canvas-shell">
      <div className="image-toolbar" role="toolbar" aria-label="图片画布工具">
        <div className="image-toolbar__tools">
          <button
            type="button"
            className={tool === "SELECT" ? "is-active" : ""}
            onClick={() => setTool("SELECT")}
            title="选择标注 (V)"
          >
            <MousePointer2 size={16} />
            <span>选择</span>
          </button>
          <button
            type="button"
            className={tool === "BOX" ? "is-active" : ""}
            onClick={() => setTool("BOX")}
            disabled={readOnly}
            title={readOnly ? "冻结任务证据为只读，不能新增标注" : "绘制矩形框 (B)"}
          >
            <BoxSelect size={16} />
            <span>框选</span>
          </button>
          <button
            type="button"
            className={tool === "PROBE" ? "is-active" : ""}
            onClick={() => setTool("PROBE")}
            title="光度与梯度剖面探针 (P / Shift+拖动)"
          >
            <Activity size={16} />
            <span>剖面探针</span>
          </button>
          <button
            type="button"
            className={tool === "PAN" ? "is-active" : ""}
            onClick={() => setTool("PAN")}
            title="平移画布 (H)"
          >
            <Hand size={16} />
            <span>平移</span>
          </button>
        </div>
        {twinPreviewUrl ? (
          <div className="image-toolbar__analysis" aria-label="孪生样本比对工具">
            <button
              type="button"
              className={comparisonMode === "CURTAIN" ? "is-active is-analysis" : ""}
              onClick={() => onComparisonModeChange?.("CURTAIN")}
              title="双图卷帘比对"
            >
              <SplitSquareVertical size={16} />
              <span>卷帘</span>
            </button>
            <button
              type="button"
              className={comparisonMode === "DIFF" ? "is-active is-analysis" : ""}
              onClick={() => onComparisonModeChange?.("DIFF")}
              title="绝对像素差值"
            >
              <Blend size={16} />
              <span>差值</span>
            </button>
            <button
              type="button"
              onClick={() => onComparisonModeChange?.("OFF")}
              title="关闭孪生比对"
            >
              <X size={15} />
            </button>
          </div>
        ) : null}
        <div className="image-toolbar__view">
          <button
            type="button"
            onClick={() => setZoom((value) => clamp(value / 1.2, 0.25, 12))}
            title="缩小"
          >
            <ZoomOut size={16} />
          </button>
          <button
            type="button"
            className="zoom-readout"
            onClick={setActualPixels}
            title="按原始像素显示"
          >
            {Math.round(geometry.scale * 100)}%
          </button>
          <button
            type="button"
            onClick={() => setZoom((value) => clamp(value * 1.2, 0.25, 12))}
            title="放大"
          >
            <ZoomIn size={16} />
          </button>
          <button type="button" onClick={resetView} title="适应窗口 (F)">
            <LocateFixed size={16} />
          </button>
          <button type="button" onClick={resetView} title="重置视图">
            <RotateCcw size={15} />
          </button>
        </div>
      </div>
      <div className="image-viewport" ref={viewportRef}>
        {imageLoadError || (comparisonMode !== "OFF" && twinPreviewUrl && twinImageLoadError) ? (
          <div className="canvas-loading is-error" role="alert">
            <AlertTriangle size={22} />
            <strong>{imageLoadError ? "当前图像解码失败" : "孪生样本解码失败"}</strong>
            <span>{imageLoadError ?? twinImageLoadError}</span>
            <div className="canvas-loading__actions">
              <button type="button" onClick={() => setDecodeAttempt((value) => value + 1)}>
                <RotateCcw size={14} /> 重试解码
              </button>
              {!imageLoadError ? (
                <button type="button" onClick={() => onComparisonModeChange?.("OFF")}>
                  关闭比对
                </button>
              ) : null}
            </div>
          </div>
        ) : !imageReady || (comparisonMode !== "OFF" && twinPreviewUrl && !twinImageReady) ? (
          <div className="canvas-loading" role="status" aria-live="polite">
            <Crosshair size={21} />
            <span>正在解码本地取证图像…</span>
          </div>
        ) : null}
        <canvas
          ref={canvasRef}
          className={`inspection-canvas tool-${tool.toLowerCase()}${
            panDrag || comparisonDragging ? " is-dragging" : ""
          }`}
          aria-busy={!imageReady || Boolean(comparisonMode !== "OFF" && twinPreviewUrl && !twinImageReady)}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onPointerLeave={() => {
            setCursor(undefined);
            onHighlightedAnnotationChange?.(undefined);
          }}
          onContextMenu={handleContextMenu}
          onWheel={handleWheel}
          aria-label={`${asset.original_name} 交互式数据法医画布`}
        />
      </div>
      <footer className="canvas-status">
        <span>{asset.width} × {asset.height}px</span>
        <span>{asset.format} · {asset.mode}</span>
        <span>{annotations.length} boxes{readOnly ? " · read only" : ""}</span>
        {twinAsset && twinMetrics ? (
          <span className="canvas-status__comparison" title={twinAsset.asset_id}>
            Δmean {twinMetrics.meanAbsoluteDifference.toFixed(3)} · changed{" "}
            {(twinMetrics.changedPixelRatio * 100).toFixed(2)}% · max {twinMetrics.maxChannelDifference}
          </span>
        ) : null}
        <span className="canvas-status__spacer" />
        <span>
          {cursor
            ? `x ${Math.round(cursor.x * asset.width)} · y ${Math.round(cursor.y * asset.height)}`
            : "pointer outside image"}
        </span>
      </footer>
    </section>
  );
}

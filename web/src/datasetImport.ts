import type { BoundingBoxAnnotation, OperatorImageAsset } from "./operatorDomain";

const imageExtensions = new Set(["jpg", "jpeg", "png", "bmp", "tif", "tiff", "webp"]);

export interface DatasetSelection {
  rootName: string;
  images: File[];
  annotationFiles: File[];
  unsupportedFiles: File[];
  totalBytes: number;
  formatHints: string[];
}

export interface ImportedImageBinding {
  file: File;
  asset: OperatorImageAsset;
}

export interface AnnotationImportPlan {
  byAssetId: Map<string, BoundingBoxAnnotation[]>;
  parsedFiles: number;
  formatCounts: Record<string, number>;
  warnings: string[];
}

function relativePath(file: File): string {
  const candidate = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
  return (candidate || file.name).replaceAll("\\", "/");
}

function normalizedPath(value: string): string {
  return value.trim().replaceAll("\\", "/").replace(/^\.\//, "").toLowerCase();
}

function extension(value: string): string {
  const name = value.split("/").at(-1) ?? value;
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index + 1).toLowerCase() : "";
}

function withoutExtension(value: string): string {
  const index = value.lastIndexOf(".");
  return index >= 0 ? value.slice(0, index) : value;
}

function basename(value: string): string {
  return normalizedPath(value).split("/").at(-1) ?? normalizedPath(value);
}

function pathWithoutRoot(value: string): string {
  const parts = normalizedPath(value).split("/").filter(Boolean);
  return parts.length > 1 ? parts.slice(1).join("/") : parts.join("/");
}

export function inspectDatasetFiles(files: File[]): DatasetSelection {
  const images = files.filter((file) => imageExtensions.has(extension(relativePath(file))));
  const annotationFiles: File[] = [];
  const unsupportedFiles: File[] = [];
  const imageFiles = new Set(images);
  const formats = new Set<string>();
  const totalBytes = files.reduce((total, file) => total + file.size, 0);
  const imageStems = new Set<string>();
  images.forEach((file) => {
    const path = relativePath(file);
    imageStems.add(withoutExtension(normalizedPath(path)));
    imageStems.add(withoutExtension(pathWithoutRoot(path)));
    imageStems.add(withoutExtension(basename(path)));
  });
  files.forEach((file) => {
    if (imageFiles.has(file)) return;
    const path = relativePath(file);
    const ext = extension(relativePath(file));
    const name = basename(path);
    const sidecarStem = withoutExtension(normalizedPath(path));
    const sidecarWithoutRoot = withoutExtension(pathWithoutRoot(path));
    const imageDirectoryStem = sidecarWithoutRoot.replace(/(^|\/)labels\//, "$1images/");
    const likelyYoloSidecar = ext === "txt" && (
      /^(classes|obj)\.txt$/i.test(name)
      || imageStems.has(sidecarStem)
      || imageStems.has(sidecarWithoutRoot)
      || imageStems.has(imageDirectoryStem)
      || imageStems.has(withoutExtension(name))
    );
    const likelyYoloMetadata = ["yaml", "yml"].includes(ext)
      || (ext === "names" && /^(classes|obj)\.names$/i.test(name));
    if (["json", "xml"].includes(ext) || likelyYoloSidecar || likelyYoloMetadata) {
      annotationFiles.push(file);
      if (ext === "xml") formats.add("VOC");
      else if (ext === "txt" || ext === "yaml" || ext === "yml" || ext === "names") formats.add("YOLO");
      else if (ext === "json") formats.add("COCO / LabelMe");
      return;
    }
    unsupportedFiles.push(file);
  });
  images.sort((a, b) => relativePath(a).localeCompare(relativePath(b)));
  annotationFiles.sort((a, b) => relativePath(a).localeCompare(relativePath(b)));
  const firstPath = files[0] ? relativePath(files[0]) : "dataset";
  const rootName = firstPath.split("/").filter(Boolean)[0] ?? "dataset";
  return {
    rootName,
    images,
    annotationFiles,
    unsupportedFiles,
    totalBytes,
    formatHints: [...formats],
  };
}

interface BindingIndex {
  exact: Map<string, ImportedImageBinding>;
  withoutRoot: Map<string, ImportedImageBinding>;
  uniqueBasename: Map<string, ImportedImageBinding>;
  uniqueStem: Map<string, ImportedImageBinding>;
  stems: Map<string, ImportedImageBinding>;
}

function uniqueMap(
  entries: ReadonlyArray<readonly [string, ImportedImageBinding]>,
): Map<string, ImportedImageBinding> {
  const counts = new Map<string, number>();
  entries.forEach(([key]) => counts.set(key, (counts.get(key) ?? 0) + 1));
  return new Map(entries.filter(([key]) => counts.get(key) === 1));
}

function buildBindingIndex(bindings: ImportedImageBinding[]): BindingIndex {
  const exactEntries = bindings.map((binding) => [normalizedPath(relativePath(binding.file)), binding] as const);
  const noRootEntries = bindings.map((binding) => [pathWithoutRoot(relativePath(binding.file)), binding] as const);
  const basenameEntries = bindings.map((binding) => [basename(relativePath(binding.file)), binding] as const);
  const stemEntries = bindings.map((binding) => [withoutExtension(basename(relativePath(binding.file))), binding] as const);
  const stems = new Map<string, ImportedImageBinding>();
  bindings.forEach((binding) => {
    const rel = normalizedPath(relativePath(binding.file));
    stems.set(withoutExtension(rel), binding);
    stems.set(withoutExtension(pathWithoutRoot(rel)), binding);
    const imagesSwapped = withoutExtension(pathWithoutRoot(rel)).replace(/(^|\/)images\//, "$1labels/");
    stems.set(imagesSwapped, binding);
  });
  return {
    exact: new Map(exactEntries),
    withoutRoot: new Map(noRootEntries),
    uniqueBasename: uniqueMap(basenameEntries),
    uniqueStem: uniqueMap(stemEntries),
    stems,
  };
}

function findBinding(index: BindingIndex, path: string): ImportedImageBinding | undefined {
  const normalized = normalizedPath(path);
  return index.exact.get(normalized)
    ?? index.withoutRoot.get(normalized)
    ?? index.exact.get(pathWithoutRoot(normalized))
    ?? index.withoutRoot.get(pathWithoutRoot(normalized))
    ?? index.uniqueBasename.get(basename(normalized))
    ?? index.uniqueStem.get(withoutExtension(basename(normalized)));
}

function findSidecarBinding(index: BindingIndex, path: string): ImportedImageBinding | undefined {
  const stem = withoutExtension(normalizedPath(path));
  const noRootStem = withoutExtension(pathWithoutRoot(path));
  const imageStem = noRootStem.replace(/(^|\/)labels\//, "$1images/");
  return index.stems.get(stem)
    ?? index.stems.get(noRootStem)
    ?? index.stems.get(imageStem)
    ?? index.uniqueStem.get(withoutExtension(basename(path)));
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function makeBox(
  format: string,
  sequence: number,
  label: string,
  x: number,
  y: number,
  width: number,
  height: number,
): BoundingBoxAnnotation | undefined {
  if (![x, y, width, height].every(Number.isFinite)) return undefined;
  const left = clamp01(x);
  const top = clamp01(y);
  const right = clamp01(x + width);
  const bottom = clamp01(y + height);
  if (!label.trim() || right - left <= 0 || bottom - top <= 0) return undefined;
  return {
    annotation_id: `import-${format.toLowerCase()}-${sequence}-${crypto.randomUUID().slice(0, 8)}`,
    label: label.trim().slice(0, 120),
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
    source: "IMPORTED",
  };
}

type AddBoxResult = "ADDED" | "UNMATCHED" | "INVALID" | "TRUNCATED";

function addBox(
  target: Map<string, BoundingBoxAnnotation[]>,
  binding: ImportedImageBinding | undefined,
  box: BoundingBoxAnnotation | undefined,
): AddBoxResult {
  if (!binding) return "UNMATCHED";
  if (!box) return "INVALID";
  const current = target.get(binding.asset.asset_id) ?? [];
  if (current.length >= 500) return "TRUNCATED";
  current.push(box);
  target.set(binding.asset.asset_id, current);
  return "ADDED";
}

async function parseClassNames(files: File[]): Promise<string[]> {
  const namesFile = files.find((file) => ["names", "txt"].includes(extension(file.name)) && /(^|\/)(classes|obj)\.(txt|names)$/i.test(relativePath(file)));
  if (namesFile) return (await namesFile.text()).split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  const yaml = files.find((file) => ["yaml", "yml"].includes(extension(file.name)));
  if (!yaml) return [];
  const text = await yaml.text();
  const inline = text.match(/names\s*:\s*\[([^\]]+)\]/i)?.[1];
  if (inline) return inline.split(",").map((item) => item.trim().replace(/^['"]|['"]$/g, "")).filter(Boolean);
  const block = text.match(/names\s*:\s*\r?\n((?:\s+\d+\s*:\s*[^\r\n]+\r?\n?)+)/i)?.[1] ?? "";
  return block.split(/\r?\n/).map((line) => line.replace(/^\s*\d+\s*:\s*/, "").trim().replace(/^['"]|['"]$/g, "")).filter(Boolean);
}

export async function buildAnnotationImportPlan(
  files: File[],
  bindings: ImportedImageBinding[],
): Promise<AnnotationImportPlan> {
  const maxAnnotationFileBytes = 64 * 1024 * 1024;
  const maxAnnotationTotalBytes = 256 * 1024 * 1024;
  const maxAnnotationFiles = 20_000;
  const index = buildBindingIndex(bindings);
  const byAssetId = new Map<string, BoundingBoxAnnotation[]>();
  const warnings: string[] = [];
  const formatCounts: Record<string, number> = { COCO: 0, YOLO: 0, VOC: 0, LabelMe: 0 };
  const boundedFiles: File[] = [];
  let boundedBytes = 0;
  let rejectedForSafety = 0;
  files.forEach((file) => {
    if (
      boundedFiles.length >= maxAnnotationFiles
      || file.size > maxAnnotationFileBytes
      || boundedBytes + file.size > maxAnnotationTotalBytes
    ) {
      rejectedForSafety += 1;
      return;
    }
    boundedFiles.push(file);
    boundedBytes += file.size;
  });
  if (rejectedForSafety > 0) {
    warnings.push(
      `${rejectedForSafety} 个标注文件因安全预算未解析（单文件 64 MiB、总计 256 MiB、最多 20,000 个文件）。图片导入不受影响。`,
    );
  }
  const classNames = await parseClassNames(boundedFiles);
  let sequence = 0;
  let parsedFiles = 0;
  let unmatchedBoxes = 0;
  let invalidBoxes = 0;
  let truncatedBoxes = 0;
  const unmatchedSamples = new Set<string>();
  const invalidSamples = new Set<string>();
  const truncatedSamples = new Set<string>();

  const recordBox = (
    file: File,
    binding: ImportedImageBinding | undefined,
    box: BoundingBoxAnnotation | undefined,
  ) => {
    const result = addBox(byAssetId, binding, box);
    const sample = relativePath(file);
    if (result === "UNMATCHED") {
      unmatchedBoxes += 1;
      if (unmatchedSamples.size < 4) unmatchedSamples.add(sample);
    } else if (result === "INVALID") {
      invalidBoxes += 1;
      if (invalidSamples.size < 4) invalidSamples.add(sample);
    } else if (result === "TRUNCATED") {
      truncatedBoxes += 1;
      if (truncatedSamples.size < 4) truncatedSamples.add(sample);
    }
  };

  for (const file of boundedFiles) {
    const ext = extension(relativePath(file));
    try {
      const text = await file.text();
      if (ext === "json") {
        const payload = JSON.parse(text) as Record<string, unknown>;
        if (Array.isArray(payload.images) && Array.isArray(payload.annotations)) {
          const categories = new Map<number, string>();
          (Array.isArray(payload.categories) ? payload.categories : []).forEach((raw) => {
            const item = raw as { id?: unknown; name?: unknown };
            if (typeof item.id === "number" && typeof item.name === "string") categories.set(item.id, item.name);
          });
          const imageById = new Map<number, ImportedImageBinding>();
          payload.images.forEach((raw) => {
            const item = raw as { id?: unknown; file_name?: unknown };
            if (typeof item.id === "number" && typeof item.file_name === "string") {
              const binding = findBinding(index, item.file_name);
              if (binding) imageById.set(item.id, binding);
            }
          });
          payload.annotations.forEach((raw) => {
            const item = raw as { image_id?: unknown; category_id?: unknown; bbox?: unknown };
            if (typeof item.image_id !== "number" || !Array.isArray(item.bbox) || item.bbox.length < 4) return;
            const binding = imageById.get(item.image_id);
            if (!binding) {
              recordBox(file, undefined, undefined);
              return;
            }
            const [x = Number.NaN, y = Number.NaN, width = Number.NaN, height = Number.NaN] = item.bbox.map(Number);
            const label = typeof item.category_id === "number" ? categories.get(item.category_id) ?? `class-${item.category_id}` : "object";
            recordBox(file, binding, makeBox("coco", sequence++, label, x / binding.asset.width, y / binding.asset.height, width / binding.asset.width, height / binding.asset.height));
            formatCounts.COCO = (formatCounts.COCO ?? 0) + 1;
          });
          parsedFiles += 1;
          continue;
        }
        if (Array.isArray(payload.shapes)) {
          const imagePath = typeof payload.imagePath === "string" ? payload.imagePath : withoutExtension(relativePath(file));
          const binding = findBinding(index, imagePath) ?? findSidecarBinding(index, relativePath(file));
          payload.shapes.forEach((raw) => {
            const shape = raw as { label?: unknown; points?: unknown };
            if (typeof shape.label !== "string" || !Array.isArray(shape.points)) {
              recordBox(file, binding, undefined);
              return;
            }
            if (!binding) {
              recordBox(file, undefined, undefined);
              return;
            }
            const points = shape.points
              .filter((point): point is unknown[] => Array.isArray(point) && point.length >= 2)
              .map((point) => ({ x: Number(point[0]), y: Number(point[1]) }))
              .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
            if (points.length < 2) {
              recordBox(file, binding, undefined);
              return;
            }
            const xs = points.map((point) => point.x);
            const ys = points.map((point) => point.y);
            const left = Math.min(...xs); const top = Math.min(...ys); const right = Math.max(...xs); const bottom = Math.max(...ys);
            recordBox(file, binding, makeBox("labelme", sequence++, shape.label, left / binding.asset.width, top / binding.asset.height, (right - left) / binding.asset.width, (bottom - top) / binding.asset.height));
            formatCounts.LabelMe = (formatCounts.LabelMe ?? 0) + 1;
          });
          parsedFiles += 1;
        }
        continue;
      }

      if (ext === "xml") {
        const documentNode = new DOMParser().parseFromString(text, "application/xml");
        if (documentNode.querySelector("parsererror")) throw new Error("invalid XML");
        const fileName = documentNode.querySelector("filename")?.textContent?.trim() || relativePath(file);
        const binding = findBinding(index, fileName) ?? findSidecarBinding(index, relativePath(file));
        documentNode.querySelectorAll("object").forEach((objectNode) => {
          if (!binding) {
            recordBox(file, undefined, undefined);
            return;
          }
          const label = objectNode.querySelector("name")?.textContent?.trim() || "object";
          const xmin = Number(objectNode.querySelector("xmin")?.textContent); const ymin = Number(objectNode.querySelector("ymin")?.textContent);
          const xmax = Number(objectNode.querySelector("xmax")?.textContent); const ymax = Number(objectNode.querySelector("ymax")?.textContent);
          recordBox(file, binding, makeBox("voc", sequence++, label, xmin / binding.asset.width, ymin / binding.asset.height, (xmax - xmin) / binding.asset.width, (ymax - ymin) / binding.asset.height));
          formatCounts.VOC = (formatCounts.VOC ?? 0) + 1;
        });
        parsedFiles += 1;
        continue;
      }

      if (ext === "txt" && !/(^|\/)(classes|obj)\.txt$/i.test(relativePath(file))) {
        const binding = findSidecarBinding(index, relativePath(file));
        let recognized = false;
        text.split(/\r?\n/).forEach((line) => {
          const tokens = line.trim().split(/\s+/);
          if (tokens.length < 5) return;
          const [classId = Number.NaN, centerX = Number.NaN, centerY = Number.NaN, width = Number.NaN, height = Number.NaN] = tokens.slice(0, 5).map(Number);
          if (![classId, centerX, centerY, width, height].every(Number.isFinite)) return;
          recognized = true;
          recordBox(
            file,
            binding,
            binding
              ? makeBox("yolo", sequence++, classNames[classId] ?? `class-${classId}`, centerX - width / 2, centerY - height / 2, width, height)
              : undefined,
          );
          formatCounts.YOLO = (formatCounts.YOLO ?? 0) + 1;
        });
        if (recognized) parsedFiles += 1;
      }
    } catch (error) {
      warnings.push(`${relativePath(file)}: ${error instanceof Error ? error.message : "解析失败"}`);
    }
  }

  const matchedBoxes = [...byAssetId.values()].reduce((total, boxes) => total + boxes.length, 0);
  if (unmatchedBoxes > 0) {
    warnings.push(`${unmatchedBoxes} 个标注未找到可靠的图片绑定；样例：${[...unmatchedSamples].join("、")}`);
  }
  if (invalidBoxes > 0) {
    warnings.push(`${invalidBoxes} 个标注坐标或类别无效，未写入；样例：${[...invalidSamples].join("、")}`);
  }
  if (truncatedBoxes > 0) {
    warnings.push(`${truncatedBoxes} 个标注超过单图 500 框账本上限，未写入；样例：${[...truncatedSamples].join("、")}`);
  }
  if (files.length > 0 && matchedBoxes === 0) warnings.push("检测到标注文件，但没有标注能与已上传图片可靠匹配。图片仍已导入。");
  return { byAssetId, parsedFiles, formatCounts, warnings };
}

export function datasetRelativePath(file: File): string {
  return relativePath(file);
}

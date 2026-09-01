import {
  AlertTriangle,
  CheckCircle2,
  FileArchive,
  FileImage,
  FolderOpen,
  LoaderCircle,
  ShieldCheck,
  UploadCloud,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import {
  buildAnnotationImportPlan,
  datasetRelativePath,
  inspectDatasetFiles,
  type DatasetSelection,
  type ImportedImageBinding,
} from "../datasetImport";
import { saveOperatorAnnotations, uploadOperatorImages } from "../data/api";
import type { OperatorImageAsset } from "../operatorDomain";
import { Modal } from "./ui";

const maxFileBytes = 32 * 1024 * 1024;
const maxBatchBytes = 128 * 1024 * 1024;
const maxBatchFiles = 64;

type ImportPhase = "IDLE" | "READY" | "UPLOADING" | "ANNOTATING" | "DONE" | "ERROR";

export interface DatasetImportResult {
  workspaceId: string;
  projectId: string;
  datasetName: string;
  assets: OperatorImageAsset[];
  selectedImageCount: number;
  rejectedImageCount: number;
  annotationFileCount: number;
  annotatedAssetCount: number;
  importedBoxCount: number;
  warnings: string[];
}

function formatBytes(value: number): string {
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GiB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MiB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${value} B`;
}

function createUploadBatches(files: File[]): File[][] {
  const batches: File[][] = [];
  let current: File[] = [];
  let currentBytes = 0;
  files.forEach((file) => {
    if (current.length >= maxBatchFiles || currentBytes + file.size > maxBatchBytes) {
      if (current.length) batches.push(current);
      current = [];
      currentBytes = 0;
    }
    current.push(file);
    currentBytes += file.size;
  });
  if (current.length) batches.push(current);
  return batches;
}

function expectedStoredName(file: File): string {
  const normalized = file.name.replaceAll("\\", "/");
  return (normalized.split("/").at(-1) ?? "uploaded-image").trim().replace(/^\.+|\.+$/g, "").slice(0, 180)
    || "uploaded-image";
}

export function DatasetImportDialog({
  workspaceId,
  projectId,
  onClose,
  onImported,
}: {
  workspaceId: string;
  projectId: string;
  onClose: () => void;
  onImported: (result: DatasetImportResult) => void;
}) {
  const directoryInputRef = useRef<HTMLInputElement>(null);
  const [selection, setSelection] = useState<DatasetSelection>();
  const [phase, setPhase] = useState<ImportPhase>("IDLE");
  const [uploadedCount, setUploadedCount] = useState(0);
  const [annotatedAssetCount, setAnnotatedAssetCount] = useState(0);
  const [error, setError] = useState<string>();
  const [result, setResult] = useState<DatasetImportResult>();

  useEffect(() => {
    directoryInputRef.current?.setAttribute("webkitdirectory", "");
    directoryInputRef.current?.setAttribute("directory", "");
  }, []);

  const validImages = useMemo(
    () => selection?.images.filter((file) => file.size > 0 && file.size <= maxFileBytes) ?? [],
    [selection],
  );
  const oversizedImages = (selection?.images.length ?? 0) - validImages.length;
  const busy = phase === "UPLOADING" || phase === "ANNOTATING";

  const openDirectoryPicker = () => {
    const input = directoryInputRef.current;
    if (!input || busy) return;
    input.value = "";
    input.click();
  };

  const chooseDirectory = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    setError(undefined);
    setResult(undefined);
    setUploadedCount(0);
    setAnnotatedAssetCount(0);
    if (!files.length) {
      setSelection(undefined);
      setPhase("IDLE");
      return;
    }
    const inspected = inspectDatasetFiles(files);
    setSelection(inspected);
    setPhase(inspected.images.length > 0 ? "READY" : "ERROR");
    if (!inspected.images.length) setError("所选目录中没有可解码的 JPG、PNG、BMP、TIFF 或 WebP 图片。");
  };

  const importDataset = async () => {
    if (!selection || !validImages.length || busy) return;
    const importWorkspaceId = workspaceId;
    const importProjectId = projectId;
    setPhase("UPLOADING");
    setError(undefined);
    setResult(undefined);
    setUploadedCount(0);
    setAnnotatedAssetCount(0);
    const warnings: string[] = [];
    const bindings: ImportedImageBinding[] = [];
    const batches = createUploadBatches(validImages);
    const annotationStateByAssetId = new Map<string, { count: number; revision: number }>();
    let successfulAnnotatedAssets = 0;
    try {
      for (let batchIndex = 0; batchIndex < batches.length; batchIndex += 1) {
        const batch = batches[batchIndex];
        if (!batch) continue;
        try {
          const uploaded = await uploadOperatorImages(importWorkspaceId, importProjectId, batch);
          if (uploaded.uploaded_count !== batch.length || uploaded.assets.length !== batch.length) {
            throw new Error("服务端没有完整回显本批图片，已停止标注绑定");
          }
          const batchBindings = uploaded.assets.map((asset, index) => {
            const file = batch[index];
            if (!file || asset.byte_size !== file.size || asset.original_name !== expectedStoredName(file)) {
              throw new Error(`第 ${index + 1} 张图片的上传回执与本地文件不一致`);
            }
            return { file, asset };
          });
          bindings.push(...batchBindings);
          setUploadedCount(bindings.length);
        } catch (caught) {
          warnings.push(`批次 ${batchIndex + 1}/${batches.length} 上传失败：${caught instanceof Error ? caught.message : "未知错误"}`);
        }
      }
      if (!bindings.length) throw new Error(warnings[0] ?? "数据集图片上传失败");
      if (oversizedImages > 0) warnings.push(`${oversizedImages} 张图片为空或超过单文件 32 MiB，已拒绝。`);

      let annotationFileCount = 0;
      let importedBoxCount = 0;
      if (selection.annotationFiles.length > 0) {
        setPhase("ANNOTATING");
        const plan = await buildAnnotationImportPlan(selection.annotationFiles, bindings);
        annotationFileCount = plan.parsedFiles;
        warnings.push(...plan.warnings.slice(0, 20));
        const entries = [...plan.byAssetId.entries()].filter(([, boxes]) => boxes.length > 0);
        for (let offset = 0; offset < entries.length; offset += 6) {
          const chunk = entries.slice(offset, offset + 6);
          const settled = await Promise.allSettled(
            chunk.map(([assetId, boxes]) => {
              const binding = bindings.find((candidate) => candidate.asset.asset_id === assetId);
              return saveOperatorAnnotations(
                importWorkspaceId,
                assetId,
                binding?.asset.annotation_revision ?? 0,
                boxes,
              );
            }),
          );
          settled.forEach((item, index) => {
            const boxes = chunk[index]?.[1] ?? [];
            if (item.status === "fulfilled") {
              successfulAnnotatedAssets += 1;
              importedBoxCount += boxes.length;
              annotationStateByAssetId.set(item.value.asset_id, {
                count: item.value.annotations.length,
                revision: item.value.revision,
              });
              setAnnotatedAssetCount((count) => count + 1);
            } else {
              warnings.push(`资产 ${chunk[index]?.[0] ?? "unknown"} 标注写入失败：${item.reason instanceof Error ? item.reason.message : "未知错误"}`);
            }
          });
        }
      }

      const completed: DatasetImportResult = {
        workspaceId: importWorkspaceId,
        projectId: importProjectId,
        datasetName: selection.rootName,
        assets: bindings.map((binding) => {
          const annotationMeta = annotationStateByAssetId.get(binding.asset.asset_id);
          return annotationMeta
            ? {
                ...binding.asset,
                annotation_count: annotationMeta.count,
                annotation_revision: annotationMeta.revision,
              }
            : binding.asset;
        }),
        selectedImageCount: selection.images.length,
        rejectedImageCount: selection.images.length - bindings.length,
        annotationFileCount,
        annotatedAssetCount: successfulAnnotatedAssets,
        importedBoxCount,
        warnings,
      };
      setAnnotatedAssetCount(completed.annotatedAssetCount);
      setResult(completed);
      setPhase("DONE");
      onImported(completed);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "数据集导入失败");
      setPhase("ERROR");
    }
  };

  return (
    <Modal title="导入工业视觉数据集" onClose={busy ? () => undefined : onClose}>
      <div className="dataset-import-dialog">
        <input
          ref={directoryInputRef}
          className="sr-only"
          type="file"
          multiple
          onChange={chooseDirectory}
        />

        <section className="dataset-import-boundary">
          <ShieldCheck size={18} />
          <div>
            <strong>本地目录导入 · 原始图片不外发</strong>
            <p>支持递归读取图片，并自动识别 COCO JSON、YOLO TXT、Pascal VOC XML 与 LabelMe JSON 的 BBox。</p>
            <p>图片复制到当前 Operator Workspace；标注以 IMPORTED 写入 append-only revision。不会自动创建 Goal 2/Goal 3 Product Task、Incident 或 CAPA。</p>
          </div>
        </section>

        <button className="dataset-import-picker" type="button" onClick={openDirectoryPicker} disabled={busy}>
          <FolderOpen size={25} />
          <span><strong>{selection ? "重新选择数据集目录" : "选择数据集目录"}</strong><small>选择根目录；系统会递归扫描，不要求把图片一张张加入。</small></span>
        </button>

        {selection ? (
          <>
            <header className="dataset-import-selection">
              <div><span>DATASET</span><strong>{selection.rootName}</strong><small>{formatBytes(selection.totalBytes)} · {selection.formatHints.join(" / ") || "images only"}</small></div>
              <code>{validImages.length} ready</code>
            </header>
            <div className="dataset-import-metrics">
              <article><FileImage size={15} /><span>图片</span><strong>{selection.images.length}</strong></article>
              <article><FileArchive size={15} /><span>标注文件</span><strong>{selection.annotationFiles.length}</strong></article>
              <article><AlertTriangle size={15} /><span>忽略文件</span><strong>{selection.unsupportedFiles.length}</strong></article>
              <article><AlertTriangle size={15} /><span>超限图片</span><strong>{oversizedImages}</strong></article>
            </div>
            <details className="dataset-import-file-sample">
              <summary>查看扫描样例与导入边界</summary>
              {selection.images.slice(0, 5).map((file) => <code key={datasetRelativePath(file)}>{datasetRelativePath(file)}</code>)}
              <p>图片单文件上限 32 MiB；前端自动拆分为每批最多 64 张、128 MiB。标注解析预算为单文件 64 MiB、总计 256 MiB、20,000 个文件，超限会明确警告但保留图片。ZIP 暂不解包，请选择解压后的目录。</p>
            </details>
          </>
        ) : null}

        {busy ? (
          <section className="dataset-import-progress" role="status">
            <LoaderCircle className="is-spinning" size={18} />
            <div><strong>{phase === "UPLOADING" ? "正在分批上传图片" : "正在写入导入标注"}</strong><span>{uploadedCount}/{validImages.length} images · {annotatedAssetCount} annotated assets</span><progress max={Math.max(validImages.length, 1)} value={phase === "UPLOADING" ? uploadedCount : validImages.length} /></div>
          </section>
        ) : null}

        {error ? <div className="dataset-import-error" role="alert"><AlertTriangle size={15} />{error}</div> : null}
        {result ? (
          <section className="dataset-import-result">
            <CheckCircle2 size={19} />
            <div>
              <strong>数据集已导入工作簿</strong>
              <p>{result.assets.length} 张图片 · {result.annotatedAssetCount} 张带导入标注 · {result.importedBoxCount} 个 BBox</p>
              {result.warnings.length ? (
                <details>
                  <summary>{result.warnings.length} 项警告；图片导入结果已保留</summary>
                  {result.warnings.slice(0, 8).map((warning) => <code key={warning}>{warning}</code>)}
                </details>
              ) : null}
            </div>
          </section>
        ) : null}

        <footer>
          <button type="button" onClick={onClose} disabled={busy}>{phase === "DONE" ? "完成" : "取消"}</button>
          <button className="is-primary" type="button" onClick={() => void importDataset()} disabled={!selection || !validImages.length || busy || phase === "DONE"}>
            {busy ? <LoaderCircle className="is-spinning" size={14} /> : <UploadCloud size={14} />}
            {busy ? "正在导入…" : `导入 ${validImages.length} 张图片`}
          </button>
        </footer>
      </div>
    </Modal>
  );
}

import { ImageOff, LoaderCircle, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { loadOperatorPreview } from "../data/api";
import type { OperatorImageAsset } from "../operatorDomain";
import { Panel, PanelHeader, StatusBadge } from "./ui";

interface ReviewSyntheticAssetProofProps {
  assets: OperatorImageAsset[];
}

interface PreviewRecord {
  asset: OperatorImageAsset;
  url: string;
  role: "BEFORE" | "RECHECK";
}

type LoadState = "LOADING" | "READY" | "FAIL_CLOSED";

function compactSha(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-7)}`;
}

export function ReviewSyntheticAssetProof({ assets }: ReviewSyntheticAssetProofProps) {
  const selected = useMemo(() => {
    const before = assets.find(
      (asset) => asset.original_name === "synthetic-fixture-before.png",
    );
    const recheck = assets.find(
      (asset) => asset.original_name === "synthetic-fixture-recheck.png",
    );
    return before && recheck
      ? [
          { asset: before, role: "BEFORE" as const },
          { asset: recheck, role: "RECHECK" as const },
        ]
      : [];
  }, [assets]);
  const [state, setState] = useState<LoadState>("LOADING");
  const [previews, setPreviews] = useState<PreviewRecord[]>([]);
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;
    const allocatedUrls = new Set<string>();
    setPreviews([]);
    setError(undefined);

    if (selected.length !== 2) {
      setState("FAIL_CLOSED");
      setError("冻结合成视觉资产不完整，页面不会用其他图片补位。");
      return () => {
        active = false;
      };
    }

    setState("LOADING");
    void Promise.all(
      selected.map(async ({ asset, role }) => {
        const url = await loadOperatorPreview(asset);
        if (!active) {
          URL.revokeObjectURL(url);
          return { asset, role, url: "" };
        }
        allocatedUrls.add(url);
        return { asset, role, url };
      }),
    )
      .then((records) => {
        if (!active) return;
        setPreviews(records);
        setState("READY");
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setState("FAIL_CLOSED");
        setError(caught instanceof Error ? caught.message : "冻结合成视觉资产不可用");
      });

    return () => {
      active = false;
      allocatedUrls.forEach((url) => URL.revokeObjectURL(url));
      allocatedUrls.clear();
    };
  }, [selected]);

  return (
    <Panel className="review-synthetic-proof" variant="raised">
      <PanelHeader
        eyebrow="FROZEN SYNTHETIC VISUAL CONTEXT"
        title="模糊输入与复核副本"
        detail="展示隔离 Demo 的项目级合成资产；不是 Task 冻结视觉分母，也不是工厂效果证据。"
        actions={(
          <StatusBadge tone={state === "READY" ? "info" : state === "LOADING" ? "neutral" : "danger"} compact>
            {state === "READY" ? "FIXTURE VERIFIED" : state === "LOADING" ? "VERIFYING" : "FAIL CLOSED"}
          </StatusBadge>
        )}
      />

      {state === "LOADING" ? (
        <div className="review-synthetic-proof__state" role="status">
          <LoaderCircle className="is-spinning" size={18} />
          <span><strong>正在校验预览字节</strong>响应头 SHA 与浏览器复算必须同时通过。</span>
        </div>
      ) : state === "FAIL_CLOSED" ? (
        <div className="review-synthetic-proof__state is-error" role="alert">
          <ImageOff size={18} />
          <span><strong>演示资产不可用</strong>{error}</span>
        </div>
      ) : (
        <div className="review-synthetic-proof__compare">
          {previews.map(({ asset, role, url }) => (
            <figure key={asset.asset_id}>
              <div className="review-synthetic-proof__image">
                <img
                  src={url}
                  alt={role === "BEFORE" ? "冻结合成模糊输入" : "冻结合成复核副本"}
                />
                <span data-role={role.toLowerCase()}>{role}</span>
              </div>
              <figcaption>
                <strong>{role === "BEFORE" ? "模糊异常上下文" : "受控复核上下文"}</strong>
                <span>edge energy {asset.inspection.edge_energy.toFixed(4)}</span>
                <small>preview {compactSha(asset.preview_sha256)}</small>
              </figcaption>
            </figure>
          ))}
        </div>
      )}

      <div className="review-synthetic-proof__boundary">
        <ShieldCheck size={15} aria-hidden="true" />
        <span>项目级资产已校验；Agent 多轮与裁决能力由下方独立 Interaction Receipt 证明。</span>
        <strong>factory effect · NOT CLAIMED</strong>
      </div>
    </Panel>
  );
}

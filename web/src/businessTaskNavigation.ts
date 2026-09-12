/** Page guidance only. Never pass purpose as a runtime contract or authority. */
export function workbookAssetSearch(current: URLSearchParams, assetId?: string): URLSearchParams {
  const next = new URLSearchParams();
  const purpose = current.get("purpose");
  // Preserve unknown values so the UI can explain and recover them explicitly.
  if (purpose !== null) next.set("purpose", purpose);
  if (assetId) next.set("asset", assetId);
  return next;
}

export function snapshotTaskUrl(sourceId: string, purpose: string | null): string {
  if (!sourceId.trim()) throw new Error("缺少已创建快照的来源标识。");
  const query = new URLSearchParams({ create: "1", source: sourceId });
  if (purpose !== null) query.set("purpose", purpose);
  return `/command-center?${query}`;
}

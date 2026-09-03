import { useCallback, useEffect, useState } from "react";
import { detachedJcsSha256 } from "./data/jcs";

export const publicReplayMode =
  import.meta.env.VITE_VISIONDATA_PUBLIC_REPLAY === "true";

export const publicReplayManifestUrl =
  `${import.meta.env.BASE_URL}public-replay.v1.json`;

export interface PublicReplayManifest {
  schema_version: "visiondata-gate.public-replay.v1";
  source_mode: "PUBLIC_SYNTHETIC_REPLAY";
  release_status: {
    source_verification: "PASS_LOCAL_PUBLIC_SOURCE";
    public_projection: "STATIC_REPLAY_VERIFIED";
    production_readiness: "NOT_EVALUATED";
    production_release_allowed: false;
  };
  evidence_boundary: {
    baseline_tag: "v0.1.0-public-replay-r1";
    baseline_claim: "PASS_LOCAL_PUBLIC_REPLAY";
    release_artifacts_included: false;
    public_snapshot_attestation: "NOT_ISSUED";
  };
  case: {
    case_id: string;
    title: string;
    dataset: string;
    input_scope: string;
    initial_disposition: string;
    child_disposition: string;
    human_authority_required: boolean;
  };
  triggering_evidence: Array<{
    id: string;
    signal: string;
    measurement: string;
    threshold: string;
    effect: string;
  }>;
  worker_selection: {
    budget: {
      selected: number;
      maximum: number;
      model_call_count: number;
    };
    selected: Array<{
      worker: string;
      reason: string;
      triggering_evidence_id: string;
    }>;
    rejected: Array<{
      worker: string;
      reason: string;
    }>;
  };
  competing_hypotheses: Array<{
    id: string;
    statement: string;
    state: string;
  }>;
  missing_evidence: string[];
  phases: Array<{ id: string; label: string; state: string }>;
  lineage: Array<{ id: string; label: string; state: string }>;
  demo_controls: {
    read_only: true;
    backend_connected: false;
    api_key_input_enabled: false;
    customer_data_included: false;
    personal_data_included: false;
    raw_industrial_images_included: false;
  };
  manifest_sha256: string;
}

type PublicReplayManifestState =
  | { status: "LOADING" }
  | { status: "VERIFIED"; manifest: PublicReplayManifest }
  | { status: "FAILED"; reason: string };

type PublicReplayManifestResult = PublicReplayManifestState & {
  retry: () => void;
};

function hasExactKeys(
  value: unknown,
  expected: readonly string[],
): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const observed = Object.keys(value).sort();
  const required = [...expected].sort();
  return (
    observed.length === required.length &&
    observed.every((key, index) => key === required[index])
  );
}

function isPublicReplayManifest(value: unknown): value is PublicReplayManifest {
  if (!hasExactKeys(value, [
    "schema_version",
    "source_mode",
    "release_status",
    "evidence_boundary",
    "case",
    "triggering_evidence",
    "worker_selection",
    "competing_hypotheses",
    "missing_evidence",
    "phases",
    "lineage",
    "demo_controls",
    "manifest_sha256",
  ])) return false;
  const manifest = value as Partial<PublicReplayManifest>;
  return (
    manifest.schema_version === "visiondata-gate.public-replay.v1" &&
    manifest.source_mode === "PUBLIC_SYNTHETIC_REPLAY" &&
    manifest.evidence_boundary?.baseline_tag === "v0.1.0-public-replay-r1" &&
    manifest.evidence_boundary?.baseline_claim ===
      "PASS_LOCAL_PUBLIC_REPLAY" &&
    manifest.evidence_boundary?.release_artifacts_included === false &&
    manifest.evidence_boundary?.public_snapshot_attestation === "NOT_ISSUED" &&
    hasExactKeys(manifest.release_status, [
      "source_verification",
      "public_projection",
      "production_readiness",
      "production_release_allowed",
    ]) &&
    hasExactKeys(manifest.evidence_boundary, [
      "baseline_tag",
      "baseline_claim",
      "release_artifacts_included",
      "public_snapshot_attestation",
    ]) &&
    hasExactKeys(manifest.demo_controls, [
      "read_only",
      "backend_connected",
      "api_key_input_enabled",
      "customer_data_included",
      "personal_data_included",
      "raw_industrial_images_included",
    ]) &&
    manifest.release_status?.production_release_allowed === false &&
    manifest.demo_controls?.read_only === true &&
    manifest.demo_controls?.backend_connected === false &&
    manifest.demo_controls?.api_key_input_enabled === false &&
    manifest.demo_controls?.customer_data_included === false &&
    manifest.demo_controls?.personal_data_included === false &&
    manifest.demo_controls?.raw_industrial_images_included === false &&
    Array.isArray(manifest.worker_selection?.selected) &&
    Array.isArray(manifest.worker_selection?.rejected) &&
    Array.isArray(manifest.triggering_evidence) &&
    Array.isArray(manifest.competing_hypotheses) &&
    Array.isArray(manifest.missing_evidence) &&
    Array.isArray(manifest.phases) &&
    Array.isArray(manifest.lineage) &&
    typeof manifest.manifest_sha256 === "string" &&
    /^[0-9a-f]{64}$/.test(manifest.manifest_sha256)
  );
}

export function usePublicReplayManifest(): PublicReplayManifestResult {
  const [state, setState] = useState<PublicReplayManifestState>({
    status: "LOADING",
  });
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => {
    setAttempt((current) => current + 1);
  }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setState({ status: "LOADING" });
    void fetch(publicReplayManifestUrl, {
      cache: "no-store",
      credentials: "omit",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP_${response.status}`);
        const payload = (await response.json()) as unknown;
        if (!isPublicReplayManifest(payload)) {
          throw new Error("PUBLIC_REPLAY_CONTRACT_INVALID");
        }
        const observed = await detachedJcsSha256(
          payload as unknown as Record<string, unknown>,
          "manifest_sha256",
        );
        if (observed !== payload.manifest_sha256) {
          throw new Error("PUBLIC_REPLAY_SHA256_MISMATCH");
        }
        if (active) setState({ status: "VERIFIED", manifest: payload });
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return;
        setState({
          status: "FAILED",
          reason:
            error instanceof Error
              ? error.message
              : "PUBLIC_REPLAY_MANIFEST_UNAVAILABLE",
        });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [attempt]);

  return { ...state, retry };
}

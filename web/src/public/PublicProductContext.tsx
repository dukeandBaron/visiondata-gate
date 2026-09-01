import type { ReactNode } from "react";
import type {
  ProjectRecord,
  RuntimeConnectionState,
  WorkspaceRecord,
} from "../domain";

const publicConnection: RuntimeConnectionState = {
  api: "UNAVAILABLE",
  reviewer: "FALLBACK",
  apiBaseUrl: "disabled in public replay",
  reviewerBaseUrl: "verified static manifest",
};

const publicWorkspace: WorkspaceRecord = {
  workspace_id: "ws_public_replay",
  name: "Public Synthetic Replay",
  owner_user_id: "no-user",
  role: "read_only_reviewer",
  created_at: "2026-08-31T00:00:00Z",
};

const publicProject: ProjectRecord = {
  project_id: "prj_public_replay",
  workspace_id: publicWorkspace.workspace_id,
  name: "Synthetic-v3 · Public",
  description: "SHA-bound synthetic replay without a backend or customer data.",
  scenario_profile: "industrial",
  source_kind: "synthetic_demo",
  created_at: "2026-08-31T00:00:00Z",
  updated_at: "2026-08-31T00:00:00Z",
};

const publicProduct = {
  connection: publicConnection,
  reviewerSnapshot: undefined,
  workspaces: [publicWorkspace],
  projects: [publicProject],
  activeWorkspace: publicWorkspace,
  activeProject: publicProject,
  workspaceLoading: false,
  workspaceError: undefined,
  connectionRefreshing: false,
  refreshConnection: async () => undefined,
  selectWorkspace: (workspaceId: string) =>
    workspaceId === publicWorkspace.workspace_id,
  selectProject: (projectId: string) => projectId === publicProject.project_id,
  registerScopeChangeGuard: () => () => undefined,
  createProject: async (): Promise<ProjectRecord> => {
    throw new Error("Public replay is read-only.");
  },
  refreshWorkspaceScope: async () => undefined,
};

export function ProductProvider({ children }: { children: ReactNode }) {
  return children;
}

export function useProduct() {
  return publicProduct;
}

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  createProject as createProjectRequest,
  listProjects,
  listWorkspaces,
  probeRuntimeConnections,
} from "./data/api";
import type {
  ProjectSourceKind,
  ProjectRecord,
  ReviewerSnapshotApi,
  RuntimeConnectionState,
  ScenarioProfile,
  WorkspaceRecord,
} from "./domain";
import { publicReplayMode } from "./publicReplay";

interface ProductContextValue {
  connection: RuntimeConnectionState;
  reviewerSnapshot?: ReviewerSnapshotApi;
  workspaces: WorkspaceRecord[];
  projects: ProjectRecord[];
  activeWorkspace?: WorkspaceRecord;
  activeProject?: ProjectRecord;
  workspaceLoading: boolean;
  workspaceError?: string;
  connectionRefreshing: boolean;
  refreshConnection: () => Promise<void>;
  selectWorkspace: (workspaceId: string) => boolean;
  selectProject: (projectId: string) => boolean;
  registerScopeChangeGuard: (guard: ScopeChangeGuard) => () => void;
  createProject: (input: {
    name: string;
    description?: string;
    scenarioProfile?: ScenarioProfile;
    sourceKind?: ProjectSourceKind;
  }) => Promise<ProjectRecord>;
  refreshWorkspaceScope: () => Promise<void>;
}

interface ProductScopeChange {
  kind: "PROJECT" | "WORKSPACE" | "CREATE_PROJECT";
  workspaceId: string;
  projectId?: string;
}

type ScopeChangeGuard = (change: ProductScopeChange) => boolean;

const publicReplayConnection: RuntimeConnectionState = {
  api: "UNAVAILABLE",
  reviewer: "FALLBACK",
  apiBaseUrl: "disabled in public replay",
  reviewerBaseUrl: "verified static manifest",
};

const initialConnection: RuntimeConnectionState = publicReplayMode
  ? publicReplayConnection
  : {
      api: "CHECKING",
      reviewer: "CHECKING",
      apiBaseUrl: "checking",
      reviewerBaseUrl: "checking",
    };

const publicReplayWorkspace: WorkspaceRecord = {
  workspace_id: "ws_public_replay",
  name: "Public Synthetic Replay",
  owner_user_id: "no-user",
  role: "read_only_reviewer",
  created_at: "2026-08-31T00:00:00Z",
};

const publicReplayProject: ProjectRecord = {
  project_id: "prj_public_replay",
  workspace_id: publicReplayWorkspace.workspace_id,
  name: "Synthetic-v3 · Public",
  description: "SHA-bound synthetic replay without a backend or customer data.",
  scenario_profile: "industrial",
  source_kind: "synthetic_demo",
  created_at: "2026-08-31T00:00:00Z",
  updated_at: "2026-08-31T00:00:00Z",
};

const ProductContext = createContext<ProductContextValue | undefined>(undefined);

function pickPreferredProject(
  projects: ProjectRecord[],
  activeProjectId: string,
): ProjectRecord | undefined {
  return (
    projects.find((item) => item.project_id === activeProjectId) ??
    projects.find((item) => item.source_kind !== "synthetic_demo") ??
    projects[0]
  );
}

export function ProductProvider({ children }: { children: ReactNode }) {
  const [connection, setConnection] = useState<RuntimeConnectionState>(initialConnection);
  const [reviewerSnapshot, setReviewerSnapshot] = useState<ReviewerSnapshotApi>();
  const [workspaces, setWorkspaces] = useState<WorkspaceRecord[]>([]);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState(
    () =>
      publicReplayMode
        ? publicReplayWorkspace.workspace_id
        : window.sessionStorage.getItem("visiondata:active-workspace") ?? "",
  );
  const [activeProjectId, setActiveProjectId] = useState(
    () =>
      publicReplayMode
        ? publicReplayProject.project_id
        : window.sessionStorage.getItem("visiondata:active-project") ?? "",
  );
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [workspaceError, setWorkspaceError] = useState<string>();
  const [connectionRefreshing, setConnectionRefreshing] = useState(false);
  const scopeChangeGuardsRef = useRef(new Set<ScopeChangeGuard>());
  const connectionProbeRef = useRef<Promise<void> | null>(null);

  const canChangeScope = useCallback((change: ProductScopeChange): boolean => {
    return Array.from(scopeChangeGuardsRef.current).every((guard) => guard(change));
  }, []);

  const registerScopeChangeGuard = useCallback((guard: ScopeChangeGuard) => {
    scopeChangeGuardsRef.current.add(guard);
    return () => {
      scopeChangeGuardsRef.current.delete(guard);
    };
  }, []);

  const refreshConnection = useCallback((): Promise<void> => {
    if (publicReplayMode) {
      setConnection({
        ...publicReplayConnection,
        checkedAt: new Date().toISOString(),
      });
      setReviewerSnapshot(undefined);
      setConnectionRefreshing(false);
      return Promise.resolve();
    }
    if (connectionProbeRef.current) return connectionProbeRef.current;
    setConnectionRefreshing(true);
    const probe = probeRuntimeConnections()
      .then((result) => {
        setConnection(result.connection);
        setReviewerSnapshot(result.reviewerSnapshot);
      })
      .catch(() => {
        setConnection((current) => ({
          ...current,
          api: "UNAVAILABLE",
          reviewer: "FALLBACK",
          checkedAt: new Date().toISOString(),
        }));
        setReviewerSnapshot(undefined);
      })
      .finally(() => {
        if (connectionProbeRef.current === probe) {
          connectionProbeRef.current = null;
        }
        setConnectionRefreshing(false);
      });
    connectionProbeRef.current = probe;
    return probe;
  }, []);

  useEffect(() => {
    void refreshConnection();
  }, [refreshConnection]);

  useEffect(() => {
    if (publicReplayMode) return;
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void refreshConnection();
    };
    const refreshWhenOnline = () => void refreshConnection();
    const interval = window.setInterval(
      () => void refreshConnection(),
      connection.api === "CONNECTED" ? 30_000 : 5_000,
    );
    window.addEventListener("focus", refreshWhenOnline);
    window.addEventListener("online", refreshWhenOnline);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshWhenOnline);
      window.removeEventListener("online", refreshWhenOnline);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [connection.api, refreshConnection]);

  const refreshWorkspaceScope = useCallback(async () => {
    if (publicReplayMode) {
      setWorkspaces([publicReplayWorkspace]);
      setProjects([publicReplayProject]);
      setActiveWorkspaceId(publicReplayWorkspace.workspace_id);
      setActiveProjectId(publicReplayProject.project_id);
      setWorkspaceError(undefined);
      setWorkspaceLoading(false);
      return;
    }
    if (connection.api !== "CONNECTED") {
      setWorkspaceLoading(false);
      return;
    }
    setWorkspaceLoading(true);
    setWorkspaceError(undefined);
    try {
      const nextWorkspaces = await listWorkspaces();
      const preferredWorkspace =
        nextWorkspaces.find((item) => item.workspace_id === activeWorkspaceId) ??
        nextWorkspaces[0];
      const nextProjects = preferredWorkspace
        ? await listProjects(preferredWorkspace.workspace_id)
        : [];
      const preferredProject = pickPreferredProject(nextProjects, activeProjectId);
      setWorkspaces(nextWorkspaces);
      setProjects(nextProjects);
      setActiveWorkspaceId(preferredWorkspace?.workspace_id ?? "");
      setActiveProjectId(preferredProject?.project_id ?? "");
      if (preferredWorkspace) {
        window.sessionStorage.setItem(
          "visiondata:active-workspace",
          preferredWorkspace.workspace_id,
        );
      }
      if (preferredProject) {
        window.sessionStorage.setItem(
          "visiondata:active-project",
          preferredProject.project_id,
        );
      } else {
        window.sessionStorage.removeItem("visiondata:active-project");
      }
    } catch {
      setWorkspaceError("无法读取本地工作空间，请检查 API 状态。");
      setWorkspaces([]);
      setProjects([]);
    } finally {
      setWorkspaceLoading(false);
    }
  }, [activeProjectId, activeWorkspaceId, connection.api]);

  useEffect(() => {
    void refreshWorkspaceScope();
  }, [connection.api]);

  const selectWorkspace = useCallback(
    (workspaceId: string) => {
      if (!workspaces.some((item) => item.workspace_id === workspaceId)) return false;
      if (workspaceId === activeWorkspaceId) return true;
      if (!canChangeScope({ kind: "WORKSPACE", workspaceId })) return false;
      setActiveWorkspaceId(workspaceId);
      window.sessionStorage.setItem("visiondata:active-workspace", workspaceId);
      setWorkspaceLoading(true);
      setWorkspaceError(undefined);
      void listProjects(workspaceId)
        .then((nextProjects) => {
          const nextProject = pickPreferredProject(nextProjects, "");
          setProjects(nextProjects);
          setActiveProjectId(nextProject?.project_id ?? "");
          if (nextProject) {
            window.sessionStorage.setItem("visiondata:active-project", nextProject.project_id);
          } else {
            window.sessionStorage.removeItem("visiondata:active-project");
          }
        })
        .catch(() => setWorkspaceError("无法读取所选工作空间的项目。"))
        .finally(() => setWorkspaceLoading(false));
      return true;
    },
    [activeWorkspaceId, canChangeScope, workspaces],
  );

  const selectProject = useCallback(
    (projectId: string) => {
      if (!projects.some((item) => item.project_id === projectId)) return false;
      if (projectId === activeProjectId) return true;
      if (
        !canChangeScope({
          kind: "PROJECT",
          workspaceId: activeWorkspaceId,
          projectId,
        })
      ) {
        return false;
      }
      setActiveProjectId(projectId);
      window.sessionStorage.setItem("visiondata:active-project", projectId);
      return true;
    },
    [activeProjectId, activeWorkspaceId, canChangeScope, projects],
  );

  const createProject = useCallback(
    async (input: {
      name: string;
      description?: string;
      scenarioProfile?: ScenarioProfile;
      sourceKind?: ProjectSourceKind;
    }) => {
      if (publicReplayMode) {
        throw new Error("公开回放为只读模式，不能创建项目。");
      }
      if (!activeWorkspaceId) {
        throw new Error("请先选择一个工作空间。");
      }
      if (!canChangeScope({ kind: "CREATE_PROJECT", workspaceId: activeWorkspaceId })) {
        throw new Error("已取消创建项目；当前标注仍保留在工作簿中。");
      }
      const created = await createProjectRequest(activeWorkspaceId, input);
      const nextProjects = await listProjects(activeWorkspaceId);
      setProjects(nextProjects);
      setActiveProjectId(created.project_id);
      window.sessionStorage.setItem("visiondata:active-project", created.project_id);
      return created;
    },
    [activeWorkspaceId, canChangeScope],
  );

  const activeWorkspace = workspaces.find(
    (workspace) => workspace.workspace_id === activeWorkspaceId,
  );
  const activeProject = projects.find((project) => project.project_id === activeProjectId);

  const value = useMemo<ProductContextValue>(
    () => ({
      connection,
      reviewerSnapshot,
      workspaces,
      projects,
      activeWorkspace,
      activeProject,
      workspaceLoading,
      workspaceError,
      connectionRefreshing,
      refreshConnection,
      selectWorkspace,
      selectProject,
      registerScopeChangeGuard,
      createProject,
      refreshWorkspaceScope,
    }),
    [
      activeProject,
      activeWorkspace,
      connection,
      connectionRefreshing,
      projects,
      refreshConnection,
      refreshWorkspaceScope,
      registerScopeChangeGuard,
      reviewerSnapshot,
      createProject,
      selectProject,
      selectWorkspace,
      workspaceError,
      workspaceLoading,
      workspaces,
    ],
  );

  return <ProductContext.Provider value={value}>{children}</ProductContext.Provider>;
}

export function useProduct(): ProductContextValue {
  const context = useContext(ProductContext);
  if (!context) throw new Error("useProduct must be used inside ProductProvider");
  return context;
}

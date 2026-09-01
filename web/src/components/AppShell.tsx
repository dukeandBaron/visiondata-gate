import {
  Activity,
  Braces,
  BriefcaseBusiness,
  ChevronDown,
  CircleUserRound,
  Eye,
  FileImage,
  FileSearch,
  FolderKanban,
  GitBranch,
  Images,
  LayoutDashboard,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  SquareKanban,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import type { AgentTask, IndustrialIncident } from "../agentDomain";
import { useProduct } from "../ProductContext";
import {
  listAgentTasks,
  listIndustrialIncidentV5,
  listOperatorImages,
  listOperatorWorkOrders,
} from "../data/api";
import type { ProjectSourceKind, ScenarioProfile } from "../domain";
import type { OperatorImageAsset, OperatorWorkOrder } from "../operatorDomain";
import { operatorInitials, useLocalOperatorProfile } from "../localProfile";
import { publicReplayMode } from "../publicReplay";
import { BrandMark } from "./BrandMark";
import { Modal } from "./ui";

interface NavigationItem {
  label: string;
  path: string;
  icon: LucideIcon;
  keywords: string;
}

interface NavigationGroup {
  label: string;
  items: NavigationItem[];
}

const navigationGroups: NavigationGroup[] = [
  {
    label: "WORK",
    items: [
      { label: "图像工作簿", path: "/workspace", icon: Images, keywords: "workbook canvas image annotation 图像 标注 画布" },
      { label: "工作总览", path: "/command-center", icon: LayoutDashboard, keywords: "overview inbox dashboard 总览 收件箱" },
      { label: "案件", path: "/cases", icon: BriefcaseBusiness, keywords: "case incident 案件 调查" },
      { label: "CAPA 工单", path: "/capa", icon: SquareKanban, keywords: "work order capa 工单 整改" },
    ],
  },
  {
    label: "TRACE",
    items: [
      { label: "证据", path: "/evidence", icon: FileSearch, keywords: "evidence sha finding 证据 哈希" },
      { label: "运行", path: "/runs", icon: Activity, keywords: "run receipt tool trace 运行 回执" },
      { label: "血缘", path: "/lineage", icon: GitBranch, keywords: "lineage provenance causal 血缘 因果" },
    ],
  },
  {
    label: "SYSTEM",
    items: [
      { label: "集成", path: "/integrations", icon: Network, keywords: "cvat yolo coco adapter integration 集成" },
      { label: "治理", path: "/governance", icon: ShieldCheck, keywords: "policy audit release governance 治理" },
      { label: "评审证据", path: "/review", icon: Eye, keywords: "review frozen evidence 评审 冻结证据" },
      { label: "账户与会话", path: "/account", icon: CircleUserRound, keywords: "account profile actor session login 账户 用户 会话 登录" },
      { label: "设置", path: "/settings", icon: Settings, keywords: "settings provider local 设置" },
    ],
  },
];

const allNavigation = navigationGroups.flatMap((group) => group.items);

function routeTitle(pathname: string): string {
  if (pathname.startsWith("/cases/") && pathname !== "/cases") {
    return `案件 · ${pathname.split("/").filter(Boolean).at(-1)}`;
  }
  return allNavigation.find((item) => item.path === pathname)?.label ?? "VisionData Gate";
}

function routeIcon(pathname: string): LucideIcon {
  if (pathname.startsWith("/cases/")) return BriefcaseBusiness;
  return allNavigation.find((item) => item.path === pathname)?.icon ?? Braces;
}

function tabPathname(href: string): string {
  return href.split(/[?#]/, 1)[0] || "/workspace";
}

function readInitialTabs(): string[] {
  try {
    const stored = JSON.parse(
      window.sessionStorage.getItem("visiondata:open-tabs") ?? "[]",
    ) as unknown;
    if (Array.isArray(stored)) {
      const valid = stored.filter(
        (value): value is string => typeof value === "string" && value.startsWith("/"),
      );
      if (valid.length) return valid.slice(-7);
    }
  } catch {
    // Session hints are disposable; malformed state must not block the workbench.
  }
  return ["/workspace"];
}

function CreateProjectDialog({ onClose }: { onClose: () => void }) {
  const { createProject, activeWorkspace } = useProduct();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scenarioProfile, setScenarioProfile] = useState<ScenarioProfile>("generic");
  const [sourceKind, setSourceKind] = useState<ProjectSourceKind>(
    "local_authorized_directory",
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => inputRef.current?.focus(), []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName || submitting) return;
    setSubmitting(true);
    setError(undefined);
    try {
      await createProject({
        name: normalizedName,
        description: description.trim(),
        scenarioProfile,
        sourceKind,
      });
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "项目创建失败，请检查本地 API。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title="新建项目" onClose={onClose}>
      <form className="project-create-form" onSubmit={(event) => void submit(event)}>
        <p>
          项目只建立工作范围，不会自动导入图片、生成结论或运行 Agent。
          后续资产与结果由你在工作簿中真实创建。
        </p>
        <label>
          <span>项目名称</span>
          <input
            ref={inputRef}
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={120}
            placeholder="例如：Line 03 相机换型审核"
            required
          />
        </label>
        <label>
          <span>说明（可选）</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={500}
            rows={3}
            placeholder="记录目标、边界或责任范围"
          />
        </label>
        <div className="project-create-form__row">
          <label>
            <span>场景</span>
            <select
              value={scenarioProfile}
              onChange={(event) => setScenarioProfile(event.target.value as ScenarioProfile)}
            >
              <option value="generic">通用视觉</option>
              <option value="industrial">工业制造</option>
              <option value="automotive">汽车制造</option>
              <option value="wearable">可穿戴设备</option>
              <option value="education">教育研究</option>
              <option value="finance">金融文档</option>
            </select>
          </label>
          <label>
            <span>数据来源</span>
            <select
              value={sourceKind}
              onChange={(event) => setSourceKind(event.target.value as ProjectSourceKind)}
            >
              <option value="local_authorized_directory">本地授权数据</option>
              <option value="external_residency_reference">外部驻留引用</option>
            </select>
          </label>
        </div>
        {error ? <div className="project-create-form__error">{error}</div> : null}
        <footer>
          <span>{activeWorkspace?.name ?? "未选择工作空间"}</span>
          <button type="button" onClick={onClose} disabled={submitting}>取消</button>
          <button className="is-primary" type="submit" disabled={!name.trim() || submitting}>
            {submitting ? "正在创建…" : "创建空项目"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

interface PaletteResult {
  id: string;
  label: string;
  detail: string;
  searchText?: string;
  kind?: string;
  icon: LucideIcon;
  action: () => void;
}

interface PaletteIncident {
  task: AgentTask;
  incident: IndustrialIncident;
}

function compactEntityId(value: string): string {
  return value.length > 19 ? `${value.slice(0, 11)}…${value.slice(-6)}` : value;
}

function CommandPalette({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [assets, setAssets] = useState<OperatorImageAsset[]>([]);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [incidents, setIncidents] = useState<PaletteIncident[]>([]);
  const [workOrders, setWorkOrders] = useState<OperatorWorkOrder[]>([]);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [scopeLoadFailures, setScopeLoadFailures] = useState<string[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const loadGeneration = useRef(0);
  const navigate = useNavigate();
  const { activeWorkspace, activeProject, projects, selectProject } = useProduct();

  useEffect(() => inputRef.current?.focus(), []);
  useEffect(() => {
    const generation = loadGeneration.current + 1;
    loadGeneration.current = generation;
    const workspaceId = activeWorkspace?.workspace_id;
    const projectId = activeProject?.project_id;
    const includeSampleAssets = activeProject?.source_kind === "synthetic_demo";

    setAssets([]);
    setTasks([]);
    setIncidents([]);
    setWorkOrders([]);
    setScopeLoadFailures([]);
    if (publicReplayMode) {
      setScopeLoading(false);
      return;
    }
    if (!workspaceId || !projectId) {
      setScopeLoading(false);
      return;
    }

    setScopeLoading(true);
    void (async () => {
      const [assetResult, taskResult, workOrderResult] = await Promise.allSettled([
        listOperatorImages(workspaceId, projectId, includeSampleAssets),
        listAgentTasks(workspaceId, projectId),
        listOperatorWorkOrders(workspaceId, projectId),
      ]);
      if (loadGeneration.current !== generation) return;

      const failures: string[] = [];
      if (assetResult.status === "fulfilled") {
        setAssets(assetResult.value);
      } else {
        failures.push("图像");
      }

      const scopedTasks = taskResult.status === "fulfilled"
        ? taskResult.value.filter(
          (task) => task.workspace_id === workspaceId && task.project_id === projectId,
        )
        : [];
      if (taskResult.status === "fulfilled") {
        setTasks(scopedTasks);
      } else {
        failures.push("Agent Task");
      }

      if (workOrderResult.status === "fulfilled") {
        setWorkOrders(
          workOrderResult.value.filter(
            (workOrder) => workOrder.project_id === projectId,
          ),
        );
      } else {
        failures.push("像素工单");
      }

      if (scopedTasks.length) {
        const incidentResults = await Promise.allSettled(
          scopedTasks.map(async (task) => ({
            task,
            incidents: await listIndustrialIncidentV5(task.task_id),
          })),
        );
        if (loadGeneration.current !== generation) return;

        const nextIncidents: PaletteIncident[] = [];
        let incidentFailure = false;
        incidentResults.forEach((result) => {
          if (result.status === "rejected") {
            incidentFailure = true;
            return;
          }
          result.value.incidents.forEach((incident) => {
            if (incident.task_id === result.value.task.task_id) {
              nextIncidents.push({ task: result.value.task, incident });
            }
          });
        });
        setIncidents(nextIncidents);
        if (incidentFailure) failures.push("部分 Incident");
      }

      if (loadGeneration.current !== generation) return;
      setScopeLoadFailures(failures);
      setScopeLoading(false);
    })();

    return () => {
      if (loadGeneration.current === generation) loadGeneration.current += 1;
    };
  }, [
    activeProject?.project_id,
    activeProject?.source_kind,
    activeWorkspace?.workspace_id,
  ]);

  const results = useMemo<PaletteResult[]>(() => {
    const navigateTo = (path: string) => {
      navigate(path);
      onClose();
    };
    const bindAgentTask = (task: AgentTask) => {
      window.sessionStorage.setItem(
        `visiondata:agent-task:${task.project_id}`,
        task.task_id,
      );
    };
    const candidates: PaletteResult[] = [
      ...allNavigation.map((item) => ({
        id: `page:${item.path}`,
        label: item.label,
        detail: `页面 · ${item.path}`,
        searchText: item.keywords,
        kind: "页面",
        icon: item.icon,
        action: () => navigateTo(item.path),
      })),
      ...tasks.map((task) => ({
        id: `task:${task.task_id}`,
        label: task.goal,
        detail: `${task.execution_status} · ${compactEntityId(task.task_id)}`,
        searchText: [
          task.task_id,
          task.execution_status,
          task.current_phase,
          task.initial_decision,
          task.final_decision,
          task.runtime_status,
        ].filter(Boolean).join(" "),
        kind: "TASK",
        icon: Workflow,
        action: () => {
          bindAgentTask(task);
          navigateTo(`/command-center?task=${encodeURIComponent(task.task_id)}`);
        },
      })),
      ...incidents.map(({ task, incident }) => ({
        id: `incident:${task.task_id}:${incident.case_id}:${incident.case_version}`,
        label: incident.case_id,
        detail: `${incident.status} · v${incident.case_version} · ${compactEntityId(task.task_id)}`,
        searchText: [
          incident.case_id,
          incident.status,
          incident.recommendation,
          incident.recommendation_reason,
          task.task_id,
          task.goal,
          ...incident.worker_selection_receipt.selected_worker_ids,
        ].join(" "),
        kind: "INCIDENT",
        icon: BriefcaseBusiness,
        action: () => {
          bindAgentTask(task);
          navigateTo(
            `/cases?task=${encodeURIComponent(task.task_id)}&case=${encodeURIComponent(incident.case_id)}&version=${incident.case_version}`,
          );
        },
      })),
      ...workOrders.map((workOrder) => ({
        id: `work-order:${workOrder.work_order_id}`,
        label: workOrder.annotation.label || workOrder.image_name,
        detail: `${workOrder.status} · ${compactEntityId(workOrder.work_order_id)}`,
        searchText: [
          workOrder.work_order_id,
          workOrder.image_name,
          workOrder.annotation.label,
          workOrder.status,
          workOrder.assignee,
          workOrder.asset_id,
          workOrder.asset_sha256,
        ].join(" "),
        kind: "像素工单",
        icon: SquareKanban,
        action: () => navigateTo(
          `/capa?workOrder=${encodeURIComponent(workOrder.work_order_id)}`,
        ),
      })),
      ...projects.map((project) => ({
        id: `project:${project.project_id}`,
        label: project.name,
        detail: `${project.source_kind === "synthetic_demo" ? "可选样例" : "项目"} · ${project.project_id}`,
        kind: "项目",
        icon: FolderKanban,
        action: () => {
          if (selectProject(project.project_id)) navigateTo("/workspace");
        },
      })),
      ...assets.map((asset) => ({
        id: `asset:${asset.asset_id}`,
        label: asset.original_name,
        detail: `图像 · ${asset.source_sha256.slice(0, 12)}…`,
        searchText: `${asset.asset_id} ${asset.source_sha256}`,
        kind: "图像",
        icon: FileImage,
        action: () => navigateTo(`/workspace?asset=${encodeURIComponent(asset.asset_id)}`),
      })),
    ];
    const normalized = query.trim().toLowerCase();
    if (!normalized) return candidates.slice(0, 18);
    return candidates
      .filter((item) =>
        `${item.label} ${item.detail} ${item.searchText ?? ""}`
          .toLowerCase()
          .includes(normalized),
      )
      .slice(0, 24);
  }, [assets, incidents, navigate, onClose, projects, query, selectProject, tasks, workOrders]);

  useEffect(() => {
    setActiveIndex((current) => Math.min(current, Math.max(0, results.length - 1)));
  }, [results.length]);

  return (
    <Modal title="Command Palette" onClose={onClose}>
      <div className="command-search">
        <Search size={17} aria-hidden="true" />
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActiveIndex(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActiveIndex((current) =>
                results.length ? (current + 1) % results.length : 0,
              );
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveIndex((current) =>
                results.length ? (current - 1 + results.length) % results.length : 0,
              );
            }
            if (event.key === "Enter" && results[activeIndex]) {
              event.preventDefault();
              results[activeIndex].action();
            }
          }}
          placeholder="搜索页面、Task、案件、工单、项目或图像…"
          aria-label="全局搜索"
        />
        <kbd>ESC</kbd>
      </div>
      <div className="command-results">
        {results.map((item, index) => (
          <button
            type="button"
            key={item.id}
            className={index === activeIndex ? "is-active" : ""}
            onMouseEnter={() => setActiveIndex(index)}
            onClick={item.action}
          >
            <item.icon size={17} aria-hidden="true" />
            <span>
              <strong>
                {item.label}
                {item.kind ? <em className="command-entity-kind">{item.kind}</em> : null}
              </strong>
              <small>{item.detail}</small>
            </span>
          </button>
        ))}
        {scopeLoading ? <p className="command-empty">正在读取当前项目的真实实体…</p> : null}
        {!scopeLoading && scopeLoadFailures.length ? (
          <p className="command-empty command-entity-load-note">
            未载入：{scopeLoadFailures.join("、")}；其余结果仍可使用
          </p>
        ) : null}
        {!scopeLoading && results.length === 0 ? (
          <p className="command-empty">没有匹配的页面、Task、案件、工单、项目或图像</p>
        ) : null}
      </div>
    </Modal>
  );
}

export function AppShell() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [openTabs, setOpenTabs] = useState<string[]>(readInitialTabs);
  const location = useLocation();
  const navigate = useNavigate();
  const { profile } = useLocalOperatorProfile();
  const {
    connection,
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
  } = useProduct();
  const operatorRoute =
    location.pathname.startsWith("/workspace") || location.pathname === "/command-center";
  const operationalProjects = publicReplayMode
    ? projects
    : projects.filter((project) => project.source_kind !== "synthetic_demo");
  const sampleProjects = publicReplayMode
    ? []
    : projects.filter((project) => project.source_kind === "synthetic_demo");
  const activeTabHref = `${location.pathname}${location.search}${location.hash}`;

  useEffect(() => {
    setOpenTabs((current) => {
      const existingIndex = current.findIndex(
        (href) => tabPathname(href) === location.pathname,
      );
      if (existingIndex >= 0) {
        if (current[existingIndex] === activeTabHref) return current;
        const next = [...current];
        next[existingIndex] = activeTabHref;
        return next;
      }
      return [...current, activeTabHref].slice(-7);
    });
  }, [activeTabHref, location.pathname]);

  useEffect(() => {
    window.sessionStorage.setItem("visiondata:open-tabs", JSON.stringify(openTabs));
  }, [openTabs]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "b") {
        event.preventDefault();
        setSidebarCollapsed((value) => !value);
      }
      if (event.key === "Escape") {
        setPaletteOpen(false);
        setProjectDialogOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const closeTab = (href: string) => {
    const next = openTabs.filter((item) => item !== href);
    const fallback = next.at(-1) ?? "/workspace";
    setOpenTabs(next.length ? next : [fallback]);
    if (tabPathname(href) === location.pathname) navigate(fallback);
  };

  return (
    <div className={`linear-shell${sidebarCollapsed ? " is-sidebar-collapsed" : ""}${location.pathname === "/review" ? " is-review-route" : ""}`}>
      <a className="skip-to-content" href="#main-content">跳到主要内容</a>
      <aside className="linear-sidebar" aria-label="工作空间导航">
        <header className="linear-sidebar__header">
          <NavLink to="/workspace" aria-label="打开图像工作簿">
            <BrandMark compact={sidebarCollapsed} />
          </NavLink>
          <button
            type="button"
            onClick={() => setSidebarCollapsed((value) => !value)}
            title={sidebarCollapsed ? "展开侧栏 (Ctrl+B)" : "收起侧栏 (Ctrl+B)"}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </header>

        <div className="linear-workspace-switcher">
          <span className="linear-workspace-switcher__glyph">
            {(activeWorkspace?.name ?? "V").slice(0, 1).toUpperCase()}
          </span>
          <label>
            <small>WORKSPACE</small>
            <select
              value={activeWorkspace?.workspace_id ?? ""}
              onChange={(event) => selectWorkspace(event.target.value)}
              disabled={workspaceLoading || workspaces.length === 0}
              aria-label="选择工作空间"
            >
              {workspaces.length === 0 ? <option value="">没有工作空间</option> : null}
              {workspaces.map((workspace) => (
                <option key={workspace.workspace_id} value={workspace.workspace_id}>
                  {workspace.name}
                </option>
              ))}
            </select>
          </label>
          <ChevronDown size={14} />
        </div>

        <button
          className="linear-search-trigger"
          type="button"
          aria-label="搜索或运行命令"
          onClick={() => setPaletteOpen(true)}
        >
          <Search size={15} />
          <span>搜索或运行命令</span>
          <kbd>Ctrl K</kbd>
        </button>

        <nav className="linear-nav" aria-label="产品页面">
          {navigationGroups.slice(0, 2).map((group) => (
            <section key={group.label}>
              <small>{group.label}</small>
              {group.items.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  data-nav-path={item.path}
                  className={({ isActive }) =>
                    isActive || location.pathname.startsWith(`${item.path}/`) ? "is-active" : ""
                  }
                  title={item.label}
                >
                  <item.icon size={15} />
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </section>
          ))}
        </nav>

        <section className="linear-projects">
          <header>
            <span>PROJECTS</span>
            <button
              type="button"
              onClick={() => setProjectDialogOpen(true)}
              title={publicReplayMode ? "公开回放禁止创建项目" : "创建空项目"}
              disabled={publicReplayMode}
            >
              <Plus size={14} />
            </button>
          </header>
          <div>
            {operationalProjects.map((project) => (
              <button
                type="button"
                key={project.project_id}
                className={project.project_id === activeProject?.project_id ? "is-active" : ""}
                onClick={() => {
                  if (selectProject(project.project_id)) navigate("/workspace");
                }}
                title={project.name}
              >
                <FolderKanban size={14} />
                <span>{project.name}</span>
              </button>
            ))}
            {!workspaceLoading && operationalProjects.length === 0 ? (
              <button type="button" className="is-empty" onClick={() => setProjectDialogOpen(true)}>
                <Plus size={14} />
                <span>创建第一个项目</span>
              </button>
            ) : null}
            {sampleProjects.length > 0 ? (
              <details className="linear-samples">
                <summary>可选样例 · {sampleProjects.length}</summary>
                {sampleProjects.map((project) => (
                  <button
                    type="button"
                    key={project.project_id}
                    onClick={() => {
                      if (selectProject(project.project_id)) navigate("/workspace");
                    }}
                  >
                    <FolderKanban size={13} />
                    <span>{project.name}</span>
                    <em>SAMPLE</em>
                  </button>
                ))}
              </details>
            ) : null}
          </div>
        </section>

        <nav className="linear-nav linear-nav--footer" aria-label="系统页面">
          {navigationGroups[2]!.items.map((item) => (
            <NavLink key={item.path} to={item.path} title={item.label} data-nav-path={item.path}>
              <item.icon size={15} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <NavLink className="linear-user" to="/account" title="账户与会话中心">
          <span className="linear-user__avatar">{publicReplayMode ? "PR" : operatorInitials(profile)}</span>
          <span><strong>{publicReplayMode ? "Public Reviewer" : profile.displayName}</strong><small>{publicReplayMode ? "anonymous · read only" : profile.role}</small></span>
          <i className={`runtime-dot runtime-dot--${connection.api.toLowerCase()}`} />
        </NavLink>
      </aside>

      <div className={`linear-main${publicReplayMode ? " has-public-replay" : ""}`}>
        <header className="linear-topbar">
          <div className="linear-breadcrumbs">
            <span>{activeWorkspace?.name ?? "Workspace"}</span>
            <span>{activeProject?.name ?? "未选择项目"}</span>
            <strong>{routeTitle(location.pathname)}</strong>
          </div>
          <div className="linear-topbar__actions">
            {workspaceError ? <span className="linear-topbar__error">{workspaceError}</span> : null}
            <NavLink
              to="/review"
              className={({ isActive }) => `linear-review-shortcut${isActive ? " is-active" : ""}`}
              aria-label="打开评审快速路径"
            >
              <Eye size={14} />
              <span>{location.pathname === "/review" ? "当前评审路径" : "评审快速路径"}</span>
            </NavLink>
            <button type="button" onClick={() => setPaletteOpen(true)}>
              <Search size={14} /> 快速查找
            </button>
            <button
              type="button"
              className="linear-api-state"
              title={`${connection.apiBaseUrl} · 点击重新检测`}
              onClick={() => void refreshConnection()}
              disabled={connectionRefreshing}
              aria-label={publicReplayMode ? "公开静态回放状态" : "重新检测本地 API"}
            >
              <i className={`runtime-dot runtime-dot--${connection.api.toLowerCase()}`} />
              {connectionRefreshing ? <RefreshCw className="is-spinning" size={12} /> : null}
              {publicReplayMode ? "Static replay" : connection.api === "CONNECTED" ? "Local API" : "API offline"}
            </button>
          </div>
        </header>

        {publicReplayMode ? (
          <div className="public-replay-banner" role="note">
            <span>PUBLIC SYNTHETIC REPLAY</span>
            <strong>静态只读 · 无后端 · 无客户数据 · 无 API Key</strong>
            <small>production_release_allowed=false</small>
          </div>
        ) : null}

        <nav className="linear-tabs" aria-label="已打开页面">
          {openTabs.map((href) => {
            const pathname = tabPathname(href);
            const Icon = routeIcon(pathname);
            const active = href === activeTabHref;
            return (
              <div key={href} className={`linear-tab${active ? " is-active" : ""}`}>
                <NavLink to={href}>
                  <Icon size={14} />
                  <span>{routeTitle(pathname)}</span>
                </NavLink>
                <button
                  type="button"
                  onClick={() => closeTab(href)}
                  aria-label={`关闭 ${routeTitle(pathname)}`}
                >
                  <X size={12} />
                </button>
              </div>
            );
          })}
        </nav>

        <main className={`linear-content${operatorRoute ? " is-workbook" : ""}`} id="main-content">
          <Suspense fallback={<RouteLoading />}>
            <Outlet />
          </Suspense>
        </main>

        <footer className="linear-statusbar">
          <span><ShieldCheck size={12} /> {publicReplayMode ? "PUBLIC REPLAY" : "LOCAL-FIRST"}</span>
          <span className="linear-statusbar__scope">{activeWorkspace?.name ?? "no workspace"}</span>
          <span className="linear-statusbar__scope">{activeProject?.name ?? "no project"}</span>
          <span className="linear-statusbar__spacer" />
          <span>raw outbound: 0</span>
          <span><i className={`runtime-dot runtime-dot--${connection.api.toLowerCase()}`} /> {publicReplayMode ? "backend disabled" : `API ${connection.api}`}</span>
          <span>authority: human</span>
        </footer>
      </div>

      {paletteOpen ? <CommandPalette onClose={() => setPaletteOpen(false)} /> : null}
      {projectDialogOpen && !publicReplayMode ? <CreateProjectDialog onClose={() => setProjectDialogOpen(false)} /> : null}
      <div className="sr-only" aria-live="polite">
        {publicReplayMode ? "公开合成回放，后端与写操作已禁用" : connection.api === "CONNECTED" ? "本地 API 已连接" : "本地 API 当前未连接"}
      </div>
    </div>
  );
}

export function RouteLoading() {
  return (
    <div className="route-loading" role="status" aria-live="polite">
      <div className="route-loading__status">
        <Sparkles size={16} aria-hidden="true" />
        <span>正在加载工作区</span>
        <small>保留当前项目与页面位置</small>
      </div>
      <div className="route-loading__frame" aria-hidden="true">
        <div className="route-loading__rail">
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
        <div className="route-loading__canvas">
          <span />
          <strong />
          <i />
          <i />
          <i />
        </div>
        <div className="route-loading__inspector">
          <Workflow size={16} />
          <i />
          <i />
          <i />
        </div>
      </div>
    </div>
  );
}

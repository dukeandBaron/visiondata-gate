import { ArrowRight, Check, ChevronRight, FileImage, FolderOpen, RefreshCw, Search } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { AgentTask } from "../agentDomain";
import { BrandMark } from "../components/BrandMark";
import { listAgentTasks, listOperatorImages, listOperatorWorkOrders } from "../data/api";
import { getIdentitySessionSnapshot, subscribeIdentitySession } from "../identitySession";
import type { OperatorWorkOrder } from "../operatorDomain";
import { useProduct } from "../ProductContext";
import "../styles/start-surfaces.css";

interface ProjectActivity {
  key: string;
  loading: boolean;
  images: number | null;
  tasks: AgentTask[] | null;
  orders: OperatorWorkOrder[] | null;
  errors: string[];
}

const taskLabels: Record<string, string> = {
  CREATED: "待执行", PLANNED: "计划已生成", RUNNING: "执行中", VERIFYING: "复验中",
  COMPLETED: "执行完成", FAILED: "执行失败", CANCELLED: "已取消", ARCHIVED: "已归档",
};

function taskAction(task: AgentTask): string {
  if (task.execution_status === "PLANNED" && task.plan_approval_required) return "待人工审批";
  return taskLabels[task.execution_status] ?? task.execution_status;
}

/** Project start surface: no simulated live data and no writes from overview controls. */
export function HomePage() {
  const navigate = useNavigate();
  const { connection, projects, activeProject, activeWorkspace, selectProject, workspaceLoading,
    workspaceError, refreshWorkspaceScope, refreshConnection, connectionRefreshing } = useProduct();
  const identity = useSyncExternalStore(subscribeIdentitySession, getIdentitySessionSnapshot, getIdentitySessionSnapshot);
  const [query, setQuery] = useState("");
  const [showExamples, setShowExamples] = useState(false);
  const [showAllTasks, setShowAllTasks] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [activity, setActivity] = useState<ProjectActivity>();
  const requestId = useRef(0);
  const workspaceId = activeWorkspace?.workspace_id;
  const projectId = activeProject?.project_id;
  const key = [identity.generation, workspaceId, projectId, connection.api, workspaceLoading, workspaceError].join(":");
  const currentKey = useRef(key);
  currentKey.current = key;
  const canRead = connection.api === "CONNECTED" && !!workspaceId && !!projectId && !workspaceLoading && !workspaceError;
  const currentActivity = canRead && activity?.key === key ? activity : undefined;

  useEffect(() => {
    const request = ++requestId.current;
    if (!canRead || !workspaceId || !projectId) { setActivity(undefined); return; }
    setActivity({ key, loading: true, images: null, tasks: null, orders: null, errors: [] });
    const scoped = <T extends { workspace_id: string; project_id?: string | null }>(items: T[]): T[] => {
      if (!Array.isArray(items) || items.some((item) => !item || item.workspace_id !== workspaceId || item.project_id !== projectId)) {
        throw new Error("响应项目不匹配");
      }
      return items;
    };
    void Promise.allSettled([
      listOperatorImages(workspaceId, projectId).then(scoped),
      listAgentTasks(workspaceId, projectId).then(scoped),
      listOperatorWorkOrders(workspaceId, projectId).then(scoped),
    ]).then(([images, tasks, orders]) => {
      if (request !== requestId.current || key !== currentKey.current) return;
      setActivity({ key, loading: false,
        images: images.status === "fulfilled" ? images.value.length : null,
        tasks: tasks.status === "fulfilled" ? tasks.value : null,
        orders: orders.status === "fulfilled" ? orders.value : null,
        errors: [images.status === "rejected" ? "图片" : "", tasks.status === "rejected" ? "任务" : "", orders.status === "rejected" ? "工单" : ""].filter(Boolean),
      });
    });
    return () => { requestId.current += 1; };
  }, [canRead, workspaceId, projectId, key, refreshToken]);

  const eligibleProjects = projects.filter((project) => project.workspace_id === workspaceId && (showExamples || project.source_kind !== "synthetic_demo"));
  const matchedProjects = eligibleProjects.filter((project) => (project.name + " " + project.description + " " + project.project_id).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const tasks = currentActivity?.tasks;
  const actionableTasks = tasks?.filter((task) => task.execution_status === "FAILED" || (task.execution_status === "PLANNED" && task.plan_approval_required));
  const visibleTasks = (showAllTasks ? tasks : actionableTasks)?.slice(0, 6);
  const openOrders = currentActivity?.orders?.filter((order) => !["CLOSED", "REJECTED"].includes(order.status));
  const value = (count: number | null | undefined) => currentActivity?.loading ? "读取中" : count === null || count === undefined ? "未知" : String(count);

  return <div className="start-home">
    <header className="start-home-nav">
      <BrandMark />
      <nav aria-label="首页导航"><Link to="/platform">任务总览</Link><Link to="/account">账户与团队</Link></nav>
    </header>
    <main>
      <header className="start-heading" id="product">
        <div><p className="start-kicker">{activeWorkspace?.name ?? "工业视觉交付站"}</p><h1>回到项目，继续工作。</h1><p>选择一批数据，处理未完成的检查与返修。</p></div>
        <div className="start-connection"><span className={"runtime-dot runtime-dot--" + connection.api.toLowerCase()} />
          <span>{connection.api === "CONNECTED" ? "工作台 API 已连接" : connection.api === "CHECKING" ? "正在检查连接" : "工作台 API 未连接"}<small>不代表工厂在线接入</small></span>
        </div>
      </header>

      <div className="start-grid">
        <section className="start-projects" aria-labelledby="start-projects-title">
          <header className="start-section-heading"><h2 id="start-projects-title">项目</h2><Link to="/workspace">管理项目 <ChevronRight size={14} /></Link></header>
          <label className="start-search"><Search size={16} /><span className="start-visually-hidden">搜索项目</span><input type="search" aria-label="搜索项目" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、描述或项目编号" />{query ? <button type="button" onClick={() => setQuery("")}>清除</button> : null}</label>
          {connection.api !== "CONNECTED" ? <div className="start-empty" role="status"><strong>连接后读取你的项目</strong><p>没有使用示例项目替代。请检查本机服务或登录状态。</p><button type="button" disabled={connectionRefreshing} onClick={() => void refreshConnection()}>{connectionRefreshing ? "正在检查连接…" : "重新检查连接"}</button><Link to="/account">打开账户</Link></div>
            : workspaceLoading ? <p className="start-empty" role="status">正在读取工作空间与项目…</p>
            : workspaceError ? <div className="start-empty" role="alert"><strong>项目列表读取失败</strong><p>当前项目数量未知。请重新读取；没有将失败显示为空列表。</p><button type="button" onClick={() => void refreshWorkspaceScope()}>重新读取项目</button></div>
            : matchedProjects.length ? <div className="start-project-list" aria-label="可选择的项目">{matchedProjects.map((project) => <button key={project.project_id} type="button" aria-label={"选择项目 " + project.name} aria-pressed={project.project_id === projectId} onClick={() => { selectProject(project.project_id); setShowAllTasks(false); }}>
              <FolderOpen size={18} /><span><strong>{project.name}</strong><small>{project.description || "尚未填写项目说明"}</small><code>{project.project_id}</code></span><span className="start-project-mark">{project.source_kind === "synthetic_demo" ? <small>示例</small> : null}{project.project_id === projectId ? <Check size={16} /> : <ChevronRight size={16} />}</span>
            </button>)}</div>
            : <div className="start-empty"><strong>{query ? "没有匹配的项目" : "还没有工作项目"}</strong><p>{query ? "试试项目名称、描述或编号，也可以清除搜索。" : "进入工作簿后，在侧栏创建项目，再导入你有权使用的数据。"}</p>{query ? <button type="button" onClick={() => setQuery("")}>清除搜索</button> : <Link to="/workspace">前往工作簿创建项目 <ArrowRight size={14} /></Link>}</div>}
          {projects.some((project) => project.source_kind === "synthetic_demo") ? <label className="start-example-toggle"><input type="checkbox" checked={showExamples} onChange={(event) => setShowExamples(event.target.checked)} />显示示例项目（不代表真实业务数据）</label> : null}
        </section>

        <section className="start-activity" aria-labelledby="start-current-title" id="proof" aria-busy={currentActivity?.loading ?? false}>
          <header className="start-current-heading"><div><span className="start-kicker">当前项目</span><h2 id="start-current-title">{activeProject?.name ?? "先选择一个项目"}</h2>{activeProject?.source_kind === "synthetic_demo" ? <small>示例数据 · 非工厂运行</small> : null}</div><button type="button" className="start-icon-button" aria-label="刷新当前项目待办" disabled={!canRead || currentActivity?.loading} onClick={() => setRefreshToken((value) => value + 1)}><RefreshCw size={16} className={currentActivity?.loading ? "is-spinning" : ""} /></button></header>
          <button type="button" className="start-primary" disabled={!canRead} onClick={() => navigate("/workspace")}><FileImage size={18} />进入图像工作簿 <ArrowRight size={16} /></button>
          {!canRead ? <p className="start-note">连接工作台并选择项目后，读取对应图片、任务与工单。</p> : null}
          <dl className="start-counts"><div><dt>工作簿图片</dt><dd>{value(currentActivity?.images)}</dd></div><div><dt>返回的任务</dt><dd>{value(tasks?.length)}</dd></div><div><dt>开放工单</dt><dd>{value(openOrders?.length)}</dd></div></dl>
          {currentActivity?.errors.length ? <p className="start-read-error" role="alert">{currentActivity.errors.join("、")}读取失败 · UNKNOWN。未读取的数据保持未知，请刷新重试。</p> : null}
          {currentActivity?.loading ? <p role="status" className="start-note">正在读取当前项目待办…</p> : null}
          <section className="start-tasks" aria-label="项目任务待办"><header className="start-section-heading"><h3>{showAllTasks ? "最近任务" : "需要你处理"}</h3><button type="button" aria-pressed={showAllTasks} onClick={() => setShowAllTasks((current) => !current)}>{showAllTasks ? "只看待处理" : "查看最近任务"}</button></header>
            {!currentActivity?.loading && tasks ? visibleTasks?.length ? <ul>{visibleTasks.map((task) => <li key={task.task_id}><Link to={"/command-center?task=" + encodeURIComponent(task.task_id)}><span><strong>{task.goal}</strong><small>{taskAction(task)}</small></span><ChevronRight size={15} /></Link></li>)}</ul> : <p className="start-note">{showAllTasks ? "尚无任务。请在工作簿准备并封存数据后创建检查任务。" : "当前返回的任务中，没有待计划审批或执行失败项。"}</p> : null}
            {tasks && tasks.length >= 200 ? <p className="start-note">本页最多读取 200 项；更早的任务请前往任务页面查询。</p> : null}
            {tasks && (showAllTasks ? tasks.length : actionableTasks?.length ?? 0) > 6 ? <Link to="/platform">查看全部已返回任务 <ArrowRight size={14} /></Link> : null}
          </section>
          {openOrders ? <section className="start-orders" aria-label="项目开放工单"><header className="start-section-heading"><h3>返修跟进</h3><Link to="/capa">工单队列 <ChevronRight size={14} /></Link></header>{openOrders.length ? <ul>{openOrders.slice(0, 3).map((order) => <li key={order.work_order_id}><Link to={"/capa?workOrder=" + encodeURIComponent(order.work_order_id)}><span><strong>{order.image_name}</strong><small>{order.assignee || "未指派"} · {order.status}</small></span><ChevronRight size={15} /></Link></li>)}</ul> : <p className="start-note">当前没有开放工单。</p>}</section> : null}
        </section>
      </div>

      <details className="start-about" id="business-story"><summary>这张工作台如何支持项目交付</summary><p>把数据导入、标注复核、质量检查、返修版本与训练反馈留在同一项目中。Agent 组织任务，专业工具提供测量依据；整改和关键决定由具名人员确认。</p><div id="workflow"><Link to="/platform">操作指引</Link><Link to="/data-pools">数据版本</Link><Link to="/models">模型与 API</Link></div><p id="architecture">本地部署是数据边界设计；实际连接、外发与模型调用以当前配置和运行证据为准。</p><div id="review-proof"><Link to="/review">评审与证据</Link><Link to="/governance">治理边界</Link></div><p id="open-source">开放接口、依赖与许可说明可在 <Link to="/integrations">集成与扩展</Link> 查看。</p></details>
    </main>
    <footer className="start-home-footer"><span>工业视觉交付站</span><span>项目数据 · 具名复核 · 版本记录</span></footer>
  </div>;
}

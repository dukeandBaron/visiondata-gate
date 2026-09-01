import {
  Activity,
  ArrowRight,
  Bot,
  Command,
  FileCheck2,
  FileImage,
  GitBranch,
  KeyRound,
  Network,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  SquareKanban,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BrandMark } from "../components/BrandMark";
import {
  getProjectGovernanceEffectiveness,
  listAgentTasks,
  listOperatorImages,
  listOperatorWorkOrders,
} from "../data/api";
import { useProduct } from "../ProductContext";

const workflow = [
  ["01", "建立范围", "创建项目并导入自己的图片、目录或标注合同。"],
  ["02", "像素取证", "在 Canvas 上检查、框选、量测、比对与修订。"],
  ["03", "Agent 办事", "按需调度确定性工具，补证并交付建议与回执。"],
  ["04", "人工闭环", "具名复核、签发 CAPA，并追踪 Child Run 与血缘。"],
] as const;

const productMap = [
  { icon: FileImage, code: "WORK", title: "图像工作簿", detail: "真实导入、Canvas、标注账本、诊断探针", tone: "violet", route: "/workspace" },
  { icon: Bot, code: "AGENT", title: "任务与工作总览", detail: "任务理解、工具轨迹、干预与结果交付", tone: "cyan", route: "/command-center" },
  { icon: FileCheck2, code: "ACTION", title: "案件与 CAPA", detail: "从异常到具名工单，再到派生版本复验", tone: "coral", route: "/cases" },
  { icon: GitBranch, code: "TRACE", title: "证据、运行与血缘", detail: "SHA、Tool Receipt、Parent / Child 演进", tone: "lime", route: "/lineage" },
  { icon: Network, code: "SYSTEM", title: "集成与治理", detail: "Adapter SDK、授权来源、影子评测与发布门禁", tone: "amber", route: "/integrations" },
  { icon: KeyRound, code: "IDENTITY", title: "账户、会话与设置", detail: "本地身份、桌面会话、界面与数据边界", tone: "violet", route: "/account" },
] as const;

const reviewProofPaths = [
  { code: "Q4", icon: Bot, title: "Agent 能力链", detail: "任务理解、计划、工具、受治理记忆与结果交付", route: "/command-center", tone: "violet" },
  { code: "Q5", icon: GitBranch, title: "任务闭环", detail: "输入、发现、人工行动、CAPA 与 Child Run 复验", route: "/capa", tone: "cyan" },
  { code: "Q6·7", icon: FileImage, title: "真实产品体验", detail: "桌面工作簿、真实上传、Canvas 与可恢复反馈", route: "/workspace", tone: "lime" },
  { code: "Q10·11", icon: ShieldCheck, title: "安全与人在回路", detail: "本地数据边界、具名审批与生产权限隔离", route: "/governance", tone: "coral" },
  { code: "Q15", icon: FileCheck2, title: "解释与可执行交付", detail: "证据引用、SHA 回执与结构化工单", route: "/evidence", tone: "amber" },
] as const;

interface HomeProofState {
  loading: boolean;
  assets: number | null;
  tasks: number | null;
  runningTasks: number | null;
  completedTasks: number | null;
  humanQueue: number | null;
  openWorkOrders: number | null;
  governanceStatus: string;
  latestTaskStatus: string;
  unavailable: number;
}

const emptyHomeProof: HomeProofState = {
  loading: false,
  assets: null,
  tasks: null,
  runningTasks: null,
  completedTasks: null,
  humanQueue: null,
  openWorkOrders: null,
  governanceStatus: "NOT MEASURED",
  latestTaskStatus: "NO TASK",
  unavailable: 0,
};

function proofValue(value: number | null, suffix = ""): string {
  return value === null ? "UNAVAILABLE" : `${value}${suffix}`;
}

export function HomePage() {
  const navigate = useNavigate();
  const { connection, projects, activeProject, activeWorkspace, selectProject, workspaceLoading } = useProduct();
  const operationalProjects = projects.filter((project) => project.source_kind !== "synthetic_demo");
  const [proofRefreshToken, setProofRefreshToken] = useState(0);
  const [proof, setProof] = useState<HomeProofState>(emptyHomeProof);

  useEffect(() => {
    let active = true;
    const workspaceId = activeWorkspace?.workspace_id;
    const projectId = activeProject?.project_id;
    if (connection.api !== "CONNECTED" || !workspaceId || !projectId) {
      setProof(emptyHomeProof);
      return () => {
        active = false;
      };
    }
    setProof((current) => ({ ...current, loading: true }));
    void Promise.allSettled([
      listOperatorImages(workspaceId, projectId),
      listAgentTasks(workspaceId, projectId),
      listOperatorWorkOrders(workspaceId, projectId),
      getProjectGovernanceEffectiveness(projectId),
    ]).then(([assetResult, taskResult, orderResult, governanceResult]) => {
      if (!active) return;
      const assets = assetResult.status === "fulfilled" ? assetResult.value : undefined;
      const tasks = taskResult.status === "fulfilled" ? taskResult.value : undefined;
      const orders = orderResult.status === "fulfilled" ? orderResult.value : undefined;
      const governance = governanceResult.status === "fulfilled" ? governanceResult.value : undefined;
      setProof({
        loading: false,
        assets: assets?.length ?? null,
        tasks: tasks?.length ?? null,
        runningTasks: tasks
          ? tasks.filter((task) => ["CREATED", "RUNNING", "VERIFYING"].includes(task.execution_status)).length
          : null,
        completedTasks: tasks
          ? tasks.filter((task) => task.execution_status === "COMPLETED").length
          : null,
        humanQueue: tasks
          ? tasks.filter((task) => task.execution_status === "PLANNED" && task.plan_approval_required).length
          : null,
        openWorkOrders: orders
          ? orders.filter((order) => !["CLOSED", "REJECTED"].includes(order.status)).length
          : null,
        governanceStatus: governance?.measurement_status ?? "NOT MEASURED",
        latestTaskStatus: tasks?.[0]?.execution_status ?? "NO TASK",
        unavailable: [assetResult, taskResult, orderResult, governanceResult].filter((result) => result.status === "rejected").length,
      });
    });
    return () => {
      active = false;
    };
  }, [activeProject?.project_id, activeWorkspace?.workspace_id, connection.api, proofRefreshToken]);

  const openProject = (projectId: string) => {
    if (selectProject(projectId)) navigate("/workspace");
  };

  return (
    <div className="product-home product-home--v2">
      <header className="product-home__nav">
        <BrandMark />
        <nav aria-label="产品页面锚点">
          <a href="#product">产品</a>
          <a href="#proof">实时证明</a>
          <a href="#workflow">工作闭环</a>
          <a href="#review-proof">评审证据</a>
        </nav>
        <div>
          <span className="linear-api-state">
            <i className={`runtime-dot runtime-dot--${connection.api.toLowerCase()}`} />
            {connection.api === "CONNECTED" ? "Local API" : "API offline"}
          </span>
          <button className="home-nav-account" type="button" onClick={() => navigate("/account")}>账户</button>
          <button type="button" onClick={() => navigate("/workspace")}>打开工作台 <ArrowRight size={15} /></button>
        </div>
      </header>

      <main>
        <section className="home-hero-v2" id="product">
          <div className="home-hero-v2__copy">
            <span className="home-hero-v2__signal"><span>🚀</span> FROM PIXEL EVIDENCE TO GOVERNED ACTION</span>
            <h1>把像素证据<br />变成<span>可复验的行动</span></h1>
            <p>
              VisionData Gate 把真实数据输入、确定性检测、受控 Agent 计划、具名人工闸门与 Child Run 复验收进同一工作簿。
              不只给出建议，而是把一段工业数据治理流程办到底。
            </p>
            <div className="home-hero-v2__actions">
              <button type="button" onClick={() => navigate("/workspace")}>进入图像工作簿 <ArrowRight size={16} /></button>
              <button type="button" onClick={() => navigate("/command-center")}><Activity size={15} /> 查看工作总览</button>
            </div>
            <div className="home-trust-chips" aria-label="产品原则">
              <span>★ Local-first</span>
              <span>✦ Evidence-bound</span>
              <span>Human authority</span>
              <span>Raw outbound · 0</span>
            </div>

            {connection.api === "CONNECTED" ? (
              <div className="home-project-dock">
                <span><i /> {activeWorkspace?.name ?? "当前工作空间"}</span>
                {workspaceLoading ? <small>正在读取项目…</small> : null}
                {!workspaceLoading && operationalProjects.length === 0 ? <button type="button" onClick={() => navigate("/workspace")}>+ 创建第一个空项目</button> : null}
                {operationalProjects.slice(0, 3).map((project) => (
                  <button type="button" key={project.project_id} className={project.project_id === activeProject?.project_id ? "is-active" : ""} onClick={() => openProject(project.project_id)}>
                    <SquareKanban size={13} /> {project.name}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <div className="home-signal-stage" aria-label="工作闭环结构图">
            <div className="home-stage-grid" />
            <div className="home-stage-orbit home-stage-orbit--one" />
            <div className="home-stage-orbit home-stage-orbit--two" />
            <span className="home-stage-star home-stage-star--one">✦</span>
            <span className="home-stage-star home-stage-star--two">★</span>
            <div className="home-stage-node home-stage-node--asset"><FileImage size={15} /><span>ASSET</span><strong>real input</strong></div>
            <div className="home-stage-node home-stage-node--tool"><Zap size={15} /><span>TOOL</span><strong>deterministic</strong></div>
            <div className="home-stage-node home-stage-node--human"><ShieldCheck size={15} /><span>HUMAN</span><strong>authority</strong></div>

            <div className="home-stage-core">
              <header><span><i /> IMAGE WORKBOOK</span><small>LIVE CONTEXT</small></header>
              <div className="home-stage-canvas">
                <div className="home-stage-part"><span /><span /><span /><span /><i /></div>
                <div className="home-stage-defect"><b>01</b><small>inspection region</small></div>
                <span className="home-stage-axis home-stage-axis--x" />
                <span className="home-stage-axis home-stage-axis--y" />
              </div>
              <footer><span>SHA bound</span><span>revision 01</span><strong>ready for action</strong></footer>
            </div>

            <div className="home-stage-trace">
              <header><Bot size={14} /> AGENT TRACE <i /></header>
              <p><span>01</span>读取当前资产与治理范围</p>
              <p><span>02</span>调用确定性视觉探针</p>
              <p className="is-highlight"><span>03</span>等待人工复核后生成工单</p>
            </div>
            <div className="home-stage-verdict"><span>GATE</span><strong>HUMAN REVIEW</strong><i /></div>
          </div>
        </section>

        <section className="home-marquee" aria-label="完整产品域">
          <span>IMAGE WORKBOOK</span><i>✦</i><span>AGENT TASKS</span><i>✦</i><span>EVIDENCE</span><i>✦</i><span>CAPA</span><i>✦</i><span>LINEAGE</span><i>✦</i><span>GOVERNANCE</span>
        </section>

        <section className="home-live-proof" id="proof">
          <header>
            <div>
              <span><Activity size={14} /> LIVE PRODUCT PROOF</span>
              <h2>问题真实、能力真实、闭环真实</h2>
              <p>这里不播放预设结论；数字来自当前项目的本机 API，读不到时就明确显示不可用。</p>
            </div>
            <button type="button" onClick={() => setProofRefreshToken((value) => value + 1)} disabled={proof.loading || connection.api !== "CONNECTED"}>
              <RefreshCw className={proof.loading ? "is-spinning" : ""} size={14} /> {proof.loading ? "正在核对" : "刷新事实"}
            </button>
          </header>

          <div className="home-live-proof__grid">
            <article className="is-problem">
              <header><span>01 / PROBLEM</span><FileImage size={17} /></header>
              <div><small>当前真实输入</small><strong>{proofValue(proof.assets, " ASSETS")}</strong><p>{activeProject ? `${activeProject.name} · ${activeProject.source_kind}` : "选择项目后读取工作簿资产"}</p></div>
              <ul><li><i />真实上传与本地授权范围</li><li><i />原图外发始终为 0</li></ul>
              <button type="button" onClick={() => navigate("/workspace")}>进入像素现场 <ArrowRight size={14} /></button>
            </article>

            <article className="is-capability">
              <header><span>02 / CAPABILITY</span><Bot size={17} /></header>
              <div><small>受控 Agent 任务</small><strong>{proofValue(proof.tasks, " TASKS")}</strong><p>latest · {proof.latestTaskStatus}</p></div>
              <ul><li><i />{proofValue(proof.runningTasks)} 运行中 · {proofValue(proof.humanQueue)} 待计划审批</li><li><i />Goal 2 / Goal 3 回执按真实任务展开</li></ul>
              <button type="button" onClick={() => navigate("/command-center")}>查看计划与工具回执 <ArrowRight size={14} /></button>
            </article>

            <article className="is-loop">
              <header><span>03 / OUTCOME</span><GitBranch size={17} /></header>
              <div><small>可验证结果</small><strong>{proofValue(proof.completedTasks, " SEALED")}</strong><p>governance · {proof.governanceStatus}</p></div>
              <ul><li><i />{proofValue(proof.openWorkOrders)} 开放工单</li><li><i />Parent → CAPA → Child Run 血缘</li></ul>
              <button type="button" onClick={() => navigate("/review")}>打开只读证明路径 <ArrowRight size={14} /></button>
            </article>
          </div>

          <footer>
            <span><i className={`runtime-dot runtime-dot--${connection.api.toLowerCase()}`} /> {connection.api === "CONNECTED" ? "LIVE LOCAL API" : "NOT CONNECTED"}</span>
            <span>{activeWorkspace?.name ?? "NO WORKSPACE"} / {activeProject?.name ?? "NO PROJECT"}</span>
            <span>{proof.unavailable ? `${proof.unavailable} VIEW(S) UNAVAILABLE` : "NO SILENT FALLBACK"}</span>
          </footer>
        </section>

        <section className="home-product-frame home-product-frame--v2" aria-label="桌面工作台结构预览">
          <aside>
            <div className="home-frame-logo">V</div>
            <span><Command size={13} /> Search <kbd>⌘K</kbd></span>
            <strong>WORK</strong>
            <span className="is-active"><FileImage size={13} /> Image workbook</span>
            <span><SquareKanban size={13} /> CAPA work orders</span>
            <strong>TRACE</strong>
            <span><GitBranch size={13} /> Evidence lineage</span>
            <strong>SYSTEM</strong>
            <span><Network size={13} /> Integrations</span>
          </aside>
          <div className="home-frame-main">
            <header><span>Vision Lab</span><span>Project</span><b>Image workbook</b><em>LOCAL API ●</em></header>
            <div className="home-frame-workbook home-frame-workbook--live">
              <section>
                <small>ASSETS · USER INPUT</small>
                <div className="home-frame-asset is-active"><i /> Current image <span>REVIEW</span></div>
                <div className="home-frame-asset"><i /> Asset 02 <span>READY</span></div>
                <div className="home-frame-asset"><i /> Asset 03 <span>NEW</span></div>
              </section>
              <article>
                <div className="home-frame-canvas-object"><span /><span /><span /><span /><i /></div>
                <div className="home-frame-bbox"><b>gear-tooth-defect</b></div>
                <span className="home-frame-probe">gradient profile · Shift drag</span>
              </article>
              <section>
                <small>INSPECTOR / AGENT</small>
                <dl><div><dt>Edge energy</dt><dd>measured</dd></div><div><dt>Annotation</dt><dd>revision bound</dd></div><div><dt>Evidence</dt><dd>SHA linked</dd></div></dl>
                <div className="home-frame-agent"><Bot size={13} /><p>Agent 只在操作者触发后运行，并把工具回执绑定到当前工作对象。</p></div>
              </section>
            </div>
          </div>
        </section>

        <section className="home-capability-map" id="architecture">
          <header><span><Sparkles size={14} /> COMPLETE PRODUCT, NOT A SINGLE TOOL</span><h2>从工作对象到系统治理，形成完整产品面</h2><p>工作台只是核心入口；账户、集成、治理、评审与开放复用共同组成可落地工程。</p></header>
          <div>
            {productMap.map((item, index) => (
              <button type="button" key={item.code} className={`is-${item.tone}${index === 0 ? " is-featured" : ""}`} onClick={() => navigate(item.route)}>
                <span className="home-capability-map__index">0{index + 1}</span>
                <span className="home-capability-map__icon"><item.icon size={20} /></span>
                <small>{item.code}</small><strong>{item.title}</strong><p>{item.detail}</p><ArrowRight size={15} />
              </button>
            ))}
          </div>
        </section>

        <section className="home-workflow-v2" id="workflow">
          <header><span>ONE OPERATIONAL LOOP</span><h2>Agent 不只“回答”，而是承担一段流程</h2><p>陌生输入、工具失败与人工责任边界都必须留在同一条可回放路径中。</p></header>
          <div className="home-workflow-track">
            {workflow.map(([index, title, detail]) => <article key={index}><span>{index}</span><i /><h3>{title}</h3><p>{detail}</p></article>)}
          </div>
          <div className="home-workflow-outcome">
            <span>INPUT</span><ArrowRight size={14} /><strong>证据驱动的 Agent 执行</strong><ArrowRight size={14} /><span>HUMAN GATE</span><ArrowRight size={14} /><strong>VERIFIED OUTCOME</strong>
          </div>
        </section>

        <section className="home-review-proof" id="review-proof">
          <header>
            <span><FileCheck2 size={14} /> REVIEWABLE BY DESIGN</span>
            <h2>每个评审问题，都能落到一个可操作页面</h2>
            <p>评分细则不是额外包装，而是产品真实工作路径的索引。点击即可进入对应证据现场。</p>
          </header>
          <div>
            {reviewProofPaths.map((item) => (
              <button type="button" className={`is-${item.tone}`} key={item.code} onClick={() => navigate(item.route)}>
                <span>{item.code}</span><item.icon size={18} /><strong>{item.title}</strong><p>{item.detail}</p><ArrowRight size={14} />
              </button>
            ))}
          </div>
          <footer>
            <span>★ HUMAN-IN-THE-LOOP</span>
            <span>✦ FAIL-CLOSED</span>
            <span>✦ EVIDENCE-BOUND</span>
            <span>PRODUCTION RELEASE · FALSE</span>
          </footer>
        </section>

        <section className="home-open-source" id="open-source">
          <div>
            <span><PackageCheck size={15} /> OPEN & REUSABLE</span>
            <h2>可以审计，也可以继续扩展</h2>
            <p>项目代码采用 Apache-2.0；依赖以 CycloneDX 1.6 SBOM 记录；工业格式与外部工具通过 Adapter SDK 和显式合同扩展。</p>
            <button type="button" onClick={() => navigate("/integrations")}>查看集成合同 <ArrowRight size={15} /></button>
          </div>
          <ul>
            <li><strong>Apache-2.0</strong><span>代码与复用边界清晰</span></li>
            <li><strong>CycloneDX 1.6</strong><span>依赖与许可证可审计</span></li>
            <li><strong>Adapter SDK</strong><span>格式、工具与生态扩展面</span></li>
            <li><strong>Local-first</strong><span>原图与工作上下文留在本机</span></li>
          </ul>
        </section>

        <section className="home-final-cta home-final-cta--v2">
          <span>★ READY FOR REAL WORK</span>
          <h2>从你的数据开始，而不是从预设结论开始</h2>
          <p>建立项目、导入数据集、进入像素现场，再让 Agent 为证据和行动服务。</p>
          <div><button type="button" onClick={() => navigate("/workspace")}>打开 VisionData Gate <ArrowRight size={16} /></button><button type="button" onClick={() => navigate("/settings")}>配置本机环境</button></div>
        </section>
      </main>

      <footer className="product-home__footer">
        <span>VisionData Gate · Industrial data release workspace</span>
        <span>Apache-2.0 · Local-first · Human authority</span>
      </footer>
    </div>
  );
}

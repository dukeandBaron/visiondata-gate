import {
  ArrowRight,
  BadgeCheck,
  Braces,
  CircleOff,
  ExternalLink,
  LockKeyhole,
  RefreshCw,
  ScanLine,
  Workflow,
} from "lucide-react";
import { Link } from "react-router-dom";
import { BrandMark } from "../components/BrandMark";
import {
  usePublicReplayManifest,
  type PublicReplayManifest,
} from "../publicReplay";

const publicRepositoryUrl =
  "https://github.com/dukeandBaron/visiondata-gate";
const runningGuideUrl = `${publicRepositoryUrl}/blob/main/docs/quickstart.md`;

const workbenchSurfaces = [
  {
    index: "01",
    title: "证据取证",
    description: "查看图像、标注、元数据测点与来源摘要",
    href: "/evidence",
  },
  {
    index: "02",
    title: "动态调查",
    description: "跟踪 Worker 选择、补证原因、预算与工具状态",
    href: "/command-center",
  },
  {
    index: "03",
    title: "案件审阅",
    description: "检查竞争假设、缺失证据与下一安全动作",
    href: "/cases",
  },
  {
    index: "04",
    title: "人工 CAPA",
    description: "让具名人员审批整改，保留 Agent 权限边界",
    href: "/capa",
  },
  {
    index: "05",
    title: "血缘复验",
    description: "追踪 Parent、Human、Derived 与 Child Run",
    href: "/lineage",
  },
  {
    index: "06",
    title: "治理边界",
    description: "区分公开回放、私域验证与尚未取得的工厂证据",
    href: "/governance",
  },
] as const;

function compactDigest(value: string): string {
  return `${value.slice(0, 14)}…${value.slice(-12)}`;
}

function IntegrityDossier({ manifest }: { manifest: PublicReplayManifest }) {
  return (
    <aside className="facade-dossier" aria-label="公开案件完整性摘要">
      <header className="facade-dossier__header">
        <span>CASE / {manifest.case.case_id}</span>
        <strong><BadgeCheck size={15} /> MANIFEST SELF-CHECK VERIFIED</strong>
      </header>
      <div className="facade-dossier__subject">
        <small>PUBLIC EVIDENCE FILE</small>
        <h2>{manifest.case.title}</h2>
        <p>{manifest.case.dataset} · {manifest.case.input_scope}</p>
      </div>
      <dl className="facade-dossier__facts">
        <div><dt>FIRST GATE</dt><dd data-tone="hold">{manifest.case.initial_disposition}</dd></div>
        <div><dt>WORKER BUDGET</dt><dd>{manifest.worker_selection.budget.selected}/{manifest.worker_selection.budget.maximum}</dd></div>
        <div><dt>MODEL CALLS</dt><dd>{manifest.worker_selection.budget.model_call_count}</dd></div>
        <div><dt>PRODUCTION</dt><dd data-tone="danger">FALSE</dd></div>
      </dl>
      <div className="facade-dossier__trace" aria-label="六阶段运行状态">
        {manifest.phases.map((phase, index) => (
          <span key={phase.id} title={`${phase.label}: ${phase.state}`}>
            <i>{String(index + 1).padStart(2, "0")}</i>
            <b>{phase.label}</b>
          </span>
        ))}
      </div>
      <footer className="facade-dossier__digest">
        <span>JCS SHA-256</span>
        <code title={manifest.manifest_sha256}>{compactDigest(manifest.manifest_sha256)}</code>
      </footer>
    </aside>
  );
}

function IntegrityUnavailable({
  failedReason,
  onRetry,
}: {
  failedReason?: string;
  onRetry: () => void;
}) {
  return (
    <aside className={`facade-dossier facade-dossier--pending${failedReason ? " is-failed" : ""}`} aria-live="polite">
      <header className="facade-dossier__header">
        <span>PUBLIC EVIDENCE FILE</span>
        <strong>{failedReason ? <CircleOff size={15} /> : <ScanLine size={15} />}{failedReason ? "FAIL CLOSED" : "VERIFYING"}</strong>
      </header>
      <div className="facade-dossier__unavailable">
        <Braces size={28} />
        <h2>{failedReason ? "公开清单未通过完整性核验" : "正在复算 JCS SHA-256"}</h2>
        <p>{failedReason ?? "任何案件数字都要等摘要一致后才显示。"}</p>
        {failedReason ? (
          <button type="button" className="facade-dossier__retry" onClick={onRetry}>
            <RefreshCw size={15} /> 重新加载并核验
          </button>
        ) : null}
      </div>
      <footer className="facade-dossier__digest">
        <span>DISPLAY POLICY</span>
        <code>NO VERIFIED FACTS · NO PASS</code>
      </footer>
    </aside>
  );
}

export function PublicLandingPage() {
  const state = usePublicReplayManifest();
  const manifest = state.status === "VERIFIED" ? state.manifest : undefined;

  return (
    <div className="public-facade">
      <a className="facade-skip" href="#facade-main">跳到主要内容</a>
      <header className="facade-nav">
        <Link className="facade-nav__brand" to="/" aria-label="VisionData Gate 公开首页">
          <BrandMark />
        </Link>
        <nav aria-label="公开项目导航">
          <a href="#capabilities">产品能力</a>
          <a href="#workflow">任务闭环</a>
          <a href="#boundary">验证边界</a>
        </nav>
        <Link className="facade-nav__workbench" to="/command-center">
          查看只读回放 <ArrowRight size={15} />
        </Link>
      </header>

      <main id="facade-main">
        <section className="facade-hero" aria-labelledby="facade-title">
          <div className="facade-hero__copy">
            <div className="facade-eyebrow">
              <span>LOCAL-FIRST · INDUSTRIAL VISION GOVERNANCE</span>
              <i />
              <span>EVIDENCE · CAPA · RECHECK</span>
            </div>
            <h1 id="facade-title">
              让工业视觉 Agent<br />
              <em>把异常办到可复验</em>
            </h1>
            <p>
              VisionData Gate 把图像、标注、批次、工艺与视觉方案组织成一个版本化案件。
              确定性工具先测量，Agent 只在证据改变下一步时补证；高风险决定交给具名人员，
              整改后由 Child Run 独立复验。
            </p>
            <div className="facade-hero__actions">
              <a href={runningGuideUrl} target="_blank" rel="noreferrer">
                启动真实本地工作台 <ExternalLink size={14} />
              </a>
              <Link to="/command-center">
                查看只读回放 <ArrowRight size={16} />
              </Link>
              <a href={publicRepositoryUrl} target="_blank" rel="noreferrer">
                查看源码 <ExternalLink size={14} />
              </a>
            </div>
            <div className="facade-validation-ledger" aria-label="公开与私有验证边界">
              <article>
                <span>PRIVATE_OFFLINE_VALIDATION</span>
                <strong>私有工业数据只留在本地工作台</strong>
                <small>本地部署路径不等于本页已经取得客户验收或工厂真值。</small>
              </article>
              <article>
                <span>PUBLIC_SYNTHETIC_REPLAY</span>
                <strong>公开页只回放 SHA 绑定合成案件</strong>
                <small>访客可以检查编排、测点和闭环结构；浏览器不连接后端。</small>
              </article>
              <p><b>NO_FACTORY_TRUTH</b> 当前没有厂级双人裁决真值，因此不声明真实工厂误放行率或生产 PASS。</p>
            </div>
            <div className="facade-mode-strip" role="note">
              <span>PUBLIC SYNTHETIC REPLAY</span>
              <b>只读</b>
              <b>无后端</b>
              <b>无客户数据</b>
              <b>无 API Key</b>
              <strong>production_release_allowed=false</strong>
            </div>
          </div>
          {manifest ? (
            <IntegrityDossier manifest={manifest} />
          ) : (
            <IntegrityUnavailable
              failedReason={state.status === "FAILED" ? state.reason : undefined}
              onRetry={state.retry}
            />
          )}
        </section>

        <section className="facade-problem" id="capabilities" aria-labelledby="problem-title">
          <header className="facade-section-heading">
            <span>01 / REAL PROBLEM</span>
            <h2 id="problem-title">现场缺的不是又一张报表，而是一段能追责的处理流程</h2>
          </header>
          <div className="facade-problem__rows">
            <article>
              <strong>证据分散</strong>
              <p>图像、标注、metadata、批次、工单和工艺记录无法回到同一案件版本。</p>
              <span>统一来源、合同、版本与摘要</span>
            </article>
            <article>
              <strong>解释竞争</strong>
              <p>采集漂移、泄漏、标注偏移和工艺变化可能同时成立，固定流程无法预写调查路径。</p>
              <span>竞争假设 + 证据触发补证</span>
            </article>
            <article>
              <strong>整改断链</strong>
              <p>finding 变少不等于责任关闭，更不等于根因成立或生产可以放行。</p>
              <span>Parent / Human / Derived / Child</span>
            </article>
          </div>
        </section>

        <section className="facade-workflow" id="workflow" aria-labelledby="workflow-title">
          <header className="facade-section-heading">
            <span>02 / AGENT AT WORK</span>
            <h2 id="workflow-title">不是“给建议”，而是受控地推进一个案件</h2>
          </header>
          <div className="facade-gate-spine">
            {(manifest?.lineage ?? [
              { id: "parent", label: "Parent case", state: "WAITING_FOR_VERIFIED_MANIFEST" },
              { id: "human", label: "Named human gate", state: "REQUIRED" },
              { id: "derived", label: "Private derived version", state: "ISOLATED" },
              { id: "child", label: "Child same-contract run", state: "INDEPENDENT_RECHECK" },
            ]).map((item, index) => (
              <article key={item.id}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <small>{item.id.toUpperCase()}</small>
                  <strong>{item.label}</strong>
                </div>
                <code>{item.state}</code>
              </article>
            ))}
          </div>
          <aside className="facade-workflow__rule">
            <LockKeyhole size={20} />
            <div>
              <strong>人工权限不是提示语，而是执行断点</strong>
              <p>Agent 可以调查、解释和建议；不能确立根因、批准 CAPA、控制设备或放行生产。</p>
            </div>
          </aside>
        </section>

        <section className="facade-proof" id="proof" aria-labelledby="proof-title">
          <header className="facade-section-heading">
            <span>03 / OPERATOR WORKBENCH</span>
            <h2 id="proof-title">从证据发现到 Child Run 复验，每一步都能进入</h2>
          </header>
          <div className="facade-score-ledger">
            {workbenchSurfaces.map((surface) => (
              <Link key={surface.title} to={surface.href}>
                <>
                  <b>{surface.index}</b>
                  <strong>{surface.title}</strong>
                  <span>{surface.description}</span>
                  <ArrowRight size={15} />
                </>
              </Link>
            ))}
          </div>
        </section>

        <section className="facade-boundary" id="boundary" aria-labelledby="boundary-title">
          <header className="facade-section-heading">
            <span>04 / TRUTH BOUNDARY</span>
            <h2 id="boundary-title">可证明的明确写出；还没有的保持未完成</h2>
          </header>
          <div className="facade-boundary__grid">
            <div className="facade-boundary__state">
              <article><span>SOURCE MODE</span><strong>PUBLIC_SYNTHETIC_REPLAY</strong></article>
              <article><span>BACKEND</span><strong>NOT CONNECTED</strong></article>
              <article><span>CUSTOMER DATA</span><strong>NOT INCLUDED</strong></article>
              <article><span>PRODUCTION</span><strong>FALSE</strong></article>
            </div>
            <div className="facade-boundary__missing">
              <header><Workflow size={17} /><strong>仍缺少的外部证据</strong></header>
              <ul>
                {(manifest?.missing_evidence ?? ["等待公开清单完整性核验"]).map((item) => <li key={item}>{item}</li>)}
              </ul>
              <p>公开回放不替代客户验收、工厂 shadow test、生产 IAM 或专业人员最终判断。</p>
            </div>
          </div>
        </section>

        <section className="facade-final-cta">
          <div>
            <span>TRACE THE EVIDENCE. CONTROL THE DECISION.</span>
            <h2>从一个冻结合成案件开始，检查工具、Worker、人工门禁与独立复验</h2>
          </div>
          <Link to="/command-center">查看公开只读回放 <ArrowRight size={17} /></Link>
        </section>
      </main>

      <footer className="facade-footer">
        <div><BrandMark /><span>Evidence-governed industrial vision release</span></div>
        <nav aria-label="公开法律与安全链接">
          <a href={`${publicRepositoryUrl}/blob/main/LICENSE`} target="_blank" rel="noreferrer">Apache-2.0</a>
          <a href={`${publicRepositoryUrl}/blob/main/SECURITY.md`} target="_blank" rel="noreferrer">安全策略</a>
          <a href={`${publicRepositoryUrl}/blob/main/docs/compliance.md`} target="_blank" rel="noreferrer">隐私边界</a>
          <Link to="/review">Evidence review</Link>
        </nav>
      </footer>
    </div>
  );
}

import {
  ArrowRight,
  BadgeCheck,
  Braces,
  CircleOff,
  Download,
  ExternalLink,
  FileCheck2,
  GitBranch,
  LockKeyhole,
  ScanLine,
  Workflow,
} from "lucide-react";
import { Link } from "react-router-dom";
import { BrandMark } from "../components/BrandMark";
import {
  publicReplayManifestUrl,
  usePublicReplayManifest,
  type PublicReplayManifest,
} from "../publicReplay";

const publicRepositoryUrl =
  "https://github.com/dukeandBaron/visiondata-gate-public";
const publicDocsUrl = `${publicRepositoryUrl}/tree/main/docs`;

const scoreRows = [
  {
    weight: "25%",
    title: "行业场景价值",
    proof: "多源工业视觉证据、目标用户、影子评测合同与迁移梯度",
    href: `${publicRepositoryUrl}/blob/main/docs/INDUSTRY_SCENARIO_VALUE.md`,
  },
  {
    weight: "25%",
    title: "Agent 任务闭环",
    proof: "Intake → Planner → Tool → Judge → CAPA → Child Run",
    href: `${publicRepositoryUrl}/blob/main/docs/AGENT_RUNTIME.md`,
  },
  {
    weight: "20%",
    title: "产品与 Demo",
    proof: "可交互多页面工作台、独立静态清单读取、错误与缺失状态失败关闭",
    href: "/command-center",
    internal: true,
  },
  {
    weight: "15%",
    title: "技术实现",
    proof: "typed kernel、确定性工具、动态补证、JCS / SHA-256 证据绑定",
    href: `${publicRepositoryUrl}/blob/main/docs/BOUNDLESS_AGENTS_TECHNICAL_ROUTE.md`,
  },
  {
    weight: "10%",
    title: "安全与可追溯",
    proof: "只读来源、具名人工权限、私有派生整改、production=false",
    href: `${publicRepositoryUrl}/blob/main/docs/PUBLICATION_BOUNDARY.md`,
  },
  {
    weight: "5%",
    title: "开放与复用",
    proof: "Apache-2.0、SBOM、Schema、Rule Pack、Adapter 与示例数据",
    href: `${publicRepositoryUrl}/blob/main/docs/OPEN_REUSE_CONTRACTS.md`,
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

function IntegrityUnavailable({ failedReason }: { failedReason?: string }) {
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
          <a href="#workflow">任务闭环</a>
          <a href="#proof">评审证据</a>
          <a href="#boundary">公开边界</a>
        </nav>
        <Link className="facade-nav__workbench" to="/command-center">
          打开工作台 <ArrowRight size={15} />
        </Link>
      </header>

      <main id="facade-main">
        <section className="facade-hero" aria-labelledby="facade-title">
          <div className="facade-hero__copy">
            <div className="facade-eyebrow">
              <span>GOAI 2026 · 复赛</span>
              <i />
              <span>第 03 队 · AI + 其他 / 工业视觉</span>
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
              <Link to="/command-center">
                进入已核验合成工作台 <ArrowRight size={16} />
              </Link>
              <Link to="/review">按评分项查看证据</Link>
              <a href={publicRepositoryUrl} target="_blank" rel="noreferrer">
                查看源码 <ExternalLink size={14} />
              </a>
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
            <IntegrityUnavailable failedReason={state.status === "FAILED" ? state.reason : undefined} />
          )}
        </section>

        <section className="facade-problem" aria-labelledby="problem-title">
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
            <span>03 / REVIEWER PROOF MAP</span>
            <h2 id="proof-title">沿着评分表取证，不靠口号拿分</h2>
          </header>
          <div className="facade-score-ledger">
            {scoreRows.map((row) => {
              const content = (
                <>
                  <b>{row.weight}</b>
                  <strong>{row.title}</strong>
                  <span>{row.proof}</span>
                  <ArrowRight size={15} />
                </>
              );
              return "internal" in row && row.internal ? (
                <Link key={row.title} to={row.href}>{content}</Link>
              ) : (
                <a key={row.title} href={row.href} target="_blank" rel="noreferrer">{content}</a>
              );
            })}
          </div>
          <div className="facade-proof__actions">
            <Link to="/review"><FileCheck2 size={16} /> 打开评审证据索引</Link>
            <a href={publicDocsUrl} target="_blank" rel="noreferrer"><GitBranch size={16} /> 浏览公开文档</a>
            <a href={publicReplayManifestUrl} download><Download size={16} /> 下载回放清单</a>
          </div>
        </section>

        <section className="facade-boundary" id="boundary" aria-labelledby="boundary-title">
          <header className="facade-section-heading">
            <span>04 / TRUTH BOUNDARY</span>
            <h2 id="boundary-title">可证明的明确写出；还没有的保持未完成</h2>
          </header>
          <div className="facade-boundary__grid">
            <div className="facade-boundary__state">
              <article><span>FROZEN RC3 BASELINE</span><strong>{manifest?.release_status.local_candidate ?? "VERIFYING"}</strong></article>
              <article><span>OFFICIAL SUBMISSION</span><strong>{manifest?.release_status.official_submission ?? "PENDING"}</strong></article>
              <article><span>OFFICIAL EVALUATION</span><strong>{manifest?.release_status.official_evaluation ?? "NOT_EVALUATED"}</strong></article>
              <article><span>PRODUCTION RELEASE</span><strong>FALSE</strong></article>
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
            <span>READ THE EVIDENCE. REPLAY THE CASE.</span>
            <h2>用 60 秒看清输入、Agent、工具、异常处理与复验</h2>
          </div>
          <Link to="/command-center">打开公开工作台 <ArrowRight size={17} /></Link>
        </section>
      </main>

      <footer className="facade-footer">
        <div><BrandMark /><span>Evidence-governed industrial vision release</span></div>
        <nav aria-label="公开法律与安全链接">
          <a href={`${publicRepositoryUrl}/blob/main/LICENSE`} target="_blank" rel="noreferrer">Apache-2.0</a>
          <a href={`${publicRepositoryUrl}/blob/main/SECURITY.md`} target="_blank" rel="noreferrer">安全策略</a>
          <a href={`${publicRepositoryUrl}/blob/main/docs/PUBLICATION_BOUNDARY.md`} target="_blank" rel="noreferrer">隐私边界</a>
        </nav>
      </footer>
    </div>
  );
}

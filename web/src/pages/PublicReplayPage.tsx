import {
  BadgeCheck,
  Braces,
  BriefcaseBusiness,
  CheckCircle2,
  CircleOff,
  Database,
  Eye,
  FileDown,
  KeyRound,
  LockKeyhole,
  Network,
  ScanSearch,
  UserRoundX,
  Workflow,
} from "lucide-react";
import { Link } from "react-router-dom";
import { InspectionCanvas } from "../components/visuals";
import {
  ClaimBoundary,
  DetailRow,
  Digest,
  EmptyState,
  LockedAction,
  Metric,
  PageIntro,
  Panel,
  PanelHeader,
  StatusBadge,
} from "../components/ui";
import { cases } from "../data/fixtures";
import {
  publicReplayManifestUrl,
  usePublicReplayManifest,
  type PublicReplayManifest,
} from "../publicReplay";

export type PublicReplayView =
  | "workspace"
  | "command-center"
  | "cases"
  | "case-detail"
  | "evidence"
  | "capa"
  | "lineage"
  | "runs"
  | "integrations"
  | "governance"
  | "review"
  | "account"
  | "settings";

const viewCopy: Record<
  PublicReplayView,
  { eyebrow: string; title: string; description: string }
> = {
  workspace: {
    eyebrow: "PUBLIC EVIDENCE LAB",
    title: "合成视觉取证工作簿",
    description: "使用固定合成测量展示图像、阈值、异常区域与责任边界；不加载用户文件。",
  },
  "command-center": {
    eyebrow: "PUBLIC CONTROL PLANE",
    title: "证据驱动调查总览",
    description: "把触发证据、Worker 选择、冻结预算、竞争假设和失败关闭裁决放在同一工作台。",
  },
  cases: {
    eyebrow: "PUBLIC CASE INBOX",
    title: "脱敏案件收件箱",
    description: "只包含一个冻结合成案件，不读取本地数据库，也不静默替代真实案件。",
  },
  "case-detail": {
    eyebrow: "PUBLIC CASE WORKBENCH",
    title: "合成冲突案件",
    description: "从首次 RECAPTURE 到人工闸门要求、派生副本和 Child 同合同复验。",
  },
  evidence: {
    eyebrow: "PUBLIC EVIDENCE",
    title: "触发证据与测点",
    description: "每个 Worker 选择都必须回到确定性测点；缺失的工厂证据保持缺失。",
  },
  capa: {
    eyebrow: "PUBLIC CAPA",
    title: "闭环结构回放",
    description: "演示 Parent → Human → Derived → Child，不提供审批、执行或生产放行写操作。",
  },
  lineage: {
    eyebrow: "PUBLIC PROVENANCE",
    title: "父子案件血缘",
    description: "版本、人工闸门和复验结果按顺序绑定；PASS_LOCAL 不会升级为生产放行。",
  },
  runs: {
    eyebrow: "PUBLIC AGENT TRACE",
    title: "六阶段状态与预算快照",
    description: "展示受控编排的可观察事实，不展示或伪造模型私有思维链。",
  },
  integrations: {
    eyebrow: "PUBLIC INTEGRATION CONTRACTS",
    title: "生态兼容边界",
    description: "公开页只说明接口合同；未连接任何客户系统、模型网关或工厂设备。",
  },
  governance: {
    eyebrow: "PUBLIC GOVERNANCE",
    title: "安全、合规与发布边界",
    description: "把当前可声明、不可声明和仍待外部完成的门禁分开呈现。",
  },
  review: {
    eyebrow: "PUBLIC REVIEW PACK",
    title: "评审证据索引",
    description: "评分项只链接可公开材料与合成回放，不把页面文案当成测试回执。",
  },
  account: {
    eyebrow: "PUBLIC SESSION",
    title: "无账户、无身份收集",
    description: "GitHub Pages 不建立用户账户、不保存 API Key，也不创建跨用户工作空间。",
  },
  settings: {
    eyebrow: "PUBLIC RUNTIME SETTINGS",
    title: "静态回放配置",
    description: "公开模式在构建期锁定；所有外部连接和写操作均保持关闭。",
  },
};

function PublicManifestGate({
  manifest,
}: {
  manifest: PublicReplayManifest;
}) {
  return (
    <div className="public-replay-integrity" role="status">
      <span><BadgeCheck size={15} /> JCS SHA-256 VERIFIED</span>
      <code>{manifest.manifest_sha256}</code>
      <a href={publicReplayManifestUrl} download>
        <FileDown size={14} /> 下载公开回放清单
      </a>
    </div>
  );
}

function CommandCenter({ manifest }: { manifest: PublicReplayManifest }) {
  const budget = manifest.worker_selection.budget;
  return (
    <>
      <div className="metric-grid metric-grid--four">
        <Metric label="来源模式" value="PUBLIC" detail="synthetic replay" tone="info" icon={Eye} />
        <Metric label="Worker 预算" value={`${budget.selected}/${budget.maximum}`} detail="evidence selected" tone="warning" icon={Workflow} />
        <Metric label="模型调用" value={String(budget.model_call_count)} detail="deterministic only" tone="success" icon={Braces} />
        <Metric label="生产放行" value="FALSE" detail="hard boundary" tone="danger" icon={LockKeyhole} />
      </div>

      <Panel variant="raised">
        <PanelHeader
          eyebrow="INCIDENT KERNEL V6"
          title="六阶段受控生命周期"
          detail="阶段状态来自已验 SHA 的公开清单，不从页面文字推断。"
          actions={<StatusBadge tone="info">PUBLIC REPLAY</StatusBadge>}
        />
        <div className="public-phase-rail">
          {manifest.phases.map((phase, index) => (
            <article key={phase.id}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div><strong>{phase.label}</strong><small>{phase.state}</small></div>
            </article>
          ))}
        </div>
      </Panel>

      <div className="public-replay-grid">
        <Panel>
          <PanelHeader eyebrow="WORKER SELECTION" title="为什么选、为什么不选" detail="预算和触发证据同时可见。" />
          <div className="public-worker-list">
            {manifest.worker_selection.selected.map((item) => (
              <article key={item.worker} className="is-selected">
                <CheckCircle2 size={16} />
                <div><strong>{item.worker}</strong><p>{item.reason}</p><code>{item.triggering_evidence_id}</code></div>
              </article>
            ))}
            {manifest.worker_selection.rejected.map((item) => (
              <article key={item.worker} className="is-rejected">
                <CircleOff size={16} />
                <div><strong>{item.worker}</strong><p>{item.reason}</p></div>
              </article>
            ))}
          </div>
        </Panel>
        <Panel>
          <PanelHeader eyebrow="BELIEF LEDGER" title="竞争假设" detail="证据支持不等于根因确立。" />
          <div className="public-hypothesis-list">
            {manifest.competing_hypotheses.map((item) => (
              <article key={item.id}>
                <span>{item.id}</span>
                <div><strong>{item.statement}</strong><small>{item.state}</small></div>
              </article>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}

function Workspace({ manifest }: { manifest: PublicReplayManifest }) {
  const syntheticCase = cases.find((item) => item.id === "synthetic-v3");
  return (
    <div className="public-workspace-grid">
      <Panel variant="raised">
        <PanelHeader
          eyebrow="SYNTHETIC INSTRUMENT"
          title="固定视觉测量"
          detail="画布使用嵌入式合成图形，不包含任何工厂或个人图像。"
          actions={<StatusBadge tone="info">READ ONLY</StatusBadge>}
        />
        <InspectionCanvas caseRecord={syntheticCase} />
      </Panel>
      <Panel>
        <PanelHeader eyebrow="MEASUREMENT CONTRACT" title="异常测点" detail="测量值、阈值和触发动作保持同屏。" />
        <div className="public-evidence-list">
          {manifest.triggering_evidence.map((item) => (
            <article key={item.id}>
              <ScanSearch size={17} />
              <div><strong>{item.signal}</strong><p>{item.measurement} · threshold {item.threshold}</p><small>{item.effect}</small></div>
            </article>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function Cases({ manifest, detail = false }: { manifest: PublicReplayManifest; detail?: boolean }) {
  if (!detail) {
    return (
      <Panel variant="raised">
        <PanelHeader eyebrow="1 FROZEN CASE" title={manifest.case.title} detail="唯一公开案件；来源与范围已固定。" />
        <Link className="public-case-card" to={`/cases/${manifest.case.case_id}`}>
          <BriefcaseBusiness size={22} />
          <div>
            <span>{manifest.case.case_id}</span>
            <strong>{manifest.case.dataset}</strong>
            <small>{manifest.case.input_scope}</small>
          </div>
          <StatusBadge tone="warning">{manifest.case.initial_disposition}</StatusBadge>
        </Link>
      </Panel>
    );
  }
  return (
    <>
      <div className="public-replay-grid">
        <Panel variant="raised">
          <PanelHeader eyebrow="CASE FACTS" title={manifest.case.title} detail={manifest.case.input_scope} />
          <DetailRow label="Parent disposition" value={manifest.case.initial_disposition} />
          <DetailRow label="Child disposition" value={manifest.case.child_disposition} />
          <DetailRow label="Human authority" value={manifest.case.human_authority_required ? "REQUIRED" : "INVALID"} />
          <DetailRow label="Production release" value="FALSE" />
        </Panel>
        <Panel>
          <PanelHeader eyebrow="MISSING EVIDENCE" title="系统不会补画的事实" detail="这些缺口阻止页面被误读为工厂验收。" />
          <ul className="public-missing-list">
            {manifest.missing_evidence.map((item) => <li key={item}><LockKeyhole size={14} />{item}</li>)}
          </ul>
        </Panel>
      </div>
      <ClaimBoundary title="案件裁决边界" tone="danger">
        Child 只在冻结合成分母上得到 PASS_LOCAL_SYNTHETIC_ONLY；生产放行仍为 false，根因仍需真实现场证据与具名专业人员确认。
      </ClaimBoundary>
    </>
  );
}

function Evidence({ manifest }: { manifest: PublicReplayManifest }) {
  return (
    <Panel variant="raised">
      <PanelHeader eyebrow="TRIGGERING EVIDENCE" title="Worker 与测点一一绑定" detail="不展示原图、客户类别或本地路径。" />
      <div className="public-evidence-table">
        <div className="public-evidence-table__head"><span>ID</span><span>Signal</span><span>Measurement</span><span>Threshold</span><span>Effect</span></div>
        {manifest.triggering_evidence.map((item) => (
          <div key={item.id}>
            <code>{item.id}</code><strong>{item.signal}</strong><span>{item.measurement}</span><span>{item.threshold}</span><small>{item.effect}</small>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function Capa({ manifest }: { manifest: PublicReplayManifest }) {
  return (
    <>
      <Panel variant="raised">
        <PanelHeader eyebrow="PARENT / HUMAN / CHILD" title="冻结血缘回放" detail="公开回放只呈现已冻结状态。" />
        <div className="public-lineage-rail">
          {manifest.lineage.map((item, index) => (
            <article key={item.id}>
              <span>{index + 1}</span>
              <div><strong>{item.label}</strong><small>{item.state}</small></div>
            </article>
          ))}
        </div>
      </Panel>
      <div className="public-locked-actions">
        <LockedAction label="批准 CAPA" reason="公开静态模式不建立操作者身份或审批绑定。" />
        <LockedAction label="执行派生整改" reason="GitHub Pages 没有私有数据卷或本地 API。" />
        <LockedAction label="生产放行" reason="系统设计上保留给具名专业人员；当前始终为 false。" danger />
      </div>
    </>
  );
}

function Runs({ manifest }: { manifest: PublicReplayManifest }) {
  return (
    <div className="public-replay-grid">
      <Panel variant="raised">
        <PanelHeader eyebrow="PHASE TRACE" title="可观察运行事件" detail="顺序与状态来自公开清单。" />
        <div className="public-run-timeline">
          {manifest.phases.map((phase, index) => (
            <article key={phase.id}><span>{index + 1}</span><div><strong>{phase.label}</strong><small>{phase.state}</small></div></article>
          ))}
        </div>
      </Panel>
      <Panel>
        <PanelHeader eyebrow="BUDGET RECEIPT" title="选择预算" detail="没有隐藏的模型调用。" />
        <Metric label="Selected" value={String(manifest.worker_selection.budget.selected)} detail="evidence-changing Workers" tone="warning" />
        <Metric label="Maximum" value={String(manifest.worker_selection.budget.maximum)} detail="frozen budget" tone="info" />
        <Metric label="Model calls" value="0" detail="deterministic replay" tone="success" />
      </Panel>
    </div>
  );
}

function Integrations() {
  const rows: Array<[string, string, string]> = [
    ["YOLO / COCO / VOC", "FORMAT CONTRACT", "公开接口与示例"],
    ["CVAT / FiftyOne", "LOCAL CONTRACT", "未连接外部服务"],
    ["OpenAI-compatible BYOK", "DISABLED ON PAGES", "密钥只允许本机服务端保管"],
    ["MES / OPC UA / PLC", "NOT CONNECTED", "无生产写权限"],
    ["Hosted AgentTeams", "NOT PROBED", "无远程执行回执"],
  ];
  return (
    <Panel variant="raised">
      <PanelHeader eyebrow="COMPATIBILITY ≠ CONNECTION" title="接口合同清单" detail="公开页不把适配器代码写成已上线连接。" />
      <div className="public-integration-list">
        {rows.map(([name, state, detail]) => (
          <article key={name}><Network size={17} /><div><strong>{name}</strong><small>{detail}</small></div><StatusBadge tone={state.includes("NOT") || state.includes("DISABLED") ? "locked" : "info"} compact>{state}</StatusBadge></article>
        ))}
      </div>
    </Panel>
  );
}

function Governance({ manifest }: { manifest: PublicReplayManifest }) {
  const controls = [
    ["Read only", manifest.demo_controls.read_only],
    ["Backend connected", manifest.demo_controls.backend_connected],
    ["API key input", manifest.demo_controls.api_key_input_enabled],
    ["Customer data included", manifest.demo_controls.customer_data_included],
    ["Personal data included", manifest.demo_controls.personal_data_included],
    ["Raw industrial images", manifest.demo_controls.raw_industrial_images_included],
  ] as const;
  return (
    <>
      <div className="public-replay-grid">
        <Panel variant="raised">
          <PanelHeader eyebrow="PUBLICATION CONTROLS" title="公开模式硬边界" detail="布尔值由 SHA 绑定清单提供。" />
          {controls.map(([label, value]) => <DetailRow key={label} label={label} value={String(value).toUpperCase()} />)}
        </Panel>
        <Panel>
          <PanelHeader eyebrow="RELEASE STATE" title="本地与官方状态分离" detail="网页部署成功不改变比赛或生产状态。" />
          <DetailRow label="Frozen RC3 baseline" value={manifest.release_status.local_candidate} />
          <DetailRow label="Public attestation" value={manifest.evidence_boundary.public_snapshot_attestation} />
          <DetailRow label="Official submission" value={manifest.release_status.official_submission} />
          <DetailRow label="Official evaluation" value={manifest.release_status.official_evaluation} />
          <DetailRow label="Production release" value="FALSE" />
        </Panel>
      </div>
      <ClaimBoundary title="专业判断边界" tone="danger">
        VisionData Gate 只提供证据组织、受控编排和门禁建议，不替代质量负责人、客户机构或主管部门的最终判断，也不直接控制生产设备。
      </ClaimBoundary>
    </>
  );
}

function Review({ manifest }: { manifest: PublicReplayManifest }) {
  const rows = [
    ["问题真实", "公开行业来源与场景边界", "README / INDUSTRY_SCENARIO_VALUE"],
    ["能力真实", "选中/拒绝 Worker、预算、触发证据", "Public replay manifest"],
    ["闭环结构可核验", "Parent / Human / Derived / Child", "Lineage view"],
    ["异常稳定", "缺失事实保持 HOLD，不制造 PASS", "Governance view"],
    ["安全合规", "无客户数据、无密钥、无人机写", "Publication boundary"],
    ["开放复用", "Apache-2.0、SBOM、格式合同", "Repository docs"],
  ];
  return (
    <Panel variant="raised">
      <PanelHeader eyebrow="GOAI REVIEW INDEX" title="评审问题 → 客观证明物" detail="链接材料仍需评委独立核验。" />
      <div className="public-review-table">
        {rows.map(([question, evidence, source]) => (
          <article key={question}><strong>{question}</strong><span>{evidence}</span><code>{source}</code></article>
        ))}
      </div>
      <Digest label="Public manifest SHA-256" value={manifest.manifest_sha256} />
    </Panel>
  );
}

function Account() {
  return (
    <Panel variant="raised">
      <PanelHeader eyebrow="NO IDENTITY PLANE" title="公开页不创建用户身份" detail="会话仅由浏览器用于页面导航偏好。" />
      <EmptyState icon={UserRoundX} title="No account required" description="无登录、无 Cookie 身份、无跨用户资源，也没有服务器端数据库。" />
      <DetailRow label="API key storage" value="NONE" />
      <DetailRow label="Personal profile" value="NONE" />
      <DetailRow label="Tenant workspace" value="NONE" />
    </Panel>
  );
}

function Settings({ manifest }: { manifest: PublicReplayManifest }) {
  return (
    <div className="public-replay-grid">
      <Panel variant="raised">
        <PanelHeader eyebrow="BUILD-TIME LOCK" title="公开运行模式" detail="这些值不能在页面中切换。" />
        <DetailRow label="Source" value={manifest.source_mode} />
        <DetailRow label="Transport" value="STATIC ASSET" />
        <DetailRow label="Writes" value="DISABLED" />
        <DetailRow label="External model" value="DISABLED" />
      </Panel>
      <Panel>
        <PanelHeader eyebrow="SECRET BOUNDARY" title="密钥不进入浏览器" detail="BYOK 只属于本机部署的服务端设置。" />
        <EmptyState icon={KeyRound} title="API key input unavailable" description="公开 Pages 不渲染密钥表单，不读取 .env，也不连接 OpenToken、DeepSeek 或其他模型网关。" />
      </Panel>
    </div>
  );
}

function renderView(view: PublicReplayView, manifest: PublicReplayManifest) {
  switch (view) {
    case "workspace": return <Workspace manifest={manifest} />;
    case "command-center": return <CommandCenter manifest={manifest} />;
    case "cases": return <Cases manifest={manifest} />;
    case "case-detail": return <Cases manifest={manifest} detail />;
    case "evidence": return <Evidence manifest={manifest} />;
    case "capa": return <Capa manifest={manifest} />;
    case "lineage": return <Capa manifest={manifest} />;
    case "runs": return <Runs manifest={manifest} />;
    case "integrations": return <Integrations />;
    case "governance": return <Governance manifest={manifest} />;
    case "review": return <Review manifest={manifest} />;
    case "account": return <Account />;
    case "settings": return <Settings manifest={manifest} />;
  }
}

export function PublicReplayPage({ view }: { view: PublicReplayView }) {
  const state = usePublicReplayManifest();
  const copy = viewCopy[view];

  if (state.status === "LOADING") {
    return (
      <div className="page-stack">
        <EmptyState icon={Database} title="正在核验公开清单" description="先完成浏览器端 JCS SHA-256 复算，再显示任何回放事实。" />
      </div>
    );
  }

  if (state.status === "FAILED") {
    return (
      <div className="page-stack">
        <EmptyState icon={CircleOff} title="公开回放失败关闭" description={`清单缺失或完整性失败：${state.reason}。页面不会使用嵌入数字补位。`} />
      </div>
    );
  }

  return (
    <div className="page-stack public-replay-page">
      <PageIntro
        eyebrow={copy.eyebrow}
        title={copy.title}
        description={copy.description}
        meta={<><StatusBadge tone="info">PUBLIC SYNTHETIC REPLAY</StatusBadge><span>NO BACKEND</span><span>NO CUSTOMER DATA</span></>}
      />
      <PublicManifestGate manifest={state.manifest} />
      {renderView(view, state.manifest)}
    </div>
  );
}

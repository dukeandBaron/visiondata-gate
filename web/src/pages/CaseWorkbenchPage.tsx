import { ArrowLeft, FileDown, ListChecks, LockKeyhole, Network, RefreshCw, ScanSearch } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  CausalReplay,
  type CausalReplayBinding,
  type CausalReplayViewState,
} from "../components/CausalReplay";
import { LiveIncidentWorkbench } from "../components/LiveIncidentWorkbench";
import { AgentTrace, CaseTree, HumanGateBar, InspectionCanvas, ToolGraph } from "../components/visuals";
import {
  ClaimBoundary,
  ActionButton,
  EvidenceSourceBadge,
  Metric,
  Panel,
  PanelHeader,
  StatusBadge,
} from "../components/ui";
import { getCapaCausalReplay } from "../data/api";
import { cases } from "../data/fixtures";
import type { CausalReplayReport, EvidenceSource } from "../domain";

type WorkbenchTab = "assets" | "evidence" | "trace";

const productTaskIdPattern = /^tsk_[0-9a-f]{20}$/;
const capaCaseIdPattern = /^capa_[A-Za-z0-9]{20}$/;
const industrialIncidentIdPattern = /^incident_[0-9a-f]{20}$/;

export function CaseWorkbenchPage() {
  const { caseId: displayCaseId = "rc3-omni-05" } = useParams();
  const [searchParams] = useSearchParams();
  const liveReplayRoute = displayCaseId === "live-replay";
  const liveIncidentRoute = industrialIncidentIdPattern.test(displayCaseId);
  const matchedCaseRecord = cases.find((item) => item.id === displayCaseId);
  const caseRecord = matchedCaseRecord ?? cases[0];
  const [mobileTab, setMobileTab] = useState<WorkbenchTab>("evidence");
  const parentTaskId = searchParams.get("parentTaskId")?.trim() ?? "";
  const capaCaseId = (
    searchParams.get("capaCaseId") ?? searchParams.get("caseId") ?? ""
  ).trim();
  const hasValidReplayIds =
    productTaskIdPattern.test(parentTaskId) && capaCaseIdPattern.test(capaCaseId);
  const hasRealReplayBinding = liveReplayRoute && hasValidReplayIds;
  const replayBinding: CausalReplayBinding | undefined = hasRealReplayBinding
    ? { parentTaskId, capaCaseId }
    : undefined;
  const [replayReport, setReplayReport] = useState<CausalReplayReport | null>(null);
  const [replayState, setReplayState] = useState<CausalReplayViewState>(
    hasRealReplayBinding ? "LOADING" : "FROZEN",
  );
  const [replayError, setReplayError] = useState<string | undefined>();
  const [replayRefreshToken, setReplayRefreshToken] = useState(0);

  useEffect(() => {
    let active = true;
    if (!hasRealReplayBinding) {
      setReplayReport(null);
      setReplayState("FROZEN");
      setReplayError(
        parentTaskId || capaCaseId
          ? !liveReplayRoute
            ? "真实回放仅在 /cases/live-replay 隔离视图中加载，不能嵌入 fixture 案件。"
            : "查询绑定格式无效；必须同时提供真实 tsk_* Parent Task 与 capa_* Case 标识。"
          : undefined,
      );
      return () => {
        active = false;
      };
    }

    setReplayReport(null);
    setReplayState("LOADING");
    setReplayError(undefined);
    void getCapaCausalReplay(parentTaskId, capaCaseId)
      .then((report) => {
        if (!active) return;
        setReplayReport(report);
        setReplayState("READY");
      })
      .catch((error: unknown) => {
        if (!active) return;
        setReplayReport(null);
        setReplayState("ERROR");
        setReplayError(error instanceof Error ? error.message : "真实因果回放请求失败");
      });

    return () => {
      active = false;
    };
  }, [capaCaseId, hasRealReplayBinding, liveReplayRoute, parentTaskId, replayRefreshToken]);

  if (liveIncidentRoute) {
    return (
      <LiveIncidentWorkbench
        taskId={searchParams.get("task")?.trim() ?? ""}
        caseId={displayCaseId}
      />
    );
  }

  if (!liveReplayRoute && !matchedCaseRecord) {
    return (
      <div className="page-stack">
        <Panel variant="raised">
          <PanelHeader
            eyebrow="CASE NOT FOUND"
            title="案件不存在"
            detail={`未找到 ${displayCaseId}；系统不会用其他 fixture 静默替代。`}
          />
          <Link to="/cases"><ArrowLeft size={14} /> 返回真实案件收件箱</Link>
        </Panel>
      </div>
    );
  }

  const replaySource: EvidenceSource = replayState === "READY" && replayReport
    ? "LIVE_API"
    : replayState === "FROZEN" && !liveReplayRoute
      ? "FROZEN_FIXTURE"
      : "NOT_CONNECTED";
  if (!caseRecord) return null;

  if (liveReplayRoute) {
    return (
      <div className="case-workbench-page">
        <div className="workbench-heading">
          <div>
            <Link to="/cases" className="back-link"><ArrowLeft size={15} /> 返回案件</Link>
            <div className="workbench-heading__title">
              <span className="eyebrow">LIVE READ-ONLY / CAUSAL REPLAY</span>
              <h1>真实案件因果回放</h1>
            </div>
          </div>
          <div className="workbench-heading__state">
            <EvidenceSourceBadge source={replaySource} />
            <StatusBadge tone="locked"><LockKeyhole size={13} /> READ ONLY</StatusBadge>
          </div>
        </div>

        <Panel variant="raised">
          <PanelHeader
            eyebrow="ISOLATED LIVE VIEW"
            title="T0–T4 SHA 绑定状态"
            detail="此视图不加载 fixture 标题、画布、指标或责任流；所有计数仅来自当前 API 回执。"
            actions={<EvidenceSourceBadge source={replaySource} />}
          />
          <CausalReplay
            report={replayReport}
            source={replaySource}
            state={replayState}
            binding={replayBinding}
            errorMessage={replayError}
          />
          {replayState === "ERROR" && replayBinding ? (
            <ActionButton
              variant="secondary"
              icon={RefreshCw}
              onClick={() => setReplayRefreshToken((value) => value + 1)}
            >
              重试只读回放 GET
            </ActionButton>
          ) : null}
        </Panel>

        <ClaimBoundary title="实时回放边界" tone="danger">
          该页面只读展示服务端已完成完整性校验的案件状态，不提供审批、整改执行或生产放行操作。
          未绑定真实任务或校验失败时，页面保持 NOT CONNECTED，不使用 fixture 补位。
        </ClaimBoundary>
      </div>
    );
  }
  const statusTone = caseRecord.status === "PASS_LOCAL" ? "success" : caseRecord.status === "RECAPTURE" ? "warning" : "danger";
  const syntheticCase = caseRecord.id === "synthetic-v3";
  const publicPilot = caseRecord.id === "omni-180-rc2";
  const responsibilityStreams: Array<{
    code: string;
    title: string;
    detail: string;
    state: string;
    tone: "danger" | "warning" | "success";
  }> = syntheticCase
    ? [{ code: "01", title: "合成注入真值", detail: "12 / 12 在固定 fixture 中关闭", state: "CLOSED", tone: "success" }]
    : publicPilot
      ? [{ code: "01", title: "冻结公开 Pilot 工单", detail: "45 findings / 45 work orders；未执行 CAPA", state: "OPEN", tone: "danger" }]
      : [
          { code: "01", title: "证据调查", detail: "2 条风险处置流证据", state: "OPEN", tone: "danger" },
          { code: "02", title: "数据划分治理", detail: "7 条责任项", state: "OPEN", tone: "warning" },
          {
            code: "03",
            title: "采集质量恢复",
            detail: caseRecord.id === "rc3-omni-05" ? "6 closed / 43 open" : "0 closed / 40 open",
            state: caseRecord.id === "rc3-omni-05" ? "PARTIAL" : "OPEN",
            tone: "warning",
          },
        ];
  const responsibilityDetail = syntheticCase
    ? "12 个注入真值问题只在 Synthetic-v3 固定分母中闭环。"
    : publicPilot
      ? "公开 Pilot 只证明 45 findings 与 45 work orders，不证明 CAPA 已执行。"
      : "49 条原子底账聚合为 3 个风险处置流。";

  return (
    <div className="case-workbench-page">
      <div className="workbench-heading">
        <div>
          <Link to="/cases" className="back-link"><ArrowLeft size={15} /> 返回案件</Link>
          <div className="workbench-heading__title">
            <span className="eyebrow">{caseRecord.namespace} / {caseRecord.displayId}</span>
            <h1>{caseRecord.title}</h1>
          </div>
        </div>
        <div className="workbench-heading__state">
          <EvidenceSourceBadge source={caseRecord.source} />
          <StatusBadge tone={statusTone}>{caseRecord.status}</StatusBadge>
        </div>
      </div>

      <div className="workbench-tabs" role="tablist" aria-label="案件工作台区域">
        <button type="button" role="tab" aria-selected={mobileTab === "assets"} className={mobileTab === "assets" ? "is-active" : ""} onClick={() => setMobileTab("assets")}>案件资产</button>
        <button type="button" role="tab" aria-selected={mobileTab === "evidence"} className={mobileTab === "evidence" ? "is-active" : ""} onClick={() => setMobileTab("evidence")}>视觉证据</button>
        <button type="button" role="tab" aria-selected={mobileTab === "trace"} className={mobileTab === "trace" ? "is-active" : ""} onClick={() => setMobileTab("trace")}>Agent 治理</button>
      </div>

      <div className={`case-workbench active-tab-${mobileTab}`}>
        <Panel className="case-workbench__tree">
          <PanelHeader eyebrow="ASSET TREE" title="数据集 / 案件树" detail="Parent、派生副本与 Child 相互隔离。" />
          <CaseTree activeCaseId={caseRecord.id} />
          <div className="tree-metrics">
            <Metric label="Findings" value={String(caseRecord.findings)} detail="current run" tone="warning" />
            <Metric label="责任项" value={`${caseRecord.responsibilityClosed}/${caseRecord.responsibilityOpen}`} detail="closed/open" tone="danger" />
          </div>
        </Panel>

        <div className="case-workbench__center">
          <Panel variant="raised">
            <PanelHeader
              eyebrow="INSTRUMENT"
              title="视觉检查执行窗"
              detail={syntheticCase
                ? "展示 Synthetic-v3 唯一已验证的清晰度测量与固定修复复验。"
                : "Synthetic-v3 测量只作为明细 fallback；Omni 案件只展示聚合状态。"}
              actions={<StatusBadge tone="info" compact><ScanSearch size={13} /> EVIDENCE VIEW</StatusBadge>}
            />
            <InspectionCanvas caseRecord={caseRecord} />
          </Panel>
          <Panel>
            <PanelHeader
              eyebrow="CAUSAL REPLAY"
              title="T0–T4 证据因果回放"
              detail="回放可观察的 SHA 绑定状态；finding 与责任项始终使用独立分母。"
              actions={<EvidenceSourceBadge source={replaySource} />}
            />
            <CausalReplay
              report={replayReport}
              source={replaySource}
              state={replayState}
              binding={replayBinding}
              errorMessage={replayError}
            />
          </Panel>
          <Panel>
            <PanelHeader
              eyebrow="TOOL GRAPH"
              title={syntheticCase ? "确定性修复与独立复验" : "确定性工具与动态补证"}
              detail={syntheticCase ? "固定真值、受控修复与同合同复验。" : "工具负责计算，Agent 负责受控编排。"}
            />
            <ToolGraph mode={syntheticCase ? "synthetic" : "incident"} />
          </Panel>
        </div>

        <div className="case-workbench__right">
          <Panel variant="raised">
            <PanelHeader eyebrow="GOVERNED AGENT" title="智能与治理中枢" detail="结构化摘要，不展示私有思维链。" />
            <AgentTrace caseRecord={caseRecord} />
          </Panel>
          <Panel>
            <PanelHeader eyebrow="RESPONSIBILITY" title="责任项与工单" detail={responsibilityDetail} />
            <div className="responsibility-streams">
              {responsibilityStreams.map((stream) => (
                <article key={stream.code}>
                  <span>{stream.code}</span>
                  <div><strong>{stream.title}</strong><small>{stream.detail}</small></div>
                  <StatusBadge tone={stream.tone} compact>{stream.state}</StatusBadge>
                </article>
              ))}
            </div>
          </Panel>
          <Panel variant="danger">
            <HumanGateBar />
          </Panel>
        </div>
      </div>

      <div className="workbench-actions">
        <Link className="text-action" to="/evidence"><ListChecks size={16} /> 打开 Evidence Lab</Link>
        <Link className="text-action" to="/lineage"><Network size={16} /> 查看完整血缘</Link>
        <button type="button" disabled><FileDown size={16} /> 下载当前证据包</button>
        <span><LockKeyhole size={14} /> fixture 模式不发起写操作</span>
      </div>

      <ClaimBoundary title="当前案件裁决" tone="danger">
        {caseRecord.scopeNote} 生产放行始终为 false；页面中的禁用按钮不会发送审批、执行或恢复请求。
      </ClaimBoundary>
    </div>
  );
}

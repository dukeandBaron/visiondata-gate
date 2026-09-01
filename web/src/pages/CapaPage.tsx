import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  FileImage,
  LoaderCircle,
  LockKeyhole,
  RefreshCcw,
  ShieldCheck,
  ShieldX,
  UserCheck,
  UserPlus,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useProduct } from "../ProductContext";
import { ActionButton, Modal, Panel, PanelHeader, StatusBadge } from "../components/ui";
import { ControlledCapaWorkbench } from "../components/ControlledCapaWorkbench";
import {
  listOperatorWorkOrders,
  loadOperatorAnnotations,
  loadOperatorWorkOrderCrop,
  OperatorApiError,
  updateOperatorWorkOrder,
} from "../data/api";
import type {
  BoundingBoxAnnotation,
  OperatorAnnotationState,
  OperatorWorkOrder,
  OperatorWorkOrderStatus,
} from "../operatorDomain";

type WorkOrderTransitionStatus = Exclude<OperatorWorkOrderStatus, "OPEN">;

const transitionCopy: Record<
  WorkOrderTransitionStatus,
  {
    eyebrow: string;
    title: string;
    description: string;
    action: string;
    notePlaceholder: string;
  }
> = {
  ACKNOWLEDGED: {
    eyebrow: "NAMED OWNERSHIP",
    title: "具名认领工单",
    description: "记录实际责任人，并确认已查看当前图片、BBox 与来源 SHA。",
    action: "确认认领",
    notePlaceholder: "填写复核范围、初步判断或计划完成时间",
  },
  IN_CAPA: {
    eyebrow: "HUMAN CAPA GATE",
    title: "批准纳入 CAPA",
    description: "该操作只进入本地整改流程，不构成设备写入或生产放行。",
    action: "批准进入 CAPA",
    notePlaceholder: "填写整改目标、边界与责任安排",
  },
  CLOSED: {
    eyebrow: "CLOSURE EVIDENCE",
    title: "复核并关闭工单",
    description: "必须写明关闭依据；当前页面不会自动推断整改已有效。",
    action: "确认关闭",
    notePlaceholder: "填写复验结果、依据或关联回执（必填）",
  },
  REJECTED: {
    eyebrow: "HUMAN OVERRIDE",
    title: "驳回或标记误报",
    description: "保留人工纠错理由，原始图片、标注与历史修订不会被删除。",
    action: "确认驳回",
    notePlaceholder: "填写驳回或误报理由（必填）",
  },
};

function workOrderError(error: unknown): string {
  if (error instanceof OperatorApiError) return `${error.code}: ${error.message}`;
  return "无法读取本地工单队列，请检查 API。";
}

function workOrderTone(status: OperatorWorkOrderStatus) {
  if (status === "CLOSED") return "success" as const;
  if (status === "REJECTED") return "locked" as const;
  if (status === "IN_CAPA") return "warning" as const;
  if (status === "ACKNOWLEDGED") return "info" as const;
  return "danger" as const;
}

function sameAnnotation(
  left: BoundingBoxAnnotation,
  right: BoundingBoxAnnotation,
): boolean {
  return (
    left.annotation_id === right.annotation_id &&
    left.label === right.label &&
    left.x === right.x &&
    left.y === right.y &&
    left.width === right.width &&
    left.height === right.height &&
    left.source === right.source
  );
}

function targetAnnotationChanged(
  state: OperatorAnnotationState,
  issued: BoundingBoxAnnotation,
): boolean {
  const current = state.annotations.find(
    (item) => item.annotation_id === issued.annotation_id,
  );
  return current === undefined || !sameAnnotation(current, issued);
}

function WorkOrderCrop({ workOrder }: { workOrder: OperatorWorkOrder }) {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    let active = true;
    let objectUrl: string | undefined;
    void loadOperatorWorkOrderCrop(workOrder)
      .then((nextUrl) => {
        objectUrl = nextUrl;
        if (!active) {
          URL.revokeObjectURL(nextUrl);
          return;
        }
        setUrl(nextUrl);
      })
      .catch(() => setUrl(undefined));
    return () => {
      active = false;
      const urlToRevoke = objectUrl;
      if (urlToRevoke) window.setTimeout(() => URL.revokeObjectURL(urlToRevoke), 1_000);
    };
  }, [workOrder]);
  return url ? (
    <img src={url} alt={`${workOrder.annotation.label} 工单裁剪图`} />
  ) : (
    <span><FileImage size={20} /></span>
  );
}

export function CapaPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedWorkOrderId = searchParams.get("workOrder")?.trim() ?? "";
  const controlledDeepLink =
    searchParams.get("layer")?.trim().toLowerCase() === "controlled" ||
    Boolean(searchParams.get("case")?.trim());
  const { activeWorkspace, activeProject } = useProduct();
  const workspaceId = activeWorkspace?.workspace_id;
  const activeScopeRef = useRef({
    workspaceId,
    projectId: activeProject?.project_id,
  });
  const workOrderRequestRef = useRef(0);
  const [workOrders, setWorkOrders] = useState<OperatorWorkOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatingId, setUpdatingId] = useState<string>();
  const [errorMessage, setErrorMessage] = useState<string>();
  const [focusNotice, setFocusNotice] = useState<string>();
  const [focusedWorkOrderId, setFocusedWorkOrderId] = useState("");
  const [transitionDraft, setTransitionDraft] = useState<{
    workOrder: OperatorWorkOrder;
    status: WorkOrderTransitionStatus;
  }>();
  const [transitionAssignee, setTransitionAssignee] = useState("");
  const [transitionNote, setTransitionNote] = useState("");
  const [transitionAttested, setTransitionAttested] = useState(false);
  const [transitionReceipt, setTransitionReceipt] = useState<OperatorWorkOrder>();
  const [closureAnnotation, setClosureAnnotation] = useState<OperatorAnnotationState>();
  const [closureAnnotationLoading, setClosureAnnotationLoading] = useState(false);
  const [closureAnnotationError, setClosureAnnotationError] = useState<string>();
  const [capaLayer, setCapaLayer] = useState<"PIXEL" | "CONTROLLED">(
    controlledDeepLink ? "CONTROLLED" : "PIXEL",
  );

  activeScopeRef.current = {
    workspaceId,
    projectId: activeProject?.project_id,
  };

  const refresh = useCallback(async () => {
    const requestVersion = workOrderRequestRef.current + 1;
    workOrderRequestRef.current = requestVersion;
    setLoading(true);
    setErrorMessage(undefined);
    setFocusNotice(undefined);
    setFocusedWorkOrderId("");
    setTransitionReceipt(undefined);
    setWorkOrders([]);
    const projectId = activeProject?.project_id;
    if (!workspaceId || !projectId) {
      setLoading(false);
      return;
    }
    try {
      const nextWorkOrders = await listOperatorWorkOrders(
        workspaceId,
        projectId,
        activeProject.source_kind === "synthetic_demo",
      );
      if (workOrderRequestRef.current === requestVersion) {
        setWorkOrders(nextWorkOrders);
        const requested = nextWorkOrders.find(
          (workOrder) => workOrder.work_order_id === requestedWorkOrderId,
        );
        if (requestedWorkOrderId && !requested) {
          setFocusNotice(
            "深链接工单不属于当前 workspace / project，已拒绝定位。",
          );
        } else {
          setFocusedWorkOrderId(requested?.work_order_id ?? "");
        }
      }
    } catch (error) {
      if (workOrderRequestRef.current === requestVersion) {
        setErrorMessage(workOrderError(error));
      }
    } finally {
      if (workOrderRequestRef.current === requestVersion) setLoading(false);
    }
  }, [activeProject?.project_id, activeProject?.source_kind, requestedWorkOrderId, workspaceId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!focusedWorkOrderId) return;
    document
      .getElementById(`work-order-${focusedWorkOrderId}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusedWorkOrderId, workOrders]);

  useEffect(() => {
    setTransitionDraft(undefined);
    setTransitionAttested(false);
    setTransitionReceipt(undefined);
    setClosureAnnotation(undefined);
    setClosureAnnotationError(undefined);
    setClosureAnnotationLoading(false);
    setUpdatingId(undefined);
  }, [activeProject?.project_id, workspaceId]);

  useEffect(() => {
    if (controlledDeepLink) setCapaLayer("CONTROLLED");
  }, [controlledDeepLink]);

  useEffect(() => {
    let active = true;
    setClosureAnnotation(undefined);
    setClosureAnnotationError(undefined);
    if (transitionDraft?.status !== "CLOSED" || !workspaceId) {
      setClosureAnnotationLoading(false);
      return () => {
        active = false;
      };
    }
    setClosureAnnotationLoading(true);
    void loadOperatorAnnotations(workspaceId, transitionDraft.workOrder.asset_id)
      .then((annotation) => {
        if (active) setClosureAnnotation(annotation);
      })
      .catch((error: unknown) => {
        if (active) {
          setClosureAnnotationError(
            error instanceof OperatorApiError
              ? `${error.code}: ${error.message}`
              : "无法读取当前标注修订，工单保持不可关闭。",
          );
        }
      })
      .finally(() => {
        if (active) setClosureAnnotationLoading(false);
      });
    return () => {
      active = false;
    };
  }, [transitionDraft, workspaceId]);

  const updateWorkOrder = async (
    workOrder: OperatorWorkOrder,
    status: OperatorWorkOrderStatus,
    assignee: string,
    note: string,
    operatorAttestsReviewedEvidence: true,
    verification?: OperatorAnnotationState,
  ): Promise<boolean> => {
    const projectId = activeProject?.project_id;
    if (!workspaceId || !projectId) return false;
    const requestVersion = workOrderRequestRef.current;
    const requestScope = { workspaceId, projectId };
    setUpdatingId(workOrder.work_order_id);
    setErrorMessage(undefined);
    setTransitionReceipt(undefined);
    try {
      const updated = await updateOperatorWorkOrder(
        workspaceId,
        workOrder.work_order_id,
        workOrder.revision,
        status,
        assignee,
        note,
        operatorAttestsReviewedEvidence,
        verification
          ? {
              annotationRevision: verification.revision,
              annotationSha256: verification.document_sha256,
            }
          : undefined,
      );
      if (
        workOrderRequestRef.current !== requestVersion ||
        activeScopeRef.current.workspaceId !== requestScope.workspaceId ||
        activeScopeRef.current.projectId !== requestScope.projectId
      ) {
        return false;
      }
      setWorkOrders((current) =>
        current.map((item) => item.work_order_id === updated.work_order_id ? updated : item),
      );
      setTransitionReceipt(updated);
      return true;
    } catch (error) {
      if (
        workOrderRequestRef.current === requestVersion &&
        activeScopeRef.current.workspaceId === requestScope.workspaceId &&
        activeScopeRef.current.projectId === requestScope.projectId
      ) {
        setErrorMessage(workOrderError(error));
      }
      return false;
    } finally {
      if (
        workOrderRequestRef.current === requestVersion &&
        activeScopeRef.current.workspaceId === requestScope.workspaceId &&
        activeScopeRef.current.projectId === requestScope.projectId
      ) {
        setUpdatingId(undefined);
      }
    }
  };

  const openTransition = (
    workOrder: OperatorWorkOrder,
    status: WorkOrderTransitionStatus,
  ) => {
    setClosureAnnotation(undefined);
    setClosureAnnotationError(undefined);
    setClosureAnnotationLoading(status === "CLOSED");
    setTransitionDraft({ workOrder, status });
    setTransitionAssignee(workOrder.assignee);
    setTransitionNote("");
    setTransitionAttested(false);
    setErrorMessage(undefined);
  };

  const submitTransition = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!transitionDraft || !transitionAttested) return;
    const assignee = transitionAssignee.trim();
    const note = transitionNote.trim();
    if (!assignee || !note) return;
    const verification =
      transitionDraft.status === "CLOSED" ? closureAnnotation : undefined;
    if (transitionDraft.status === "CLOSED" && !verification) return;
    if (
      transitionDraft.status === "CLOSED" &&
      verification &&
      (
        verification.revision <= transitionDraft.workOrder.annotation_revision ||
        !targetAnnotationChanged(verification, transitionDraft.workOrder.annotation)
      )
    ) {
      return;
    }
    const updated = await updateWorkOrder(
      transitionDraft.workOrder,
      transitionDraft.status,
      assignee,
      note,
      transitionAttested,
      verification,
    );
    if (updated) setTransitionDraft(undefined);
  };

  const counts = useMemo(() => ({
    open: workOrders.filter((item) => item.status === "OPEN").length,
    acknowledged: workOrders.filter((item) => item.status === "ACKNOWLEDGED").length,
    inCapa: workOrders.filter((item) => item.status === "IN_CAPA").length,
    closed: workOrders.filter((item) => item.status === "CLOSED").length,
    rejected: workOrders.filter((item) => item.status === "REJECTED").length,
  }), [workOrders]);

  const closureRevisionIsNewer = Boolean(
    transitionDraft?.status === "CLOSED" &&
    closureAnnotation &&
    closureAnnotation.revision > transitionDraft.workOrder.annotation_revision,
  );
  const closureTargetIsChanged = Boolean(
    transitionDraft?.status === "CLOSED" &&
    closureAnnotation &&
    targetAnnotationChanged(
      closureAnnotation,
      transitionDraft.workOrder.annotation,
    ),
  );
  const closureEvidenceReady = Boolean(
    transitionDraft?.status === "CLOSED" &&
    closureAnnotation &&
    closureRevisionIsNewer &&
    closureTargetIsChanged,
  );

  return (
    <div className="capa-live-page">
      <header className="capa-live-header">
        <div>
          <span>WORK ORDERS · HUMAN AUTHORITY</span>
          <h1>CAPA 工单</h1>
          <p>
            {activeWorkspace?.name ?? "未选择工作空间"} · {activeProject?.name ?? "未选择项目"}
            ；这里仅显示由当前工作空间真实签发并持久化的工单。
          </p>
        </div>
        <ActionButton variant="secondary" icon={RefreshCcw} onClick={() => void refresh()} disabled={loading || Boolean(updatingId)}>
          刷新
        </ActionButton>
      </header>

      <nav className="capa-layer-tabs" aria-label="CAPA 业务层级">
        <button type="button" className={capaLayer === "PIXEL" ? "is-active" : ""} onClick={() => setCapaLayer("PIXEL")}>
          <span>像素工单</span><small>Image Workspace ledger</small>
        </button>
        <button type="button" className={capaLayer === "CONTROLLED" ? "is-active" : ""} onClick={() => setCapaLayer("CONTROLLED")}>
          <span>受控 CAPA 案件</span><small>Parent → derived copy → Child Run</small>
        </button>
        <p>两层账本当前保持独立；没有可靠 SHA 身份绑定前，页面不会声称像素工单已进入 ProductService CAPA。</p>
      </nav>

      <div className="capa-layer-view" hidden={capaLayer !== "PIXEL"}>
      <div className="capa-live-deltas" aria-label="真实工单状态统计">
        <span className="is-open" title="当前项目本地账本中等待人工处理的工单"><i />{counts.open} Open</span>
        <span className="is-ack" title="当前项目本地账本中已具名认领的工单"><i />{counts.acknowledged} Acknowledged</span>
        <span className="is-capa" title="当前项目本地账本中已进入整改流程的工单"><i />{counts.inCapa} In CAPA</span>
        <span className="is-closed" title="当前项目本地账本中已有人工关闭依据的工单；不等同于自动质量放行"><i />{counts.closed} Closed</span>
        <span className="is-rejected" title="当前项目本地账本中被人工驳回或判为误报的工单"><i />{counts.rejected} Rejected</span>
      </div>

      <Panel className="operator-work-order-panel" variant="raised">
        <PanelHeader
          eyebrow="PERSISTED LOCAL QUEUE"
          title="像素现场整改工单"
          detail={`${workOrders.length} total · values derived from the current local ledger`}
        />
        {errorMessage ? <div className="operator-work-order-error">{errorMessage}</div> : null}
        {focusNotice ? <div className="operator-work-order-error">{focusNotice}</div> : null}
        {transitionReceipt ? (
          <div className="operator-work-order-receipt" role="status">
            <CheckCircle2 size={16} />
            <span>
              工单 <strong>{transitionReceipt.work_order_id}</strong> 已写入状态 {transitionReceipt.status}
            </span>
            <code title={transitionReceipt.document_sha256}>
              rev {transitionReceipt.revision} · {transitionReceipt.document_sha256.slice(0, 16)}…
            </code>
          </div>
        ) : null}
        {loading ? (
          <div className="operator-work-order-empty">
            <LoaderCircle size={18} className="is-spinning" />正在读取本地工单账本…
          </div>
        ) : null}
        {!loading && workOrders.length === 0 ? (
          <div className="capa-empty-state">
            <span><ClipboardCheck size={22} /></span>
            <strong>当前工作空间没有工单</strong>
            <p>在图像工作簿中保存 BBox，右键该标注并完成具名人工复核后，工单会出现在这里。</p>
            <button type="button" onClick={() => navigate("/workspace")}>
              返回图像工作簿 <ArrowRight size={15} />
            </button>
          </div>
        ) : null}
        <div className="operator-work-order-list">
          {workOrders.map((workOrder) => {
            const queueBusy = Boolean(updatingId);
            const terminal = ["REJECTED", "CLOSED"].includes(workOrder.status);
            const humanReviewMissing = !workOrder.operator_attests_reviewed_evidence;
            return (
              <article
                id={`work-order-${workOrder.work_order_id}`}
                className={focusedWorkOrderId === workOrder.work_order_id ? "is-deep-linked" : undefined}
                key={workOrder.work_order_id}
              >
                <div className="operator-work-order-crop"><WorkOrderCrop workOrder={workOrder} /></div>
                <div className="operator-work-order-body">
                  <header>
                    <span>{workOrder.work_order_id}</span>
                    <StatusBadge tone={workOrderTone(workOrder.status)} compact>{workOrder.status}</StatusBadge>
                  </header>
                  <strong>{workOrder.annotation.label}</strong>
                  <p>{workOrder.image_name} · annotation rev {workOrder.annotation_revision}</p>
                  <div className="operator-work-order-binding">
                    <code>x {workOrder.pixel_bbox.x} · y {workOrder.pixel_bbox.y} · w {workOrder.pixel_bbox.width} · h {workOrder.pixel_bbox.height}</code>
                    <code title={workOrder.asset_sha256}>sha {workOrder.asset_sha256.slice(0, 12)}…</code>
                    <span>assignee: {workOrder.assignee}</span>
                    <span>ledger rev {workOrder.revision}</span>
                    <span className={humanReviewMissing ? "is-attestation-missing" : "is-attested"}>
                      {humanReviewMissing ? "HUMAN REVIEW MISSING" : "HUMAN REVIEW ATTESTED"}
                    </span>
                  </div>
                  {workOrder.note ? <small>{workOrder.note}</small> : null}
                </div>
                <div className="operator-work-order-actions">
                  <ActionButton
                    variant="secondary"
                    icon={UserPlus}
                    disabled={loading || queueBusy || terminal || humanReviewMissing || workOrder.status === "IN_CAPA"}
                    onClick={() => openTransition(workOrder, "ACKNOWLEDGED")}
                  >认领</ActionButton>
                  <ActionButton
                    variant="primary"
                    icon={ClipboardCheck}
                    disabled={
                      loading ||
                      queueBusy ||
                      terminal ||
                      humanReviewMissing ||
                      workOrder.status === "IN_CAPA"
                    }
                    onClick={() => openTransition(workOrder, "IN_CAPA")}
                  >纳入 CAPA</ActionButton>
                  {workOrder.status === "IN_CAPA" ? (
                    <ActionButton
                      variant="secondary"
                      icon={CheckCircle2}
                      disabled={loading || queueBusy || humanReviewMissing}
                      onClick={() => openTransition(workOrder, "CLOSED")}
                    >关闭</ActionButton>
                  ) : null}
                  <ActionButton
                    variant="danger"
                    icon={ShieldX}
                    disabled={loading || queueBusy || terminal}
                    onClick={() => openTransition(workOrder, "REJECTED")}
                  >驳回</ActionButton>
                </div>
              </article>
            );
          })}
        </div>
      </Panel>

      <footer className="capa-authority-note">
        <ShieldCheck size={16} />
        <span><strong>Human-in-the-loop</strong> 状态变化只写入本地责任账本；设备写入与生产放行始终不在此页面权限内。</span>
      </footer>
      </div>

      {capaLayer === "CONTROLLED" ? <ControlledCapaWorkbench /> : null}

      {transitionDraft ? (
        <Modal title="具名人工审批" onClose={() => {
          if (!updatingId) setTransitionDraft(undefined);
        }}>
          <form className="capa-signoff" onSubmit={(event) => void submitTransition(event)}>
            <div className="capa-signoff__intro">
              <span><UserCheck size={18} /></span>
              <div>
                <small>{transitionCopy[transitionDraft.status].eyebrow}</small>
                <strong>{transitionCopy[transitionDraft.status].title}</strong>
                <p>{transitionCopy[transitionDraft.status].description}</p>
              </div>
            </div>

            <dl className="capa-signoff__binding">
              <div><dt>work order</dt><dd>{transitionDraft.workOrder.work_order_id}</dd></div>
              <div><dt>status</dt><dd>{transitionDraft.workOrder.status} → {transitionDraft.status}</dd></div>
              <div><dt>evidence</dt><dd title={transitionDraft.workOrder.document_sha256}>{transitionDraft.workOrder.document_sha256.slice(0, 16)}…</dd></div>
              <div><dt>ledger</dt><dd>revision {transitionDraft.workOrder.revision}</dd></div>
              {transitionDraft.status === "CLOSED" ? (
                <>
                  <div><dt>issued annotation</dt><dd>revision {transitionDraft.workOrder.annotation_revision}</dd></div>
                  <div><dt>current annotation</dt><dd>{closureAnnotation ? `revision ${closureAnnotation.revision}` : "UNAVAILABLE"}</dd></div>
                  <div><dt>annotation SHA</dt><dd title={closureAnnotation?.document_sha256}>{closureAnnotation ? `${closureAnnotation.document_sha256.slice(0, 16)}…` : "UNAVAILABLE"}</dd></div>
                  <div><dt>target annotation</dt><dd>{closureAnnotation ? (closureTargetIsChanged ? "CHANGED / REMOVED" : "UNCHANGED") : "UNAVAILABLE"}</dd></div>
                </>
              ) : null}
            </dl>

            {errorMessage ? (
              <div className="capa-signoff__error"><AlertTriangle size={14} />{errorMessage}</div>
            ) : null}

            {transitionDraft.status === "CLOSED" ? (
              <div className={`capa-closure-verification${closureEvidenceReady ? " is-ready" : " is-blocked"}`}>
                {closureAnnotationLoading ? (
                  <><LoaderCircle size={14} className="is-spinning" /><span><strong>正在读取当前标注修订</strong><small>关闭按钮保持禁用，直到 API 返回 revision 与 document SHA。</small></span></>
                ) : closureAnnotationError ? (
                  <><AlertTriangle size={14} /><span><strong>当前标注不可读取</strong><small>{closureAnnotationError}</small></span></>
                ) : closureEvidenceReady ? (
                  <><CheckCircle2 size={14} /><span><strong>整改复验证据已绑定</strong><small>当前 revision 更新且目标标注已修改或删除；提交时服务端仍会再次核验 SHA 与最新状态。</small></span></>
                ) : (
                  <><AlertTriangle size={14} /><span><strong>尚不能关闭工单</strong><small>{!closureRevisionIsNewer ? `当前 annotation revision 必须大于签发时 revision ${transitionDraft.workOrder.annotation_revision}。` : "目标 BBox 尚未修改或删除。"}</small></span></>
                )}
                {!closureEvidenceReady && !closureAnnotationLoading ? (
                  <button type="button" onClick={() => { setTransitionDraft(undefined); navigate("/workspace"); }}>
                    返回图像工作簿整改 <ArrowRight size={12} />
                  </button>
                ) : null}
              </div>
            ) : null}

            <label className="capa-signoff__field">
              <span>具名责任人 / 工号</span>
              <input
                value={transitionAssignee}
                onChange={(event) => setTransitionAssignee(event.target.value)}
                maxLength={120}
                autoFocus
                required
              />
              <small>写入工单 assignee 字段，用于后续责任追踪。</small>
            </label>
            <label className="capa-signoff__field">
              <span>人工判断与依据</span>
              <textarea
                value={transitionNote}
                onChange={(event) => setTransitionNote(event.target.value)}
                placeholder={transitionCopy[transitionDraft.status].notePlaceholder}
                maxLength={1000}
                rows={4}
                required
              />
            </label>
            <label className={`capa-signoff__attestation${transitionAttested ? " is-checked" : ""}`}>
              <input
                type="checkbox"
                checked={transitionAttested}
                onChange={(event) => setTransitionAttested(event.target.checked)}
              />
              <LockKeyhole size={15} />
              <span>
                <strong>我已复核当前证据并承担本次人工流转责任</strong>
                <small>AI/Agent 仅提供辅助建议；本操作不授予生产放行、设备控制或自动执行权限。</small>
              </span>
            </label>
            <footer className="capa-signoff__actions">
              <button type="button" onClick={() => setTransitionDraft(undefined)} disabled={Boolean(updatingId)}>
                取消
              </button>
              <button
                type="submit"
                className={transitionDraft.status === "REJECTED" ? "is-danger" : "is-primary"}
                disabled={
                  Boolean(updatingId) ||
                  !transitionAttested ||
                  !transitionAssignee.trim() ||
                  !transitionNote.trim() ||
                  (transitionDraft.status === "CLOSED" && !closureEvidenceReady)
                }
              >
                {updatingId ? <LoaderCircle size={14} className="is-spinning" /> : <ShieldCheck size={14} />}
                {updatingId ? "正在写入不可变修订…" : transitionCopy[transitionDraft.status].action}
              </button>
            </footer>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}

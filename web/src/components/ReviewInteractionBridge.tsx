import { LoaderCircle, LockKeyhole, MessageSquareText, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type {
  IncidentInteractionReceipt,
  IndustrialIncident,
} from "../agentDomain";
import { getIndustrialIncidentInteractionReceipt } from "../data/api";
import { IncidentInteractionTimeline } from "./IncidentInteractionTimeline";
import { ActionButton, StatusBadge } from "./ui";

interface ReviewInteractionBridgeProps {
  taskId: string;
  incidents: IndustrialIncident[];
  incidentsPending: boolean;
  incidentsUnavailable: boolean;
}

type BridgeState = "LOADING" | "READY" | "EMPTY" | "FAIL_CLOSED";

function newestChildCase(
  incidents: IndustrialIncident[],
  taskId: string,
): IndustrialIncident | undefined {
  return [...incidents]
    .filter(
      (incident) =>
        incident.task_id === taskId &&
        incident.parent_case_id !== null && incident.authorizing_decision_id !== null,
    )
    .sort((left, right) => right.case_version - left.case_version)[0];
}

export function ReviewInteractionBridge({
  taskId,
  incidents,
  incidentsPending,
  incidentsUnavailable,
}: ReviewInteractionBridgeProps) {
  const navigate = useNavigate();
  const child = useMemo(() => newestChildCase(incidents, taskId), [incidents, taskId]);
  const [state, setState] = useState<BridgeState>("LOADING");
  const [receipt, setReceipt] = useState<IncidentInteractionReceipt>();
  const [error, setError] = useState<string>();
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    let active = true;
    setReceipt(undefined);
    setError(undefined);

    if (incidentsPending) {
      setState("LOADING");
      return () => {
        active = false;
      };
    }
    if (incidentsUnavailable) {
      setState("FAIL_CLOSED");
      setError("Incident 索引不可用，无法证明 Parent / Child 身份。");
      return () => {
        active = false;
      };
    }
    if (!child) {
      setState("EMPTY");
      return () => {
        active = false;
      };
    }

    setState("LOADING");
    void getIndustrialIncidentInteractionReceipt(taskId, child.case_id)
      .then((value) => {
        if (!active) return;
        if (
          value.parent_case_id !== child.parent_case_id ||
          value.parent_case_sha256 !== child.parent_case_sha256 ||
          value.decision_id !== child.authorizing_decision_id ||
          value.decision_sha256 !== child.authorizing_decision_sha256 ||
          value.child_case_sha256 !== child.case_sha256
        ) {
          throw new Error("交互回执与当前 Child Case 的身份绑定不一致");
        }
        setReceipt(value);
        setState("READY");
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setState("FAIL_CLOSED");
        setError(caught instanceof Error ? caught.message : "三轮交互回执不可用");
      });

    return () => {
      active = false;
    };
  }, [
    child?.authorizing_decision_id,
    child?.authorizing_decision_sha256,
    child?.case_id,
    child?.case_sha256,
    child?.parent_case_id,
    child?.parent_case_sha256,
    incidentsPending,
    incidentsUnavailable,
    retryToken,
    taskId,
  ]);

  if (state === "READY" && receipt) {
    const caseHref = (caseId: string) =>
      `/cases/${encodeURIComponent(caseId)}?task=${encodeURIComponent(taskId)}`;
    return (
      <IncidentInteractionTimeline
        receipt={receipt}
        onOpenParent={() => navigate(caseHref(receipt.parent_case_id))}
        onOpenChild={() => navigate(caseHref(receipt.child_case_id))}
      />
    );
  }

  return (
    <section
      className={`review-interaction-bridge review-interaction-bridge--${state.toLowerCase().replace("_", "-")}`}
      aria-labelledby="review-interaction-bridge-title"
      role={state === "FAIL_CLOSED" ? "alert" : "status"}
    >
      <div className="review-interaction-bridge__icon" aria-hidden="true">
        {state === "LOADING" ? (
          <LoaderCircle className="is-spinning" size={20} />
        ) : state === "FAIL_CLOSED" ? (
          <LockKeyhole size={20} />
        ) : (
          <MessageSquareText size={20} />
        )}
      </div>
      <div>
        <span>AGENT ↔ HUMAN · OBSERVABLE RECEIPT</span>
        <h2 id="review-interaction-bridge-title">
          {state === "LOADING"
            ? "正在核验三轮交互"
            : state === "FAIL_CLOSED"
              ? "交互证据失败关闭"
              : "尚未形成 Child Case 交互"}
        </h2>
        <p>
          {state === "LOADING"
            ? "定位最新 Child Case，并核验 Parent、具名决定与恢复回执。"
            : state === "FAIL_CLOSED"
              ? error
              : "当前 Task 尚未发生“暂停 → 具名决定 → 不可变恢复”；页面不会伪造多轮交互。"}
        </p>
      </div>
      <div>
        <StatusBadge tone={state === "FAIL_CLOSED" ? "danger" : "neutral"} compact>
          {state === "FAIL_CLOSED" ? "FAIL CLOSED" : state === "LOADING" ? "VERIFYING" : "NOT AVAILABLE"}
        </StatusBadge>
        {state === "FAIL_CLOSED" && child ? (
          <ActionButton
            variant="secondary"
            icon={RefreshCw}
            onClick={() => setRetryToken((value) => value + 1)}
          >
            重试只读 GET
          </ActionButton>
        ) : null}
      </div>
    </section>
  );
}

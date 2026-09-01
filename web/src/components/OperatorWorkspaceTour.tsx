import { ChevronLeft, ChevronRight, Sparkles, X } from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";

interface TourStep {
  selector: string;
  eyebrow: string;
  title: string;
  body: string;
}

const steps: TourStep[] = [
  {
    selector: "[data-tour-target='upload']",
    eyebrow: "01 · INPUT",
    title: "上传一组可核验图片",
    body: "选择本地图片或数据集文件。上传期间按钮会锁定并显示进度，原始图像保留在本地工作区。",
  },
  {
    selector: "[data-tour-target='assets']",
    eyebrow: "02 · TRIAGE",
    title: "在资产收件箱中分流",
    body: "这里是真实图片列表，不是静态卡片。选择任意资产都会加载其 SHA、像素统计、标注 revision 与重复关系。",
  },
  {
    selector: "[data-tour-target='canvas']",
    eyebrow: "03 · PIXEL FORENSICS",
    title: "在像素现场取证",
    body: "可框选缺陷、缩放和平移；Shift 拖动读取真实本地预览的光度与梯度剖面，右键 BBox 可进入工单流程。",
  },
  {
    selector: "[data-tour-target='agent']",
    eyebrow: "04 · AGENT",
    title: "查看 Agent 可审计活动",
    body: "运行后逐条查看服务端实际返回的阶段事件、Tool Receipt、治理知识和 Evidence Copilot；不展示或伪造私有思维链。",
  },
  {
    selector: "[data-nav-path='/capa']",
    eyebrow: "05 · HUMAN GATE",
    title: "由人工完成业务闭环",
    body: "创建工单前必须具名并勾选现场复核；随后在 CAPA 队列完成认领和纳入。生产放行权始终保持在人类手中。",
  },
];

interface TourRect {
  left: number;
  top: number;
  width: number;
  height: number;
  bottom: number;
}

interface OperatorWorkspaceTourProps {
  onClose: () => void;
}

export function OperatorWorkspaceTour({ onClose }: OperatorWorkspaceTourProps) {
  const [stepIndex, setStepIndex] = useState(0);
  const [target, setTarget] = useState<TourRect>();
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const step = steps[stepIndex] ?? steps[0]!;

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : undefined;
    const dialog = dialogRef.current;
    dialog?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = [...dialog.querySelectorAll<HTMLElement>(
        "button:not(:disabled), a[href], input:not(:disabled), [tabindex]:not([tabindex='-1'])",
      )];
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0]!;
      const last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, []);

  useLayoutEffect(() => {
    const update = () => {
      const element = document.querySelector<HTMLElement>(step.selector);
      if (!element) {
        setTarget(undefined);
        return;
      }
      const rect = element.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) {
        setTarget(undefined);
        return;
      }
      setTarget({
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
        bottom: rect.bottom,
      });
    };
    update();
    window.addEventListener("resize", update);
    document.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      document.removeEventListener("scroll", update, true);
    };
  }, [step.selector]);

  const focusStyle = useMemo<CSSProperties | undefined>(() => {
    if (!target) return undefined;
    return {
      left: target.left - 6,
      top: target.top - 6,
      width: target.width + 12,
      height: target.height + 12,
    };
  }, [target]);

  const cardStyle = useMemo<CSSProperties>(() => {
    if (!target) return { left: 24, top: 96 };
    const cardWidth = Math.min(360, window.innerWidth - 32);
    const left = Math.max(16, Math.min(target.left, window.innerWidth - cardWidth - 16));
    const roomBelow = window.innerHeight - target.bottom;
    const top = roomBelow >= 230
      ? target.bottom + 14
      : Math.max(16, target.top - 214);
    return { left, top };
  }, [target]);

  const next = () => {
    if (stepIndex === steps.length - 1) {
      onCloseRef.current();
      return;
    }
    setStepIndex((current) => current + 1);
  };

  return createPortal(
    <div className="operator-tour">
      {focusStyle ? <div className="operator-tour__focus" style={focusStyle} /> : <div className="operator-tour__shade" />}
      <section
        ref={dialogRef}
        className="operator-tour__card"
        style={cardStyle}
        role="dialog"
        aria-modal="true"
        aria-labelledby="operator-tour-title"
        aria-describedby="operator-tour-body"
        tabIndex={-1}
      >
        <header>
          <span><Sparkles size={15} /> GOLDEN FLOW</span>
          <button type="button" onClick={onClose} aria-label="关闭评审引导"><X size={15} /></button>
        </header>
        <div className="operator-tour__progress" aria-label={`第 ${stepIndex + 1} 步，共 ${steps.length} 步`}>
          {steps.map((item, index) => (
            <span
              className={index <= stepIndex ? "is-complete" : ""}
              key={item.eyebrow}
              aria-current={index === stepIndex ? "step" : undefined}
            />
          ))}
        </div>
        <small>{step.eyebrow}</small>
        <strong id="operator-tour-title">{step.title}</strong>
        <p id="operator-tour-body" aria-live="polite">{step.body}</p>
        {!target ? <em>当前窄屏未显示目标区域；仍可继续阅读流程。</em> : null}
        <footer>
          <button
            type="button"
            onClick={() => setStepIndex((current) => Math.max(0, current - 1))}
            disabled={stepIndex === 0}
          >
            <ChevronLeft size={14} />上一步
          </button>
          <span>{stepIndex + 1} / {steps.length}</span>
          <button type="button" className="is-primary" onClick={next}>
            {stepIndex === steps.length - 1 ? "开始操作" : "下一步"}<ChevronRight size={14} />
          </button>
        </footer>
      </section>
    </div>,
    document.body,
  );
}

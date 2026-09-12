import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import "../styles/start-surfaces.css";

const steps = [
  { title: "标注与数据准备", description: "导入图片，保存标注和逐样本验收要求。", href: "/workspace?purpose=annotation-rework" },
  { title: "选择起始模型", description: "分开配置 Agent 语言模型与视觉训练模型。", href: "/models" },
  { title: "质检与受控修复", description: "运行检查，复核证据并确认整改动作。", href: "/command-center" },
  { title: "数据池与版本", description: "复核成员，保留返修原因和新旧版本。", href: "/data-pools" },
  { title: "训练、评测与回流", description: "授权训练，复核验证问题，再决定下一轮。", href: "/models?tab=vision" },
];

/** Navigation expresses the workflow, never fabricated execution/completion states. */
export function PlatformWorkflow() {
  return <section className="start-workflow" aria-label="视觉数据与模型工作流">
    <details><summary>第一次使用？查看数据到模型的操作顺序</summary>
      <ol>{steps.map((step) => <li key={step.href}><Link to={step.href}>{step.title}<ArrowRight size={13} /></Link><p>{step.description}</p></li>)}</ol>
      <p>这是操作顺序，不是完成状态。修复说明不会自动变成标注真值；验证集和测试集不会自动回灌训练。</p>
      <Link to="/learning">CPU 参考学习闭环</Link>
    </details>
  </section>;
}

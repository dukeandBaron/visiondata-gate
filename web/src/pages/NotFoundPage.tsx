import { ArrowLeft, FileQuestion } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState, Panel } from "../components/ui";

export function NotFoundPage() {
  return (
    <div className="not-found-page">
      <Panel>
        <EmptyState icon={FileQuestion} title="页面不存在" description="该路由不在当前受控产品导航中。" />
        <Link className="text-action" to="/command-center"><ArrowLeft size={16} /> 返回指挥中心</Link>
      </Panel>
    </div>
  );
}

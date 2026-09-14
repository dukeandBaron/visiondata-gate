import { BrainCircuit, Cpu, Images } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { ProviderCenter } from "../components/ProviderCenter";
import { VisionModelWorkbench } from "../components/VisionModelWorkbench";
import "../styles/model-center.css";

export function ModelCenterPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "vision" ? "vision" : "agent";
  const chooseTab = (value: string) => setParams(current => { const next = new URLSearchParams(current); next.set("tab", value); return next; });
  return <div className="model-center-page"><header className="model-center-header"><span><Cpu size={16} /> MODEL CENTER</span><h1>模型与 API 管理</h1><p>语言模型负责理解和规划，视觉模型负责图像预测与训练。连接状态、运行环境和训练结果分别核验。</p></header>
    <nav className="model-center-tabs" aria-label="模型类型"><button type="button" aria-pressed={tab === "agent"} onClick={() => chooseTab("agent")}><BrainCircuit size={16} />Agent 语言模型 / API</button><button type="button" aria-pressed={tab === "vision"} onClick={() => chooseTab("vision")}><Images size={16} />视觉模型与训练</button><Link to="/platform">返回 Agent 平台</Link></nav>
    {tab === "agent" ? <><div className="model-center-boundary"><strong>本机模型不需要原图外发</strong><p>选择 Ollama 并填写实际已安装的模型 ID。接入外部服务时，只有你明确点击测试或使用该配置，才发起相应请求；不要把配置存在当成连接成功。</p></div><ProviderCenter initialProvider="ollama_local" /></> : <VisionModelWorkbench />}
  </div>;
}

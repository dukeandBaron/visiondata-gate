import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, HashRouter } from "react-router-dom";
import { App } from "./App";
import { ProductProvider } from "./ProductContext";
import { initializeInterfacePreferences } from "./interfacePreferences";
import { publicReplayMode } from "./publicReplay";
import "./styles/tokens.css";
import "./styles/index.css";
import "./styles/hosted-agentteams.css";
import "./styles/evaluation-evidence.css";
import "./styles/semifinal-manifest.css";
import "./styles/public-facade.css";

const root = document.getElementById("root");
if (!root) throw new Error("VisionData Gate root element is missing");

document.documentElement.dataset.runtimeMode = publicReplayMode
  ? "public-replay"
  : "local-workbench";

const Router =
  "__TAURI_INTERNALS__" in window || publicReplayMode
    ? HashRouter
    : BrowserRouter;
initializeInterfacePreferences();

createRoot(root).render(
  <StrictMode>
    <Router>
      <ProductProvider>
        <App />
      </ProductProvider>
    </Router>
  </StrictMode>,
);

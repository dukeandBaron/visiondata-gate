import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, HashRouter } from "react-router-dom";
import { App } from "./App";
import { ProductProvider } from "./ProductContext";
import { initializeInterfacePreferences } from "./interfacePreferences";
import { publicReplayMode } from "./publicReplay";
import { IdentityProvider, useIdentity } from "./IdentityContext";
import { IdentityAccessScreen } from "./components/IdentityAccessScreen";
import "./styles/tokens.css";
import "./styles/index.css";
import "./styles/hosted-agentteams.css";
import "./styles/evaluation-evidence.css";
import "./styles/semifinal-manifest.css";
import "./styles/public-facade.css";
import "./styles/workbench-interface.css";

const root = document.getElementById("root");
if (!root) throw new Error("Workbench root element is missing");

document.documentElement.dataset.runtimeMode = publicReplayMode
  ? "public-replay"
  : "local-workbench";

const Router =
  "__TAURI_INTERNALS__" in window || publicReplayMode
    ? HashRouter
    : BrowserRouter;
initializeInterfacePreferences();

function LocalProduct() {
  const identity = useIdentity();
  if (identity.status !== "authenticated") return <IdentityAccessScreen />;
  return <ProductProvider key={`${identity.user?.user_id ?? "none"}:${identity.generation}`}><App /></ProductProvider>;
}

createRoot(root).render(
  <StrictMode>
    <Router>
      {publicReplayMode ? <ProductProvider><App /></ProductProvider> : <IdentityProvider><LocalProduct /></IdentityProvider>}
    </Router>
  </StrictMode>,
);

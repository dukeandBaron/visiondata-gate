import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { publicReplayMode } from "./publicReplay";

const HomePage = lazy(() => import("./pages/HomePage").then((module) => ({ default: module.HomePage })));
const PilotPlanPage = lazy(() => import("./pages/PilotPlanPage").then((module) => ({ default: module.PilotPlanPage })));
const TaskGuidePage = lazy(() => import("./pages/TaskGuidePage").then((module) => ({ default: module.TaskGuidePage })));
const ComputeHandoffPage = lazy(() => import("./pages/ComputeHandoffPage").then((module) => ({ default: module.ComputeHandoffPage })));
const LearningLoopPage = lazy(() => import("./pages/LearningLoopPage").then((module) => ({ default: module.LearningLoopPage })));
const ModelCenterPage = lazy(() => import("./pages/ModelCenterPage").then((module) => ({ default: module.ModelCenterPage })));
const DataPoolsPage = lazy(() => import("./pages/DataPoolsPage").then((module) => ({ default: module.DataPoolsPage })));
const ImageWorkspacePage = lazy(() => import("./pages/ImageWorkspacePage").then((module) => ({ default: module.ImageWorkspacePage })));
const CommandCenterPage = lazy(() => import("./pages/CommandCenterPage").then((module) => ({ default: module.CommandCenterPage })));
const AgentPlatformPage = lazy(() => import("./pages/AgentPlatformPage").then((module) => ({ default: module.AgentPlatformPage })));
const CasesPage = lazy(() => import("./pages/CasesPage").then((module) => ({ default: module.CasesPage })));
const CaseWorkbenchPage = lazy(() => import("./pages/CaseWorkbenchPage").then((module) => ({ default: module.CaseWorkbenchPage })));
const EvidencePage = lazy(() => import("./pages/EvidencePage").then((module) => ({ default: module.EvidencePage })));
const CapaPage = lazy(() => import("./pages/CapaPage").then((module) => ({ default: module.CapaPage })));
const LineagePage = lazy(() => import("./pages/LineagePage").then((module) => ({ default: module.LineagePage })));
const RunsPage = lazy(() => import("./pages/RunsPage").then((module) => ({ default: module.RunsPage })));
const IntegrationsPage = lazy(() => import("./pages/IntegrationsPage").then((module) => ({ default: module.IntegrationsPage })));
const GovernancePage = lazy(() => import("./pages/GovernancePage").then((module) => ({ default: module.GovernancePage })));
const ReviewPage = lazy(() => import("./pages/ReviewPage").then((module) => ({ default: module.ReviewPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const AccountPage = lazy(() => import("./pages/AccountPage").then((module) => ({ default: module.AccountPage })));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })));
const PublicReplayPage = lazy(() => import("./pages/PublicReplayPage").then((module) => ({ default: module.PublicReplayPage })));
const PublicLandingPage = lazy(() => import("./pages/PublicLandingPage").then((module) => ({ default: module.PublicLandingPage })));

export function App() {
  if (publicReplayMode) {
    return (
      <Suspense fallback={<div className="route-loading" role="status">正在核验公开回放清单…</div>}>
        <Routes>
          <Route path="/" element={<PublicLandingPage />} />
          <Route element={<AppShell />}>
            <Route path="/start" element={<TaskGuidePage />} />
            <Route path="/pilot" element={<PilotPlanPage />} />
            <Route path="/workspace" element={<PublicReplayPage view="workspace" />} />
            <Route path="/command-center" element={<PublicReplayPage view="command-center" />} />
            <Route path="/platform" element={<Navigate to="/" replace />} />
            <Route path="/cases" element={<PublicReplayPage view="cases" />} />
            <Route path="/cases/:caseId" element={<PublicReplayPage view="case-detail" />} />
            <Route path="/evidence" element={<PublicReplayPage view="evidence" />} />
            <Route path="/capa" element={<PublicReplayPage view="capa" />} />
            <Route path="/lineage" element={<PublicReplayPage view="lineage" />} />
            <Route path="/runs" element={<PublicReplayPage view="runs" />} />
            <Route path="/integrations" element={<PublicReplayPage view="integrations" />} />
            <Route path="/governance" element={<PublicReplayPage view="governance" />} />
            <Route path="/review" element={<PublicReplayPage view="review" />} />
            <Route path="/account" element={<PublicReplayPage view="account" />} />
            <Route path="/settings" element={<PublicReplayPage view="settings" />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    );
  }

  return (
    <Suspense fallback={<div className="route-loading" role="status">正在加载工作台模块…</div>}>
      <Routes>
        <Route path="/" element={"__TAURI_INTERNALS__" in window ? <Navigate to="/platform" replace /> : <HomePage />} />
        <Route element={<AppShell />}>
          <Route path="/start" element={<TaskGuidePage />} />
          <Route path="/pilot" element={<PilotPlanPage />} />
          <Route path="/compute" element={<ComputeHandoffPage />} />
          <Route path="/learning" element={<LearningLoopPage />} />
          <Route path="/models" element={<ModelCenterPage />} />
          <Route path="/data-pools" element={<DataPoolsPage />} />
          <Route path="/workspace" element={<ImageWorkspacePage />} />
          <Route path="/command-center" element={<CommandCenterPage />} />
          <Route path="/platform" element={<AgentPlatformPage />} />
          <Route path="/cases" element={<CasesPage />} />
          <Route path="/cases/:caseId" element={<CaseWorkbenchPage />} />
          <Route path="/evidence" element={<EvidencePage />} />
          <Route path="/capa" element={<CapaPage />} />
          <Route path="/lineage" element={<LineagePage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/integrations" element={<IntegrationsPage />} />
          <Route path="/governance" element={<GovernancePage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

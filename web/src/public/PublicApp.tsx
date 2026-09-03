import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { PublicLandingPage } from "../pages/PublicLandingPage";
import { PublicReplayPage } from "../pages/PublicReplayPage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<PublicLandingPage />} />
      <Route element={<AppShell />}>
        <Route path="/workspace" element={<PublicReplayPage view="workspace" />} />
        <Route path="/command-center" element={<PublicReplayPage view="command-center" />} />
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
  );
}

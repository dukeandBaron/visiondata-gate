export interface BrowserSessionBootstrap {
  sessionToken?: string;
}

const fragmentParameter = "visiondata_session";
const storageKey = "visiondata:browser-session-token";
const tokenPattern = /^[A-Za-z0-9_-]{32,128}$/;

function consumeFragmentToken(): string | undefined {
  if (!window.location.hash.startsWith(`#${fragmentParameter}=`)) return undefined;
  const parameters = new URLSearchParams(window.location.hash.slice(1));
  const candidate = parameters.get(fragmentParameter)?.trim() ?? "";
  parameters.delete(fragmentParameter);
  const remaining = parameters.toString();
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}${remaining ? `#${remaining}` : ""}`,
  );
  return tokenPattern.test(candidate) ? candidate : undefined;
}

export function resolveBrowserSessionBootstrap(): BrowserSessionBootstrap {
  const fragmentToken = consumeFragmentToken();
  if (fragmentToken) {
    window.sessionStorage.setItem(storageKey, fragmentToken);
    return { sessionToken: fragmentToken };
  }
  const stored = window.sessionStorage.getItem(storageKey)?.trim() ?? "";
  if (!tokenPattern.test(stored)) {
    window.sessionStorage.removeItem(storageKey);
    return {};
  }
  return { sessionToken: stored };
}

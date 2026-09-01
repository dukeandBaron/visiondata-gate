export type DesktopPlatform = "WEB" | "WINDOWS" | "MACOS" | "LINUX" | "UNKNOWN";

export interface PlatformCapability {
  runtime: "BROWSER" | "TAURI";
  platform: DesktopPlatform;
  localFilePicker: "BROWSER_CONTROLLED" | "DESKTOP_BRIDGE_REQUIRED";
  secureCredentialStore: "NOT_USED_BY_WEB_UI" | "DESKTOP_BRIDGE_REQUIRED";
  desktopPackaging: "NOT_BUNDLED" | "AVAILABLE";
}

export interface DesktopRuntimeConfig {
  apiBaseUrl: string;
  sessionToken: string;
  dataRoot: string;
  configFile: string;
  sampleDataRoot: string;
}

let desktopRuntimePromise: Promise<DesktopRuntimeConfig | undefined> | undefined;

export function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

export function resolveDesktopRuntimeConfig(): Promise<DesktopRuntimeConfig | undefined> {
  if (!isTauriRuntime()) return Promise.resolve(undefined);
  desktopRuntimePromise ??= import("@tauri-apps/api/core").then(({ invoke }) =>
    invoke<DesktopRuntimeConfig>("desktop_runtime_config"),
  );
  return desktopRuntimePromise;
}

export async function openDesktopConfigDirectory(): Promise<void> {
  if (!isTauriRuntime()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("open_desktop_config_directory");
}

function detectPlatform(): DesktopPlatform {
  const navWithUserAgentData = navigator as Navigator & {
    userAgentData?: { platform?: string };
  };
  const platform = navWithUserAgentData.userAgentData?.platform ?? navigator.platform ?? "";
  const normalized = platform.toLowerCase();
  if (normalized.includes("win")) return "WINDOWS";
  if (normalized.includes("mac")) return "MACOS";
  if (normalized.includes("linux")) return "LINUX";
  return normalized ? "UNKNOWN" : "WEB";
}

export function getPlatformCapability(): PlatformCapability {
  const tauriAvailable = isTauriRuntime();
  return {
    runtime: tauriAvailable ? "TAURI" : "BROWSER",
    platform: detectPlatform(),
    localFilePicker: tauriAvailable ? "DESKTOP_BRIDGE_REQUIRED" : "BROWSER_CONTROLLED",
    secureCredentialStore: tauriAvailable ? "DESKTOP_BRIDGE_REQUIRED" : "NOT_USED_BY_WEB_UI",
    desktopPackaging: tauriAvailable ? "AVAILABLE" : "NOT_BUNDLED",
  };
}

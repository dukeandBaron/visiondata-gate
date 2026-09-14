import { useEffect, useState } from "react";

export type AccentPalette = "graphite" | "violet-cyan" | "cyan-lime" | "coral-violet";
export type InterfaceDensity = "comfortable" | "compact";

export interface InterfacePreferences {
  accent: AccentPalette;
  density: InterfaceDensity;
  reduceMotion: boolean;
}

const preferenceStorageKey = "visiondata:interface-preferences:v2";
const legacyPreferenceStorageKey = "visiondata:interface-preferences";
const preferenceEvent = "visiondata:interface-preferences-changed";

const defaults: InterfacePreferences = {
  accent: "graphite",
  density: "comfortable",
  reduceMotion: false,
};

export function readInterfacePreferences(): InterfacePreferences {
  try {
    const saved = window.localStorage.getItem(preferenceStorageKey);
    const parsed = JSON.parse(saved ?? window.localStorage.getItem(legacyPreferenceStorageKey) ?? "{}") as Partial<InterfacePreferences> | null;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return defaults;
    return {
      accent: saved && ["graphite", "violet-cyan", "cyan-lime", "coral-violet"].includes(parsed.accent ?? "")
        ? parsed.accent as AccentPalette
        : defaults.accent,
      density: parsed.density === "compact" ? "compact" : defaults.density,
      reduceMotion: parsed.reduceMotion === true,
    };
  } catch {
    return defaults;
  }
}

export function applyInterfacePreferences(preferences: InterfacePreferences): void {
  document.documentElement.dataset.accent = preferences.accent;
  document.documentElement.dataset.density = preferences.density;
  document.documentElement.dataset.reduceMotion = preferences.reduceMotion ? "true" : "false";
}

export function saveInterfacePreferences(preferences: InterfacePreferences): InterfacePreferences {
  window.localStorage.setItem(preferenceStorageKey, JSON.stringify(preferences));
  applyInterfacePreferences(preferences);
  window.dispatchEvent(new CustomEvent(preferenceEvent, { detail: preferences }));
  return preferences;
}

export function initializeInterfacePreferences(): void {
  applyInterfacePreferences(readInterfacePreferences());
}

export function useInterfacePreferences() {
  const [preferences, setPreferences] = useState<InterfacePreferences>(readInterfacePreferences);

  useEffect(() => {
    const update = (event: Event) => {
      const detail = (event as CustomEvent<InterfacePreferences>).detail;
      const next = detail ?? readInterfacePreferences();
      applyInterfacePreferences(next);
      setPreferences(next);
    };
    window.addEventListener(preferenceEvent, update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener(preferenceEvent, update);
      window.removeEventListener("storage", update);
    };
  }, []);

  const updatePreferences = (patch: Partial<InterfacePreferences>) => {
    const next = { ...preferences, ...patch };
    saveInterfacePreferences(next);
    setPreferences(next);
  };

  return { preferences, updatePreferences };
}

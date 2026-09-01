import { useEffect, useState } from "react";

export interface LocalOperatorProfile {
  displayName: string;
  role: string;
  team: string;
}

const profileStorageKey = "visiondata:local-operator-profile";
const profileEvent = "visiondata:local-profile-changed";

const defaultProfile: LocalOperatorProfile = {
  displayName: "本地操作者",
  role: "工业视觉工程师",
  team: "Vision Lab",
};

export function readLocalOperatorProfile(): LocalOperatorProfile {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(profileStorageKey) ?? "{}") as Partial<LocalOperatorProfile>;
    return {
      displayName: parsed.displayName?.trim() || defaultProfile.displayName,
      role: parsed.role?.trim() || defaultProfile.role,
      team: parsed.team?.trim() || defaultProfile.team,
    };
  } catch {
    return defaultProfile;
  }
}

export function saveLocalOperatorProfile(profile: LocalOperatorProfile): LocalOperatorProfile {
  const normalized = {
    displayName: profile.displayName.trim() || defaultProfile.displayName,
    role: profile.role.trim() || defaultProfile.role,
    team: profile.team.trim() || defaultProfile.team,
  };
  window.localStorage.setItem(profileStorageKey, JSON.stringify(normalized));
  window.dispatchEvent(new CustomEvent(profileEvent, { detail: normalized }));
  return normalized;
}

export function operatorInitials(profile: LocalOperatorProfile): string {
  const asciiWords = profile.displayName.match(/[A-Za-z0-9]+/g);
  if (asciiWords?.length) return asciiWords.slice(0, 2).map((word) => word[0]).join("").toUpperCase();
  return Array.from(profile.displayName).filter((character) => character.trim()).slice(0, 2).join("");
}

export function useLocalOperatorProfile() {
  const [profile, setProfile] = useState<LocalOperatorProfile>(readLocalOperatorProfile);

  useEffect(() => {
    const update = (event: Event) => {
      const detail = (event as CustomEvent<LocalOperatorProfile>).detail;
      setProfile(detail ?? readLocalOperatorProfile());
    };
    window.addEventListener(profileEvent, update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener(profileEvent, update);
      window.removeEventListener("storage", update);
    };
  }, []);

  return { profile, saveProfile: saveLocalOperatorProfile };
}

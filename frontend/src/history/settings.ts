export type FrontendSettings = { saveHistory: boolean; showRetrievalDetails: boolean };
const KEY = "repo-cartographer.settings";
export const defaultSettings: FrontendSettings = { saveHistory: true, showRetrievalDetails: false };

export function loadSettings(): FrontendSettings {
  if (typeof window === "undefined") return defaultSettings;
  try {
    return {
      ...defaultSettings,
      ...JSON.parse(localStorage.getItem(KEY) ?? "{}"),
    } as FrontendSettings;
  } catch {
    return defaultSettings;
  }
}
export function saveSettings(settings: FrontendSettings) {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    /* optional storage */
  }
}

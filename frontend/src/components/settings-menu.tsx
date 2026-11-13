"use client";

import { useEffect, useState } from "react";
import { clearHistory } from "@/history/store";
import {
  defaultSettings,
  loadSettings,
  saveSettings,
  type FrontendSettings,
} from "@/history/settings";

export function SettingsMenu({
  onChange,
  onClear,
  forceOpen = false,
  onOpenChange,
}: {
  onChange: (settings: FrontendSettings) => void;
  onClear: () => void;
  forceOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState(defaultSettings);
  useEffect(() => setSettings(loadSettings()), []);
  useEffect(() => {
    if (forceOpen) {
      setOpen(true);
      onOpenChange?.(true);
    }
  }, [forceOpen, onOpenChange]);
  const update = (change: Partial<FrontendSettings>) => {
    const next = { ...settings, ...change };
    setSettings(next);
    saveSettings(next);
    onChange(next);
  };
  const toggle = (next: boolean) => {
    setOpen(next);
    onOpenChange?.(next);
  };
  return (
    <div className="settings-wrap">
      <button
        className="icon-button"
        type="button"
        aria-label="Open settings"
        onClick={() => toggle(!open)}
      >
        ⚙
      </button>
      {open && (
        <div className="settings-menu" role="dialog" aria-label="Settings">
          <strong>Settings</strong>
          <label>
            <input
              type="checkbox"
              checked={settings.saveHistory}
              onChange={(event) => update({ saveHistory: event.target.checked })}
            />{" "}
            Save history on this device
          </label>
          <label>
            <input
              type="checkbox"
              checked={settings.showRetrievalDetails}
              onChange={(event) => update({ showRetrievalDetails: event.target.checked })}
            />{" "}
            Show retrieval details
          </label>
          <p>History stays on this device. It is never sent to the backend.</p>
          <button
            type="button"
            onClick={() => {
              void clearHistory();
              onClear();
              toggle(false);
            }}
          >
            Clear history
          </button>
        </div>
      )}
    </div>
  );
}

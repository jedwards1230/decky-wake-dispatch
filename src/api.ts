// Typed bindings for the Wake Dispatch backend. Mirrors docs/CONTRACT.md (contract v1).
import { callable } from "@decky/api";

export type Trigger = "manual" | "boot" | "resume";
export type AutoTrigger = "boot" | "resume";

export interface Device {
  id: string;
  name: string;
  mac: string;
  broadcast: string;
  port: number;
  host: string | null;
  status_port: number | null;
  secureon: string | null;
  auto: AutoTrigger[];
  home_gateway: string | null;
}

export interface DeviceResult {
  name: string;
  status: "sent" | "error" | "skipped";
  error?: string;
}

export interface DispatchRecord {
  trigger: Trigger;
  at: number;
  outcome: "sent" | "partial" | "failed" | "skipped" | "no_network";
  reason: string | null;
  results: Record<string, DeviceResult>;
}

export interface State {
  last: DispatchRecord | null;
  automation: { boot: DispatchRecord | null; resume: DispatchRecord | null };
}

export type Status = "awake" | "asleep" | "unknown";

export interface Neighbour {
  ip: string;
  mac: string;
  iface: string;
  hostname: string | null;
}

export interface Network {
  iface: string;
  gateway: string;
}

export type Saved =
  | { ok: true; devices: Device[] }
  | { ok: false; error: string; field?: string; index?: number };

export type MacValidation = { ok: true; mac: string } | { ok: false; error: string };

export type ImportMode = "replace" | "merge";

export type UpdateStatus = "disabled" | "unchecked" | "current" | "available" | "unavailable";

export interface UpdateRelease {
  version: string;
  url: string;
  sha256: string; // 64 lowercase hex characters, no "sha256:" prefix
  size: number;
}

export interface UpdateInfo {
  enabled: boolean;
  installed: string | null;
  status: UpdateStatus;
  latest: string | null;
  release: UpdateRelease | null;
  checked_at: number | null;
  error: string | null;
  throttled: boolean;
  manual_url: string;
}

export type UpdateCheckSaved = { ok: true; enabled: boolean } | { ok: false; error: string };

/** Event emitted by the backend after every wake, with a DispatchRecord payload. */
export const DISPATCHED_EVENT = "dispatched";

export const listDevices = callable<[], Device[]>("list_devices");
export const saveDevices = callable<[devices: Partial<Device>[]], Saved>("save_devices");
export const validateMac = callable<[mac: string], MacValidation>("validate_mac");
export const wake = callable<[ids: string[] | null, trigger: Trigger], DispatchRecord>("wake");
export const status = callable<[ids: string[] | null], Record<string, Status>>("status");
export const getState = callable<[], State>("get_state");
export const currentNetwork = callable<[], Network | null>("current_network");
export const neighbours = callable<[], Neighbour[]>("neighbours");
export const exportConfig = callable<[], string>("export_config");
export const importConfig = callable<[text: string, mode: ImportMode], Saved>("import_config");
export const updateInfo = callable<[force: boolean], UpdateInfo>("update_info");
export const setUpdateCheck = callable<[enabled: boolean], UpdateCheckSaved>("set_update_check");

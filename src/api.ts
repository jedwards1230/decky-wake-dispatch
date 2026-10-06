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

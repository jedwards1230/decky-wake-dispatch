// Module-level device list shared by the panel and the modals. Modals opened
// with showModal() live outside the panel's React tree (and can outlive it), so
// they write through these functions and the panel re-renders via useDevices().
import { useEffect, useState } from "react";

import {
  currentNetwork,
  listDevices,
  saveDevices,
  status,
  wake,
  type Device,
  type DispatchRecord,
  type Saved,
  type Status,
} from "./api";
import {
  checkableDevices,
  scheduleNoReplyCheck,
  toastDispatch,
  toastError,
  toastInfo,
  withManualWake,
} from "./notify";
import { S, TOAST } from "./strings";

export interface DevicesSnapshot {
  devices: Device[] | null; // null = not loaded yet
  failed: boolean;
}

let snapshot: DevicesSnapshot = { devices: null, failed: false };
const subscribers = new Set<() => void>();
const statusRefreshSubscribers = new Set<() => void>();

function publish(next: DevicesSnapshot): void {
  snapshot = next;
  for (const fn of [...subscribers]) fn();
}

export async function loadDevices(): Promise<void> {
  try {
    publish({ devices: await listDevices(), failed: false });
  } catch (e) {
    console.error("[Wake Dispatch] list_devices failed", e);
    publish({ devices: snapshot.devices, failed: snapshot.devices === null });
  }
}

export function useDevices(): DevicesSnapshot {
  const [state, setState] = useState(snapshot);
  useEffect(() => {
    const update = () => setState(snapshot);
    subscribers.add(update);
    update();
    void loadDevices();
    return () => {
      subscribers.delete(update);
    };
  }, []);
  return state;
}

/** Ask any mounted status poller to refresh now. */
export function requestStatusRefresh(): void {
  for (const fn of [...statusRefreshSubscribers]) fn();
}

export function onStatusRefreshRequested(fn: () => void): () => void {
  statusRefreshSubscribers.add(fn);
  return () => {
    statusRefreshSubscribers.delete(fn);
  };
}

/** A save result plus whether a validation error points at the edited device. */
export type SaveOutcome = Saved & { atEdited?: boolean };

async function writeList(list: Partial<Device>[], editedIndex?: number): Promise<SaveOutcome> {
  const saved = await saveDevices(list);
  if (saved.ok) {
    publish({ devices: saved.devices, failed: false });
    return saved;
  }
  return { ...saved, atEdited: editedIndex !== undefined && (saved.index === undefined || saved.index === editedIndex) };
}

/** Insert (empty id) or replace (matching id) one device, saving the whole list. Throws on backend failure. */
export async function saveDevice(draft: Partial<Device>): Promise<SaveOutcome> {
  const current = await listDevices();
  const index = draft.id ? current.findIndex((d) => d.id === draft.id) : -1;
  const list: Partial<Device>[] = [...current];
  if (index >= 0) {
    list[index] = { ...current[index], ...draft };
    return writeList(list, index);
  }
  list.push({ ...draft, id: "" });
  return writeList(list, list.length - 1);
}

/** Remove one device. Toasts on failure. */
export async function deleteDevice(id: string): Promise<void> {
  try {
    const current = await listDevices();
    const result = await writeList(current.filter((d) => d.id !== id));
    if (!result.ok) toastInfo(S.deleteFailed, result.error);
  } catch (e) {
    toastError(S.deleteFailed, e);
  }
}

/** Accept a list that import_config already saved. */
export function replaceDevices(devices: Device[]): void {
  publish({ devices, failed: false });
}

/** True when a target has a home network set and the current gateway (best effort) differs. */
async function offHomeNetwork(targets: Device[]): Promise<boolean> {
  const gateways = targets.map((d) => d.home_gateway).filter((g): g is string => g !== null);
  if (gateways.length === 0) return false;
  try {
    const net = await currentNetwork();
    return net !== null && gateways.some((g) => g !== net.gateway);
  } catch {
    return false;
  }
}

/**
 * Manual wake: always sends. Toasts once (the event path stands aside while this
 * runs) and schedules the follow-up status check. A status snapshot taken
 * alongside the wake tells the follow-up which devices were already awake.
 */
export async function wakeManual(ids: string[] | null): Promise<DispatchRecord | null> {
  const devices = snapshot.devices ?? [];
  const targets = ids === null ? devices : devices.filter((d) => ids.includes(d.id));
  const checkIds = checkableDevices(null, targets).map((d) => d.id);
  const before: Promise<Record<string, Status>> =
    checkIds.length > 0 ? status(checkIds).catch(() => ({})) : Promise.resolve({});
  const offHome = offHomeNetwork(targets);

  return withManualWake(async () => {
    let record: DispatchRecord;
    try {
      record = await wake(ids, "manual");
    } catch (e) {
      toastError(TOAST.couldntSend, e);
      return null;
    }
    const sentSomething = record.outcome === "sent" || record.outcome === "partial";
    toastDispatch(record, sentSomething && (await offHome) ? TOAST.offHomeNetwork : undefined);
    setTimeout(requestStatusRefresh, 4_000);
    scheduleNoReplyCheck(record, devices, before, requestStatusRefresh);
    return record;
  });
}

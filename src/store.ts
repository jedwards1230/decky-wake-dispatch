// Module-level device list shared by the panel and the modals. Modals opened
// with showModal() live outside the panel's React tree (and can outlive it), so
// they write through these functions and the panel re-renders via useDevices().
import { useEffect, useState } from "react";

import { listDevices, saveDevices, wake, type Device, type DispatchRecord, type Saved } from "./api";
import { scheduleNoReplyCheck, toastDispatch, toastError, toastInfo } from "./notify";

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
    if (!result.ok) toastInfo("Couldn't delete the device", result.error);
  } catch (e) {
    toastError("Couldn't delete the device", e);
  }
}

/** Accept a list that import_config already saved. */
export function replaceDevices(devices: Device[]): void {
  publish({ devices, failed: false });
}

/** Manual wake: always sends. Toasts once (deduplicated against the event) and schedules the no-reply check. */
export async function wakeManual(ids: string[] | null): Promise<DispatchRecord | null> {
  let record: DispatchRecord;
  try {
    record = await wake(ids, "manual");
  } catch (e) {
    toastError("Couldn't send the wake", e);
    return null;
  }
  toastDispatch(record);
  setTimeout(requestStatusRefresh, 4_000);
  scheduleNoReplyCheck(record, snapshot.devices ?? [], requestStatusRefresh);
  return record;
}

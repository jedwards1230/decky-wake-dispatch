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
  type UpdateInfo,
} from "./api";
import {
  cancelPendingTimers,
  checkableDevices,
  later,
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

/**
 * A save result plus whether a validation error points at the edited device, and
 * on success the id of the saved device (new devices get theirs from the backend).
 */
export type SaveOutcome = Saved & { atEdited?: boolean; savedId?: string };

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
    // A draft without home_gateway_mac lets the backend keep or capture it
    // (docs/CONTRACT.md §4); the saved value must not ride along unasked.
    if (!("home_gateway_mac" in draft)) delete list[index].home_gateway_mac;
    const result = await writeList(list, index);
    return result.ok ? { ...result, savedId: draft.id } : result;
  }
  list.push({ ...draft, id: "" });
  const result = await writeList(list, list.length - 1);
  if (!result.ok) return result;
  const before = new Set(current.map((d) => d.id));
  const added = result.devices.find((d) => !before.has(d.id)) ?? result.devices[result.devices.length - 1];
  return { ...result, savedId: added?.id };
}

/** The row that should take focus once `id` is gone: the next one, else the previous one. */
export function neighbourOf(id: string): string | null {
  const list = snapshot.devices ?? [];
  const i = list.findIndex((d) => d.id === id);
  if (i < 0) return null;
  return list[i + 1]?.id ?? list[i - 1]?.id ?? null;
}

// Where focus should land after a modal closes: a device id (its Wake button) or
// ADD_DEVICE_FOCUS. The sequence number makes a repeat request for the same id fire again.
export const ADD_DEVICE_FOCUS = "__add_device__";
/** The Update button, or Check for updates when the Update row is gone. */
export const UPDATE_FOCUS = "__update__";

export interface FocusRequest {
  id: string;
  seq: number;
}

let focusRequest: FocusRequest | null = null;
const focusSubscribers = new Set<() => void>();

// A request only means "right after this modal closes": it expires, so reopening
// the Quick Access menu later starts from Steam's usual first focus again and
// preferredFocus doesn't stick to the last-edited row.
const FOCUS_REQUEST_MS = 2_000;
let focusSeq = 0;

function publishFocus(): void {
  for (const fn of [...focusSubscribers]) fn();
}

export function requestFocus(id: string): void {
  const seq = ++focusSeq;
  focusRequest = { id, seq };
  publishFocus();
  later(() => {
    if (focusRequest?.seq !== seq) return;
    focusRequest = null;
    publishFocus();
  }, FOCUS_REQUEST_MS);
}

export function useFocusRequest(): FocusRequest | null {
  const [state, setState] = useState(focusRequest);
  useEffect(() => {
    const update = () => setState(focusRequest);
    focusSubscribers.add(update);
    update();
    return () => {
      focusSubscribers.delete(update);
    };
  }, []);
  return state;
}

// Per-device outcome of the last manual wake, shown in the row for a while.
export type WakeResultPhase = "sent" | "checking" | "awake" | "asleep";
export interface WakeResult {
  at: number; // ms, when the wake was sent
  phase: WakeResultPhase;
}
export const WAKE_RESULT_MS = 10 * 60_000;

const wakeResults = new Map<string, WakeResult>();
const wakeResultSubscribers = new Set<() => void>();

function publishWakeResults(): void {
  for (const fn of [...wakeResultSubscribers]) fn();
}

let lastWakeToken = 0;

/** The wake's time in ms, made unique so two wakes never share a token. */
function nextWakeToken(): number {
  lastWakeToken = Math.max(Date.now(), lastWakeToken + 1);
  return lastWakeToken;
}

/** Start a device's result for the wake sent at `at` (ms). */
function startWakeResult(id: string, at: number, phase: WakeResultPhase): void {
  wakeResults.set(id, { at, phase });
  publishWakeResults();
}

/** Whether `at` is still the device's latest wake (a newer wake replaces the result). */
function isLatestWake(id: string, at: number): boolean {
  return wakeResults.get(id)?.at === at;
}

/** Update the result of the wake sent at `at`; a follow-up for an older wake is ignored. */
function updateWakeResult(id: string, at: number, phase: WakeResultPhase): void {
  if (!isLatestWake(id, at)) return;
  wakeResults.set(id, { at, phase });
  publishWakeResults();
}

/** The device's last manual-wake result while it is younger than WAKE_RESULT_MS. */
export function useWakeResult(id: string): WakeResult | null {
  const [state, setState] = useState(() => wakeResults.get(id) ?? null);
  useEffect(() => {
    const update = () => setState(wakeResults.get(id) ?? null);
    wakeResultSubscribers.add(update);
    update();
    return () => {
      wakeResultSubscribers.delete(update);
    };
  }, [id]);
  return state;
}

/** Remove one device. Toasts on failure; resolves true only when it was removed. */
export async function deleteDevice(id: string): Promise<boolean> {
  try {
    const current = await listDevices();
    const result = await writeList(current.filter((d) => d.id !== id));
    if (result.ok) return true;
    toastInfo(S.deleteFailed, result.error);
  } catch (e) {
    toastError(S.deleteFailed, e);
  }
  return false;
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

// In-flight manual wakes, so a second press (row or Wake all) never sends twice
// and every button can show "Sending…" while its wake is pending.
const wakingIds = new Set<string>();
let wakingAll = false;
const wakingSubscribers = new Set<() => void>();

function publishWaking(): void {
  for (const fn of [...wakingSubscribers]) fn();
}

export interface WakingState {
  all: boolean;
  isWaking: (id: string) => boolean;
}

function wakingState(): WakingState {
  const ids = new Set(wakingIds);
  return { all: wakingAll, isWaking: (id) => ids.has(id) };
}

/** Re-renders when a manual wake starts or settles. */
export function useWaking(): WakingState {
  const [state, setState] = useState(wakingState);
  useEffect(() => {
    const update = () => setState(wakingState());
    wakingSubscribers.add(update);
    update();
    return () => {
      wakingSubscribers.delete(update);
    };
  }, []);
  return state;
}

/**
 * Manual wake: always sends. Toasts once (the event path stands aside while this
 * runs) and schedules the follow-up status check. A status snapshot taken
 * alongside the wake tells the follow-up which devices were already awake.
 * Devices already being woken are left out; if nothing is left, nothing is sent.
 */
export async function wakeManual(ids: string[] | null): Promise<DispatchRecord | null> {
  if (ids === null ? wakingAll : ids.every((id) => wakingIds.has(id))) return null;
  const devices = snapshot.devices ?? [];
  const pendingIds = (ids ?? devices.map((d) => d.id)).filter((id) => !wakingIds.has(id));
  if (pendingIds.length === 0) return null;
  // "All" stays null when nothing else is in flight, so devices the panel hasn't
  // loaded yet are still included.
  const sendIds = ids === null && wakingIds.size === 0 ? null : pendingIds;

  const isAll = ids === null;
  if (isAll) wakingAll = true;
  for (const id of pendingIds) wakingIds.add(id);
  publishWaking();
  try {
    return await sendManualWake(sendIds, devices.filter((d) => pendingIds.includes(d.id)), devices);
  } finally {
    if (isAll) wakingAll = false;
    for (const id of pendingIds) wakingIds.delete(id);
    publishWaking();
  }
}

async function sendManualWake(
  ids: string[] | null,
  targets: Device[],
  devices: Device[],
): Promise<DispatchRecord | null> {
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
    const checkable = new Set(checkableDevices(record, devices).map((d) => d.id));
    toastDispatch(record, sentSomething && (await offHome) ? TOAST.offHomeNetwork : undefined, checkable.size > 0);
    // One token per wake: follow-ups only touch results (and toast for devices)
    // this wake still owns, so a slow check can't overwrite a newer wake's row.
    const at = nextWakeToken();
    for (const [id, result] of Object.entries(record.results)) {
      if (result.status === "sent") startWakeResult(id, at, checkable.has(id) ? "checking" : "sent");
    }
    later(requestStatusRefresh, 4_000);
    scheduleNoReplyCheck(record, devices, before, requestStatusRefresh, {
      isCurrent: (id) => isLatestWake(id, at),
      onResult: (id, value, final) => {
        if (value === "awake") updateWakeResult(id, at, "awake");
        else if (value === "unknown") updateWakeResult(id, at, "sent");
        else if (final) updateWakeResult(id, at, "asleep");
      },
    });
    return record;
  });
}

/**
 * Plugin unload: cancel pending follow-up checks and status refreshes and drop
 * per-session state, so nothing fires or toasts after the plugin is gone.
 */
export function cancelPendingChecks(): void {
  cancelPendingTimers();
  wakeResults.clear();
  wakingIds.clear();
  wakingAll = false;
  focusRequest = null;
  forcedUpdate = null;
  detachWindowFocus?.();
}

// The last Check for updates answer. With the daily check off, update_info(false)
// on the next panel open says "disabled" and would hide what the user just
// checked, so the panel keeps showing this for the rest of the session.
let forcedUpdate: UpdateInfo | null = null;

export function rememberForcedUpdate(info: UpdateInfo): void {
  forcedUpdate = info;
}

export function lastForcedUpdate(): UpdateInfo | null {
  return forcedUpdate;
}

let detachWindowFocus: (() => void) | null = null;
const WINDOW_FOCUS_WAIT_MS = 120_000;

/**
 * Request focus on `id` when `win` gets window focus back, once, within two
 * minutes. Decky's install prompt opens in Steam's main window and gives no close
 * callback, so the Quick Access window regaining focus is the signal that it closed.
 */
export function focusWhenWindowReturns(win: Window, id: string): void {
  onWindowFocusOnce(win, () => requestFocus(id));
}

/**
 * Run `fn` the next time `win` gets window focus, once, within two minutes.
 * Menus and prompts that open outside the Quick Access window give no close
 * callback; the window regaining focus is the signal. Only one waits at a time
 * (a new one replaces the old), and plugin unload detaches it. Returns detach.
 */
export function onWindowFocusOnce(win: Window, fn: () => void): () => void {
  detachWindowFocus?.();
  const onFocus = () => {
    detach();
    fn();
  };
  const detach = () => {
    win.removeEventListener("focus", onFocus);
    if (detachWindowFocus === detach) detachWindowFocus = null;
  };
  win.addEventListener("focus", onFocus);
  detachWindowFocus = detach;
  later(detach, WINDOW_FOCUS_WAIT_MS);
  return detach;
}

// Toasts. One toast per DispatchRecord:
// - Manual wakes started from this panel are toasted by the wake path (it can
//   add context such as "not on your home network"); while one is in flight the
//   "dispatched" event skips manual records.
// - Everything else is toasted from the event.
// A short-lived key set makes a second toast for the same record a no-op.
import { toaster } from "@decky/api";

import type { Device, DispatchRecord } from "./api";
import { nameList, resultsWith, triggerLabel } from "./format";
import { S, TOAST, names } from "./strings";

const SEEN_TTL_MS = 60_000;

const seen = new Map<string, number>();
let manualInFlight = 0;

// Every pending timer, so plugin unload can cancel follow-ups instead of
// letting them fire (and toast) into a torn-down plugin.
const timers = new Set<ReturnType<typeof setTimeout>>();

/** setTimeout that cancelPendingTimers() can cancel. */
export function later(fn: () => void, ms: number): void {
  const id = setTimeout(() => {
    timers.delete(id);
    fn();
  }, ms);
  timers.add(id);
}

/** Cancel every pending follow-up and forget which records were toasted. */
export function cancelPendingTimers(): void {
  for (const id of timers) clearTimeout(id);
  timers.clear();
  seen.clear();
}

function recordKey(record: DispatchRecord): string {
  return `${record.trigger}|${record.at}|${record.outcome}|${Object.keys(record.results).sort().join(",")}`;
}

function firstSeen(record: DispatchRecord): boolean {
  const now = Date.now();
  for (const [key, at] of seen) {
    if (now - at > SEEN_TTL_MS) seen.delete(key);
  }
  const key = recordKey(record);
  if (seen.has(key)) return false;
  seen.set(key, now);
  return true;
}

function toast(title: string, body: string): void {
  try {
    toaster.toast({ title, body });
  } catch (e) {
    console.error("[Wake Dispatch] toast failed", e);
  }
}

/**
 * Plain-language toast for a dispatch, or null when nothing is worth saying.
 * "Sent" never claims the PC woke: a manual wake says a status check follows
 * (`checking`) or that starting can take a while.
 */
export function describeDispatch(
  record: DispatchRecord,
  note?: string,
  checking = false,
): { title: string; body: string } | null {
  const sent = resultsWith(record, "sent");
  const failed = resultsWith(record, "error");
  const auto = record.trigger !== "manual";
  const context = auto
    ? TOAST.automaticContext(triggerLabel(record.trigger))
    : checking
      ? sent.length > 1
        ? TOAST.checkingAwakeMany
        : TOAST.checkingAwake
      : TOAST.mayTakeAMinute;

  switch (record.outcome) {
    case "sent":
      return {
        title: sent.length === 1 ? TOAST.sentToOne(sent[0].name) : TOAST.sentTo(sent.length),
        body: note ?? context,
      };
    case "partial":
      return {
        title: TOAST.sentSome(sent.length, sent.length + failed.length),
        body: note ?? TOAST.couldntSendTo(nameList(failed), failed[0]?.error),
      };
    case "failed":
      return {
        title: failed.length === 1 ? TOAST.couldntWake(failed[0].name) : TOAST.couldntSend,
        body: failed[0]?.error ?? TOAST.checkConnected,
      };
    case "no_network":
      // Automatic no-network runs show in the panel's "Last automatic wake" line.
      if (auto) return null;
      return { title: TOAST.noNetwork, body: TOAST.noNetworkBody };
    case "skipped":
    default:
      // Automatic skips (not on home network, nobody opted in) also stay in the
      // panel line, so a handheld that resumes often doesn't spam notifications.
      if (auto) return null;
      return { title: TOAST.nothingSent, body: record.reason ?? TOAST.nothingToWake };
  }
}

export function toastDispatch(record: DispatchRecord, note?: string, checking = false): void {
  if (!firstSeen(record)) return;
  const msg = describeDispatch(record, note, checking);
  if (msg) toast(msg.title, msg.body);
}

/** Handler for the backend "dispatched" event. */
export function toastDispatchEvent(record: DispatchRecord): void {
  if (record.trigger === "manual" && manualInFlight > 0) return;
  toastDispatch(record);
}

/** Wrap a manual wake so the event path leaves its toast to the caller. */
export async function withManualWake<T>(fn: () => Promise<T>): Promise<T> {
  manualInFlight += 1;
  try {
    return await fn();
  } finally {
    manualInFlight -= 1;
  }
}

export function toastError(title: string, e: unknown): void {
  console.error(`[Wake Dispatch] ${title}`, e);
  toast(title, S.backendError);
}

export function toastInfo(title: string, body: string): void {
  toast(title, body);
}

/** Devices whose wake was sent and that have a status host + port. */
export function checkableDevices(record: DispatchRecord | null, devices: Device[]): Device[] {
  return devices.filter(
    (d) => (record === null || record.results[d.id]?.status === "sent") && d.host && d.status_port !== null,
  );
}

/** "<name> is awake", as soon as a polled device answers. */
export function toastAwake(name: string): void {
  toast(TOAST.isAwake(name, false), TOAST.isAwakeBody);
}

/** One combined "hasn't woken up" toast at the confirmation deadline. */
export function toastNotWoken(list: readonly string[]): void {
  if (list.length === 0) return;
  toast(TOAST.notWoken(names(list), list.length > 1), TOAST.notWokenBody);
}

// Toasts. One toast per DispatchRecord:
// - Manual wakes started from this panel are toasted by the wake path (it can
//   add context such as "not on your home network"); while one is in flight the
//   "dispatched" event skips manual records.
// - Everything else is toasted from the event.
// A short-lived key set makes a second toast for the same record a no-op.
import { toaster } from "@decky/api";

import { status, type Device, type DispatchRecord, type Status } from "./api";
import { errorText, nameList, resultsWith, triggerLabel } from "./format";
import { PLUGIN_NAME, S, TOAST, names } from "./strings";

const FIRST_CHECK_MS = 20_000;
const SECOND_CHECK_MS = 45_000;
const SEEN_TTL_MS = 60_000;

const seen = new Map<string, number>();
let manualInFlight = 0;

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

/** Plain-language toast for a dispatch, or null when nothing is worth saying. */
export function describeDispatch(record: DispatchRecord, note?: string): { title: string; body: string } | null {
  const sent = resultsWith(record, "sent");
  const failed = resultsWith(record, "error");
  const auto = record.trigger !== "manual";
  const context = auto ? TOAST.automaticContext(triggerLabel(record.trigger)) : PLUGIN_NAME;

  switch (record.outcome) {
    case "sent":
      return {
        title: sent.length === 1 ? TOAST.woke(sent[0].name) : TOAST.sentTo(sent.length),
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

export function toastDispatch(record: DispatchRecord, note?: string): void {
  if (!firstSeen(record)) return;
  const msg = describeDispatch(record, note);
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

function toastAwake(list: Device[]): void {
  if (list.length === 0) return;
  toast(TOAST.isAwake(names(list.map((d) => d.name)), list.length > 1), TOAST.isAwakeBody);
}

/**
 * Follow-up after a manual wake: check at ~20 s; anything still asleep is
 * checked again at ~45 s and only then reported, in one combined toast. A
 * device that comes up gets "<name> is awake", unless it was already awake
 * before the wake. "unknown" never produces a failure claim.
 */
export function scheduleNoReplyCheck(
  record: DispatchRecord,
  devices: Device[],
  before: Promise<Record<string, Status>>,
  onChecked?: () => void,
): void {
  const checkable = checkableDevices(record, devices);
  if (checkable.length === 0) return;

  const check = (list: Device[]) => status(list.map((d) => d.id));
  const fail = (e: unknown) => console.warn("[Wake Dispatch] follow-up status check failed", errorText(e));

  setTimeout(() => {
    Promise.all([before, check(checkable)])
      .then(([prior, first]) => {
        onChecked?.();
        const wasAwake = (d: Device) => prior[d.id] === "awake";
        toastAwake(checkable.filter((d) => first[d.id] === "awake" && !wasAwake(d)));
        const pending = checkable.filter((d) => first[d.id] === "asleep");
        if (pending.length === 0) return;
        setTimeout(() => {
          check(pending)
            .then((second) => {
              onChecked?.();
              toastAwake(pending.filter((d) => second[d.id] === "awake"));
              const asleep = pending.filter((d) => second[d.id] === "asleep");
              if (asleep.length > 0) {
                toast(TOAST.notWoken(names(asleep.map((d) => d.name)), asleep.length > 1), TOAST.notWokenBody);
              }
            })
            .catch(fail);
        }, SECOND_CHECK_MS - FIRST_CHECK_MS);
      })
      .catch(fail);
  }, FIRST_CHECK_MS);
}

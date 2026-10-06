// Toasts. One toast per DispatchRecord: both the "dispatched" event and the
// manual wake() return value call toastDispatch(); a short-lived key set makes
// whichever arrives second a no-op.
import { toaster } from "@decky/api";

import { status, type Device, type DispatchRecord } from "./api";
import { errorText, nameList, resultsWith, triggerLabel } from "./format";
import { PLUGIN_NAME, S } from "./strings";

const NO_REPLY_DELAY_MS = 18_000;
const SEEN_TTL_MS = 60_000;

const seen = new Map<string, number>();

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
export function describeDispatch(record: DispatchRecord): { title: string; body: string } | null {
  const sent = resultsWith(record, "sent");
  const failed = resultsWith(record, "error");
  const auto = record.trigger !== "manual";
  const context = auto ? `Automatic wake ${triggerLabel(record.trigger)}` : PLUGIN_NAME;

  switch (record.outcome) {
    case "sent":
      return {
        title: sent.length === 1 ? `Woke ${sent[0].name}` : `Sent wake to ${sent.length} devices`,
        body: context,
      };
    case "partial":
      return {
        title: `Sent wake to ${sent.length} of ${sent.length + failed.length} devices`,
        body: `Couldn't send to ${nameList(failed)}${failed[0]?.error ? `: ${failed[0].error}` : ""}`,
      };
    case "failed":
      return {
        title: failed.length === 1 ? `Couldn't wake ${failed[0].name}` : "Couldn't send the wake",
        body: failed[0]?.error ?? "Check that this device is connected to the network.",
      };
    case "no_network":
      return {
        title: "Couldn't reach the network",
        body: auto
          ? `${context} skipped: ${record.reason ?? "no network connection"}`
          : "Connect to your network and try again.",
      };
    case "skipped":
    default:
      // Automatic runs that skip (not on home network, nobody opted in) are
      // shown in the panel's "Last automatic wake" line instead of a toast, so
      // a handheld that resumes often doesn't spam notifications.
      if (auto) return null;
      return { title: "Nothing was sent", body: record.reason ?? "No devices to wake." };
  }
}

export function toastDispatch(record: DispatchRecord): void {
  if (!firstSeen(record)) return;
  const msg = describeDispatch(record);
  if (msg) toast(msg.title, msg.body);
}

export function toastError(title: string, e: unknown): void {
  console.error(`[Wake Dispatch] ${title}`, e);
  toast(title, S.backendError);
}

export function toastInfo(title: string, body: string): void {
  toast(title, body);
}

/**
 * After a manual wake, check devices that have a status host + port. If one
 * still reads "asleep" after ~18 s, say so. Devices without a status check, or
 * whose check is "unknown", never get a failure claim.
 */
export function scheduleNoReplyCheck(record: DispatchRecord, devices: Device[], onChecked?: () => void): void {
  const checkable = devices.filter(
    (d) => record.results[d.id]?.status === "sent" && d.host && d.status_port !== null,
  );
  if (checkable.length === 0) return;
  setTimeout(() => {
    status(checkable.map((d) => d.id))
      .then((result) => {
        for (const d of checkable) {
          if (result[d.id] === "asleep") {
            toast(`No reply from ${d.name}`, "Check that Wake-on-LAN is enabled on that PC.");
          }
        }
        onChecked?.();
      })
      .catch((e: unknown) => console.warn("[Wake Dispatch] follow-up status check failed", errorText(e)));
  }, NO_REPLY_DELAY_MS);
}

import type { AutoTrigger, DeviceResult, DispatchRecord, Trigger } from "./api";
import { AUTOMATION, LAST, names } from "./strings";

/** "Manual only" / "Wakes on boot" / "Wakes on resume" / "Wakes on boot and resume". */
export function automationSummary(auto: readonly AutoTrigger[]): string {
  const boot = auto.includes("boot");
  const resume = auto.includes("resume");
  if (boot && resume) return AUTOMATION.both;
  if (boot) return AUTOMATION.boot;
  if (resume) return AUTOMATION.resume;
  return AUTOMATION.manual;
}

export function triggerLabel(trigger: Trigger): string {
  switch (trigger) {
    case "boot":
      return "on boot";
    case "resume":
      return "after resume";
    default:
      return "manual";
  }
}

/** Relative time from a unix-seconds timestamp. */
export function relativeTime(atSeconds: number, nowMs: number = Date.now()): string {
  const diff = Math.max(0, Math.round(nowMs / 1000 - atSeconds));
  if (diff < 45) return "just now";
  const min = Math.round(diff / 60);
  if (min < 60) return `${min} min ago`;
  const hours = Math.round(min / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

function lowerFirst(s: string): string {
  return s.length === 0 ? s : s[0].toLowerCase() + s.slice(1);
}

export function resultsWith(record: DispatchRecord, status: DeviceResult["status"]): DeviceResult[] {
  return Object.values(record.results).filter((r) => r.status === status);
}

export function nameList(results: DeviceResult[]): string {
  return names(results.map((r) => r.name));
}

/**
 * "Last automatic wake: on boot, 2 min ago — sent to Gaming PC" when something
 * was sent; otherwise lead with the outcome: "Automatic wake on boot was
 * skipped, 3 h ago: not on home network".
 */
export function lastAutomationLine(record: DispatchRecord, nowMs: number = Date.now()): string {
  const when = triggerLabel(record.trigger);
  const ago = relativeTime(record.at, nowMs);
  const sent = resultsWith(record, "sent");
  const failed = resultsWith(record, "error");
  switch (record.outcome) {
    case "sent":
      return LAST.sent(when, ago, sent.length > 0 ? LAST.sentTo(nameList(sent)) : LAST.sentBare);
    case "partial":
      return LAST.sent(when, ago, LAST.sentPartial(nameList(sent), failed.length));
    case "failed":
      return LAST.failed(when, ago, lowerFirst(failed[0]?.error ?? LAST.unknownError));
    case "no_network":
      return LAST.skipped(when, ago, lowerFirst(record.reason ?? LAST.noNetwork));
    case "skipped":
    default:
      return LAST.skipped(when, ago, lowerFirst(record.reason ?? LAST.nothingToWake));
  }
}

/** Turn an unknown thrown value into a log-friendly string. */
export function errorText(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

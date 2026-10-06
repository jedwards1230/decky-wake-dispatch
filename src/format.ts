import type { AutoTrigger, DeviceResult, DispatchRecord, Trigger } from "./api";

/** "Manual only" / "Wakes on boot" / "Wakes on resume" / "Wakes on boot and resume". */
export function automationSummary(auto: readonly AutoTrigger[]): string {
  const boot = auto.includes("boot");
  const resume = auto.includes("resume");
  if (boot && resume) return "Wakes on boot and resume";
  if (boot) return "Wakes on boot";
  if (resume) return "Wakes on resume";
  return "Manual only";
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

/** "Gaming PC", "Gaming PC and Office PC", "3 devices". */
export function nameList(results: DeviceResult[]): string {
  if (results.length === 1) return results[0].name;
  if (results.length === 2) return `${results[0].name} and ${results[1].name}`;
  return `${results.length} devices`;
}

/** Outcome part of the "Last automatic wake" line. */
export function outcomeSummary(record: DispatchRecord): string {
  const sent = resultsWith(record, "sent");
  const failed = resultsWith(record, "error");
  switch (record.outcome) {
    case "sent":
      return sent.length > 0 ? `sent to ${nameList(sent)}` : "sent";
    case "partial":
      return `sent to ${nameList(sent)}; ${failed.length} couldn't be sent`;
    case "failed":
      return failed[0]?.error ? `couldn't send: ${lowerFirst(failed[0].error)}` : "couldn't send";
    case "no_network":
      return `skipped: ${lowerFirst(record.reason ?? "no network connection")}`;
    case "skipped":
    default:
      return `skipped: ${lowerFirst(record.reason ?? "nothing to wake")}`;
  }
}

export function lastAutomationLine(record: DispatchRecord, nowMs: number = Date.now()): string {
  return `Last automatic wake: ${triggerLabel(record.trigger)}, ${relativeTime(record.at, nowMs)} — ${outcomeSummary(record)}`;
}

/** Turn an unknown thrown value into a log-friendly string. */
export function errorText(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

import { Field } from "@decky/ui";

import type { Device } from "../api";
import { automationNextLine, isRelevantAutomation, lastAutomationLine } from "../format";
import { useAutomationRecords } from "../hooks/useAutomationState";

/**
 * "Last automatic wake: on boot, 2 min ago — sent to Gaming PC", or, before any
 * automatic wake that concerns the current setup, what happens next. Records
 * from before automation was switched on are not shown. The panel only mounts
 * this when at least one device has automation enabled.
 */
export function LastDispatch({ devices, now }: { devices: readonly Device[]; now: number }) {
  const records = useAutomationRecords();
  const last = records
    .filter((r) => isRelevantAutomation(r, devices))
    .reduce<(typeof records)[number] | null>((best, r) => (best && best.at >= r.at ? best : r), null);
  return (
    <Field
      description={last ? lastAutomationLine(last, now) : automationNextLine(devices)}
      bottomSeparator="none"
      focusable={false}
    />
  );
}

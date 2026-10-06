import { lastAutomationLine } from "../format";
import { useLastAutomation, useTick } from "../hooks/useAutomationState";

/** "Last automatic wake: on boot, 2 min ago — sent to Gaming PC". Hidden until there is something to show. */
export function LastDispatch({ automationEnabled }: { automationEnabled: boolean }) {
  const last = useLastAutomation();
  const now = useTick(30_000);
  if (!last) {
    if (!automationEnabled) return null;
    return <div style={{ fontSize: "12px", opacity: 0.75 }}>No automatic wakes yet.</div>;
  }
  return <div style={{ fontSize: "12px", opacity: 0.75, lineHeight: 1.4 }}>{lastAutomationLine(last, now)}</div>;
}

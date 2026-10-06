import { lastAutomationLine } from "../format";
import { useLastAutomation, useTick } from "../hooks/useAutomationState";
import { S } from "../strings";

/**
 * "Last automatic wake: on boot, 2 min ago — sent to Gaming PC". The panel only
 * mounts this when at least one device has automation enabled.
 */
export function LastDispatch() {
  const last = useLastAutomation();
  const now = useTick(30_000);
  return (
    <div style={{ fontSize: "12px", opacity: 0.75, lineHeight: 1.4 }}>
      {last ? lastAutomationLine(last, now) : S.noAutomaticYet}
    </div>
  );
}

import { useEffect, useState } from "react";

import { getState, type DispatchRecord } from "../api";
import { onDispatched } from "../events";

/** Most recent automatic (boot/resume) dispatch, from get_state() and kept live by the "dispatched" event. */
export function useLastAutomation(): DispatchRecord | null {
  const [last, setLast] = useState<DispatchRecord | null>(null);

  useEffect(() => {
    let active = true;
    const keepNewest = (record: DispatchRecord | null) => {
      if (!record || record.trigger === "manual") return;
      setLast((prev) => (prev && prev.at > record.at ? prev : record));
    };
    getState()
      .then((state) => {
        if (!active) return;
        keepNewest(state.automation.boot);
        keepNewest(state.automation.resume);
      })
      .catch((e: unknown) => console.warn("[Wake Dispatch] get_state failed", e));
    const unsubscribe = onDispatched(keepNewest);
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  return last;
}

/** Re-render every `ms` so relative times stay fresh. */
export function useTick(ms: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [ms]);
  return now;
}

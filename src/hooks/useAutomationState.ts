import { useEffect, useState } from "react";

import { getState, type DispatchRecord } from "../api";
import { onDispatched } from "../events";

/**
 * The latest boot and resume dispatch records, from get_state() and kept live by
 * the "dispatched" event. The caller decides which one is still worth showing.
 */
export function useAutomationRecords(): DispatchRecord[] {
  const [records, setRecords] = useState<{ boot: DispatchRecord | null; resume: DispatchRecord | null }>({
    boot: null,
    resume: null,
  });

  useEffect(() => {
    let active = true;
    const keepNewest = (record: DispatchRecord | null) => {
      if (!record || record.trigger === "manual") return;
      const trigger = record.trigger;
      setRecords((prev) => {
        const current = prev[trigger];
        return current && current.at > record.at ? prev : { ...prev, [trigger]: record };
      });
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

  return [records.boot, records.resume].filter((r): r is DispatchRecord => r !== null);
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

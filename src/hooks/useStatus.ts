import { useCallback, useEffect, useRef, useState } from "react";

import { status, type Status } from "../api";
import { onStatusRefreshRequested } from "../store";

export const STATUS_POLL_MS = 10_000;

/**
 * Status for the given device ids: fetched on mount, every 10 s while mounted,
 * and whenever requestStatusRefresh() is called. Stops on unmount. A failed
 * lookup keeps the previous values (missing ids render as "checking").
 */
export function useStatus(ids: string[]): Record<string, Status> {
  const [statuses, setStatuses] = useState<Record<string, Status>>({});
  const key = ids.join(",");
  const inFlight = useRef(false);
  const mounted = useRef(true);

  const refresh = useCallback(() => {
    if (key === "" || inFlight.current) return;
    inFlight.current = true;
    status(key.split(","))
      .then((result) => {
        if (mounted.current) setStatuses(result);
      })
      .catch((e: unknown) => console.warn("[Wake Dispatch] status check failed", e))
      .finally(() => {
        inFlight.current = false;
      });
  }, [key]);

  useEffect(() => {
    mounted.current = true;
    refresh();
    const timer = setInterval(refresh, STATUS_POLL_MS);
    const unsubscribe = onStatusRefreshRequested(refresh);
    return () => {
      mounted.current = false;
      clearInterval(timer);
      unsubscribe();
    };
  }, [refresh]);

  return statuses;
}

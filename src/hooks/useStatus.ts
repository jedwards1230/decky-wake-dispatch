import { useEffect, useRef, useState } from "react";

import { status, type Status } from "../api";
import { onStatusRefreshRequested } from "../store";

export const STATUS_POLL_MS = 10_000;

/**
 * Status for the given device ids: fetched on mount, every 10 s while mounted,
 * and whenever requestStatusRefresh() is called. Stops on unmount. A failed
 * lookup marks ids with no value yet as "unknown" and keeps earlier values.
 */
export function useStatus(ids: string[]): Record<string, Status> {
  const [statuses, setStatuses] = useState<Record<string, Status>>({});
  const key = ids.join(",");
  const latestKey = useRef(key);
  const inFlightKey = useRef<string | null>(null);
  const mounted = useRef(true);
  latestKey.current = key;

  useEffect(() => {
    mounted.current = true;

    const refresh = () => {
      const want = latestKey.current;
      if (want === "" || inFlightKey.current !== null) return;
      inFlightKey.current = want;
      const requested = want.split(",");
      status(requested)
        .then((result) => {
          if (mounted.current) setStatuses((prev) => ({ ...prev, ...result }));
        })
        .catch((e: unknown) => {
          console.warn("[Wake Dispatch] status check failed", e);
          if (!mounted.current) return;
          setStatuses((prev) => {
            const next = { ...prev };
            for (const id of requested) next[id] ??= "unknown";
            return next;
          });
        })
        .finally(() => {
          inFlightKey.current = null;
          // The device list changed while we waited: check the new set now.
          if (mounted.current && latestKey.current !== want) refresh();
        });
    };

    refresh();
    const timer = setInterval(refresh, STATUS_POLL_MS);
    const unsubscribe = onStatusRefreshRequested(refresh);
    return () => {
      mounted.current = false;
      clearInterval(timer);
      unsubscribe();
    };
  }, [key]);

  return statuses;
}

// Fan-out for the backend "dispatched" event. The single Decky listener is
// registered in index.tsx (definePlugin) and forwards here; mounted components
// subscribe with onDispatched() and unsubscribe on unmount.
import type { DispatchRecord } from "./api";

type Listener = (record: DispatchRecord) => void;

const listeners = new Set<Listener>();

export function onDispatched(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function emitDispatched(record: DispatchRecord): void {
  for (const listener of [...listeners]) {
    try {
      listener(record);
    } catch (e) {
      console.error("[Wake Dispatch] dispatched listener failed", e);
    }
  }
}

import { DialogButton, DialogFooter, DialogHeader, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { useCallback, useEffect, useState } from "react";

import { currentNetwork, neighbours, type Neighbour } from "../api";
import { PICKER } from "../strings";
import { InlineError } from "./InlineError";

interface Props {
  onPick: (n: Neighbour) => void;
  closeModal?: () => void;
}

/** Named devices first, the router last; otherwise keep the backend's order. */
function rank(n: Neighbour, gateway: string | null): number {
  if (gateway !== null && n.ip === gateway) return 2;
  return n.hostname ? 0 : 1;
}

/** Modal list of recently seen LAN devices; each entry is one focusable button. B closes. */
export function NetworkPicker({ onPick, closeModal }: Props) {
  const [items, setItems] = useState<Neighbour[] | null>(null);
  const [gateway, setGateway] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    setItems(null);
    setFailed(false);
    currentNetwork()
      .then((net) => setGateway(net?.gateway ?? null))
      .catch(() => setGateway(null));
    neighbours()
      .then(setItems)
      .catch((e: unknown) => {
        console.error("[Wake Dispatch] neighbours failed", e);
        setItems([]);
        setFailed(true);
      });
  }, []);

  useEffect(load, [load]);

  const pick = (n: Neighbour) => {
    onPick(n);
    closeModal?.();
  };

  const sorted = items
    ? items
        .map((n, i) => ({ n, i }))
        .sort((a, b) => rank(a.n, gateway) - rank(b.n, gateway) || a.i - b.i)
        .map(({ n }) => n)
    : null;

  return (
    <ModalRoot onCancel={closeModal} closeModal={closeModal}>
      <DialogHeader>{PICKER.title}</DialogHeader>
      <div style={{ fontSize: "13px", marginBottom: "12px", opacity: 0.8 }}>{PICKER.intro}</div>
      {sorted === null ? (
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <Spinner style={{ width: "20px", height: "20px" }} />
          {PICKER.loading}
        </div>
      ) : failed ? (
        <InlineError>{PICKER.failed}</InlineError>
      ) : sorted.length === 0 ? (
        <div>{PICKER.empty}</div>
      ) : (
        <Focusable style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          {sorted.map((n) => (
            <DialogButton key={`${n.mac}-${n.ip}`} onClick={() => pick(n)} style={{ textAlign: "left" }}>
              <div style={{ fontWeight: "bold" }}>
                {n.hostname ?? n.ip}
                {gateway !== null && n.ip === gateway ? ` ${PICKER.router}` : ""}
              </div>
              <div style={{ fontSize: "12px", opacity: 0.8 }}>
                {n.ip} · {n.mac}
              </div>
            </DialogButton>
          ))}
        </Focusable>
      )}
      <DialogFooter>
        <Focusable flow-children="horizontal" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
          <DialogButton onClick={load}>{PICKER.refresh}</DialogButton>
          <DialogButton onClick={closeModal}>{PICKER.cancel}</DialogButton>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}

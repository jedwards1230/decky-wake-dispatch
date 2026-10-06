import { DialogButton, DialogFooter, DialogHeader, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { useCallback, useEffect, useState } from "react";

import { neighbours, type Neighbour } from "../api";
import { PICKER } from "../strings";
import { InlineError } from "./InlineError";

interface Props {
  onPick: (n: Neighbour) => void;
  closeModal?: () => void;
}

/** Modal list of recently seen LAN devices; each entry is one focusable button. B closes. */
export function NetworkPicker({ onPick, closeModal }: Props) {
  const [items, setItems] = useState<Neighbour[] | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    setItems(null);
    setFailed(false);
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

  return (
    <ModalRoot onCancel={closeModal} closeModal={closeModal}>
      <DialogHeader>{PICKER.title}</DialogHeader>
      <div style={{ fontSize: "13px", marginBottom: "12px", opacity: 0.8 }}>{PICKER.intro}</div>
      {items === null ? (
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <Spinner style={{ width: "20px", height: "20px" }} />
          {PICKER.loading}
        </div>
      ) : failed ? (
        <InlineError>{PICKER.failed}</InlineError>
      ) : items.length === 0 ? (
        <div>{PICKER.empty}</div>
      ) : (
        <Focusable style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          {items.map((n) => (
            <DialogButton key={`${n.mac}-${n.ip}`} onClick={() => pick(n)} style={{ textAlign: "left" }}>
              <div style={{ fontWeight: "bold" }}>{n.hostname ?? n.ip}</div>
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

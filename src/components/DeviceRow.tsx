import { ConfirmModal, DialogButton, Focusable, showModal } from "@decky/ui";
import { useState } from "react";

import type { Device, Status } from "../api";
import { automationSummary } from "../format";
import { deleteDevice, wakeManual } from "../store";
import { S } from "../strings";
import { DeviceEditor } from "./DeviceEditor";
import { StatusBadge } from "./StatusBadge";

const BUTTON_STYLE = { minWidth: 0, padding: "6px 8px", flex: 1 } as const;

function confirmDelete(device: Device) {
  showModal(
    <ConfirmModal
      strTitle={S.deleteTitle(device.name)}
      strDescription={S.deleteBody}
      strOKButtonText={S.delete}
      bDestructiveWarning
      onOK={() => void deleteDevice(device.id)}
    />,
  );
}

/** Name + status text, automation summary, then Wake / Edit / Delete (D-pad left/right between them). */
export function DeviceRow({ device, status }: { device: Device; status: Status | undefined }) {
  const [waking, setWaking] = useState(false);

  const onWake = async () => {
    if (waking) return;
    setWaking(true);
    try {
      await wakeManual([device.id]);
    } finally {
      setWaking(false);
    }
  };

  return (
    <div style={{ width: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px" }}>
        <span style={{ fontWeight: "bold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {device.name}
        </span>
        <StatusBadge value={status} />
      </div>
      <div style={{ fontSize: "12px", opacity: 0.75, margin: "2px 0 6px" }}>{automationSummary(device.auto)}</div>
      <Focusable flow-children="horizontal" style={{ display: "flex", gap: "6px" }}>
        <DialogButton style={{ ...BUTTON_STYLE, flex: 2 }} onClick={() => void onWake()}>
          {waking ? S.waking : S.wake}
        </DialogButton>
        <DialogButton style={BUTTON_STYLE} onClick={() => showModal(<DeviceEditor device={device} />)}>
          {S.edit}
        </DialogButton>
        <DialogButton style={BUTTON_STYLE} onClick={() => confirmDelete(device)}>
          {S.delete}
        </DialogButton>
      </Focusable>
    </div>
  );
}

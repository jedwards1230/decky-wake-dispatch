import { ConfirmModal, DialogButton, Focusable, showModal } from "@decky/ui";

import type { Device, Status } from "../api";
import { automationSummary } from "../format";
import { deleteDevice, useWaking, wakeManual } from "../store";
import { S } from "../strings";
import { AccessibleText } from "./AccessibleText";
import { DeviceEditor } from "./DeviceEditor";
import { StatusBadge } from "./StatusBadge";

const BUTTON_STYLE = {
  position: "relative",
  minWidth: 0,
  padding: "6px 8px",
  flex: 1,
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
} as const;

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
  const waking = useWaking().isWaking(device.id);
  const hasStatusCheck = Boolean(device.host) && device.status_port !== null;

  // wakeManual ignores a second press while this device's wake is in flight.
  const onWake = () => void wakeManual([device.id]);

  return (
    <div style={{ width: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px" }}>
        <span title={device.name} style={{ fontWeight: "bold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {device.name}
        </span>
        <StatusBadge name={device.name} value={hasStatusCheck ? status : "none"} />
      </div>
      <div style={{ fontSize: "12px", opacity: 0.75, margin: "2px 0 6px" }}>{automationSummary(device.auto)}</div>
      <Focusable flow-children="horizontal" style={{ display: "flex", gap: "6px" }}>
        <DialogButton style={{ ...BUTTON_STYLE, flex: 2 }} disabled={waking} onClick={onWake}>
          <AccessibleText visible={waking ? S.waking : S.wake} label={waking ? `${S.waking} ${device.name}` : S.wakeLabel(device.name)} />
        </DialogButton>
        <DialogButton style={BUTTON_STYLE} onClick={() => showModal(<DeviceEditor device={device} />)}>
          <AccessibleText visible={S.edit} label={S.editLabel(device.name)} />
        </DialogButton>
        <DialogButton style={BUTTON_STYLE} onClick={() => confirmDelete(device)}>
          <AccessibleText visible={S.delete} label={S.deleteLabel(device.name)} />
        </DialogButton>
      </Focusable>
    </div>
  );
}

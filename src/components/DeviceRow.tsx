import { DialogButton, Field, Focusable, Menu, MenuItem, NavEntryPositionPreferences, showContextMenu } from "@decky/ui";
import { useEffect, useRef } from "react";
import { FaEllipsisH } from "react-icons/fa";

import type { Device, Status } from "../api";
import { automationSummary, relativeTime } from "../format";
import { WAKE_RESULT_MS, onWindowFocusOnce, requestFocus, useFocusRequest, useWakeResult, useWaking, wakeManual, type WakeResult } from "../store";
import { ROW, S } from "../strings";
import { AccessibleText } from "./AccessibleText";
import { confirmDeleteDevice, openDeviceEditor } from "./DeviceEditor";
import { focusSoon } from "./focus";
import { StatusDot } from "./StatusBadge";

// Fixed width so swapping "Wake" for "Sending…" never resizes the row.
const WAKE_STYLE = { minWidth: 0, width: "84px", padding: 0, whiteSpace: "nowrap" } as const;
const MORE_STYLE = { minWidth: 0, width: "40px", padding: 0, display: "flex", alignItems: "center", justifyContent: "center" } as const;

function resultText(result: WakeResult, now: number): string {
  switch (result.phase) {
    case "checking":
      return ROW.checking;
    case "awake":
      return ROW.awake;
    case "asleep":
      return ROW.notWoken;
    case "sent":
    default:
      return ROW.sent(relativeTime(result.at / 1000, now));
  }
}

/** Marks a row's ⋯ wrapper so focus can find it again after the panel re-renders. */
const MORE_ATTR = "data-wake-dispatch-more";

/**
 * The row's ⋯ menu: Edit and Delete…. Cancelling it (B or Cancel) puts focus
 * back on ⋯: the menu opens outside the Quick Access panel, and when it closes
 * the panel's buttons are rebuilt and Steam hands focus to the row's first
 * button (Wake) or to nothing. The ⋯ is looked up again by device id, since the
 * one that was pressed may be gone by then. After a delete, focus moves to the
 * neighbouring row's Wake, else Add device; after Edit, the editor restores it.
 */
function showRowMenu(device: Device, from: HTMLElement | null): void {
  const doc = from?.ownerDocument ?? null;
  const win = doc?.defaultView ?? null;
  const findMore = () => doc?.querySelector<HTMLElement>(`[${MORE_ATTR}="${CSS.escape(device.id)}"]`) ?? null;
  let picked = false;
  let detach = () => {};
  const refocus = () => {
    detach();
    if (!picked) focusSoon(findMore, { retry: "always" });
  };
  // The panel's window regains focus when the menu closes, however it closed.
  // The listener expires after two minutes and is dropped on plugin unload.
  if (win) detach = onWindowFocusOnce(win, refocus);
  const choose = (action: () => void) => () => {
    picked = true;
    detach();
    action();
  };
  showContextMenu(
    <Menu label={device.name} cancelText={S.cancel} onCancel={refocus}>
      <MenuItem onClick={choose(() => openDeviceEditor(device))}>{S.edit}</MenuItem>
      <MenuItem tone="destructive" onClick={choose(() => confirmDeleteDevice(device, requestFocus))}>
        {S.deleteEllipsis}
      </MenuItem>
    </Menu>,
    from ?? undefined,
  );
}

/** While a recent result shows, the dot follows it rather than the live poll. */
function dotForResult(result: WakeResult, live: Status | "checking"): Status | "checking" {
  switch (result.phase) {
    case "checking":
      return "checking";
    case "awake":
      return "awake";
    case "asleep":
      return "asleep";
    case "sent":
    default:
      return live;
  }
}

interface Props {
  device: Device;
  status: Status | undefined;
  now: number;
}

/**
 * Steam-style row: the name, a description with the status in words (the dot is
 * decorative) and the automation summary, or for ~10 min after a manual wake
 * what that wake did. Wake and a ⋯ menu (Edit, Delete…) sit on the right; D-pad
 * left/right moves between them.
 */
export function DeviceRow({ device, status, now }: Props) {
  const waking = useWaking().isWaking(device.id);
  const result = useWakeResult(device.id);
  const focus = useFocusRequest();
  const wakeRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLDivElement>(null);
  const hasStatusCheck = Boolean(device.host) && device.status_port !== null;
  const wantsFocus = focus?.id === device.id;

  useEffect(() => {
    if (wantsFocus) focusSoon(() => wakeRef.current, { retry: "always" });
    // Once per request (seq), not on every re-render while it is the latest one.
  }, [focus?.seq]);

  // Never disable the button while sending: it may hold focus, and a disabled
  // button drops it. wakeManual ignores a second press while this wake is in flight.
  const onWake = () => void wakeManual([device.id]);

  const recent = result && now - result.at < WAKE_RESULT_MS ? result : null;
  const live: Status | "checking" = status ?? "checking";
  const parts = recent
    ? [resultText(recent, now)]
    : [...(hasStatusCheck ? [S.status[live]] : []), automationSummary(device.auto)];

  const description = (
    <span>
      {hasStatusCheck && <StatusDot value={recent ? dotForResult(recent, live) : live} />}
      {parts.join(" · ")}
    </span>
  );

  return (
    <Field
      label={
        <span title={device.name} style={{ overflowWrap: "anywhere" }}>
          {device.name}
        </span>
      }
      description={description}
      bottomSeparator="standard"
      childrenContainerWidth="min"
      inlineWrap="keep-inline"
      focusable={false}
    >
      <Focusable
        flow-children="horizontal"
        navEntryPreferPosition={NavEntryPositionPreferences.FIRST}
        style={{ display: "flex", gap: "6px" }}
      >
        <DialogButton ref={wakeRef} style={WAKE_STYLE} preferredFocus={wantsFocus} onClick={onWake}>
          <AccessibleText visible={waking ? S.waking : S.wake} label={waking ? S.wakingLabel(device.name) : S.wakeLabel(device.name)} />
        </DialogButton>
        <div ref={moreRef} {...{ [MORE_ATTR]: device.id }} style={{ display: "contents" }}>
          <DialogButton style={MORE_STYLE} onClick={() => showRowMenu(device, moreRef.current)}>
            <AccessibleText visible={<FaEllipsisH size={14} />} label={S.moreLabel(device.name)} />
          </DialogButton>
        </div>
      </Focusable>
    </Field>
  );
}

import {
  ButtonItem,
  DialogBodyText,
  DialogButtonSecondary,
  DialogFooter,
  DialogHeader,
  Field,
  Focusable,
  ModalRoot,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import { useEffect, useRef } from "react";

import type { UpdateInfo } from "../api";
import type { UpdateState } from "../hooks/useUpdate";
import { UPDATE } from "../strings";
import { UPDATE_FOCUS, focusWhenWindowReturns, requestFocus, useFocusRequest } from "../store";
import { canInstallInPlace, requestInstall } from "../update";
import { focusSoon } from "./focus";
import { InlineError, hintOrError } from "./InlineError";

/** One line saying where updates stand. "Off" is a choice, not a problem, so it isn't styled as one. */
function statusLine(info: UpdateInfo | null): string | null {
  if (info === null) return null;
  switch (info.status) {
    case "available":
      return UPDATE.available(info.latest ?? info.release?.version ?? "");
    case "current":
      // The backend reports an unreadable installed version as unavailable, so it is set here.
      return UPDATE.current(info.installed ?? info.latest ?? "");
    case "unavailable":
      return info.error ? UPDATE.unavailableWith(info.error) : UPDATE.unavailable;
    case "unchecked":
      return info.enabled ? UPDATE.notChecked : UPDATE.autoOff;
    case "disabled":
    default:
      return UPDATE.autoOff;
  }
}

/** Manual install: Decky's Install Plugin from URL, with the URL as copyable text. */
function ManualUpdateModal({ url, failed, closeModal }: { url: string; failed: boolean; closeModal?: () => void }) {
  return (
    <ModalRoot onCancel={closeModal} closeModal={closeModal}>
      <DialogHeader>{UPDATE.manualTitle}</DialogHeader>
      {failed && (
        <DialogBodyText style={{ marginBottom: "8px" }}>
          <InlineError>{UPDATE.installFailed}</InlineError>
        </DialogBodyText>
      )}
      <DialogBodyText style={{ marginBottom: "8px" }}>{UPDATE.manual}</DialogBodyText>
      {/* Read-only (edits are ignored) but focusable, so Steam's copy action works. */}
      <TextField label={UPDATE.manualField} description={UPDATE.manualFieldHint} value={url} bShowCopyAction onChange={() => undefined} />
      <DialogFooter>
        <Focusable style={{ display: "flex", marginTop: "16px" }}>
          <DialogButtonSecondary onClick={closeModal}>{UPDATE.close}</DialogButtonSecondary>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}

/**
 * "Update available: vX.Y.Z" with an Update button, shown only when a newer
 * release is known. Update opens Decky's own confirm; where that isn't
 * possible (or fails) it shows how to install from the URL instead.
 */
export function UpdateRow({ info }: { info: UpdateInfo | null }) {
  const busy = useRef(false);
  const rowRef = useRef<HTMLDivElement>(null);
  const focus = useFocusRequest();
  const shown = info?.status === "available" && info.release !== null;

  // Back on Update after Decky's prompt or the manual modal closes. The panel is
  // rebuilt when its window regains focus, so the row may only appear once the
  // status has loaded again: try again when it does.
  useEffect(() => {
    if (shown && focus?.id === UPDATE_FOCUS) focusSoon(() => rowRef.current, { retry: "always" });
  }, [focus?.seq, shown]);

  if (!shown || !info?.release) return null;
  const release = info.release;
  const manualUrl = info.manual_url;

  const install = async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const inPlace = canInstallInPlace();
      const opened = inPlace && (await requestInstall(release));
      if (opened) {
        const win = rowRef.current?.ownerDocument.defaultView;
        if (win) focusWhenWindowReturns(win, UPDATE_FOCUS);
      } else {
        showModal(<ManualUpdateModal url={manualUrl} failed={inPlace} />, undefined, {
          fnOnClose: () => requestFocus(UPDATE_FOCUS),
        });
      }
    } finally {
      busy.current = false;
    }
  };

  return (
    <PanelSectionRow>
      <div ref={rowRef}>
        <ButtonItem layout="below" label={UPDATE.available(release.version)} onClick={() => void install()}>
          {UPDATE.update}
        </ButtonItem>
      </div>
    </PanelSectionRow>
  );
}

/** Updates section: where things stand, Check for updates, the Check daily toggle, the installed version. */
export function UpdateSection({ update }: { update: UpdateState }) {
  const { info, checking, checkNote, toggleError, checkNow, setDaily } = update;
  const line = statusLine(info);
  const checkRef = useRef<HTMLDivElement>(null);
  const focus = useFocusRequest();
  const rowShown = info?.status === "available" && info.release !== null;

  // The Update row is gone (installed elsewhere, or a newer check said current):
  // fall back here. Only once the status has loaded, or a rebuilt panel would
  // land here before the row has had a chance to come back.
  const loaded = info !== null;
  useEffect(() => {
    if (loaded && !rowShown && focus?.id === UPDATE_FOCUS) focusSoon(() => checkRef.current, { retry: "always" });
  }, [focus?.seq, loaded]);
  return (
    <PanelSection title={UPDATE.title}>
      {line && (
        <PanelSectionRow>
          <Field description={line} bottomSeparator="none" focusable={false} />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        {/* Never disabled while checking (it holds focus); repeat presses are ignored. */}
        <div ref={checkRef}>
          <ButtonItem layout="below" description={checkNote ?? undefined} onClick={checkNow}>
            {checking ? UPDATE.checking : UPDATE.checkNow}
          </ButtonItem>
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label={UPDATE.toggle}
          description={hintOrError(UPDATE.toggleHint, toggleError)}
          checked={info?.enabled ?? false}
          onChange={setDaily}
        />
      </PanelSectionRow>
      {info?.installed && (
        <PanelSectionRow>
          <Field description={UPDATE.installed(info.installed)} bottomSeparator="none" focusable={false} />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

import {
  ConfirmModal,
  DialogBodyText,
  DialogButtonPrimary,
  DialogButtonSecondary,
  DialogFooter,
  DialogHeader,
  Focusable,
  ModalRoot,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import { useRef, useState } from "react";

import { importConfig, listDevices } from "../api";
import { toastInfo } from "../notify";
import { replaceDevices } from "../store";
import { BACKUP } from "../strings";
import { InlineError } from "./InlineError";

/** Resolves exactly once: OK → true, Cancel/B → false, any other close → false. */
function confirmReplace(count: number): Promise<boolean> {
  return new Promise((resolve) => {
    let done = false;
    const settle = (value: boolean) => {
      if (done) return;
      done = true;
      resolve(value);
    };
    showModal(
      <ConfirmModal
        strTitle={BACKUP.importConfirmTitle}
        strDescription={BACKUP.importConfirmBody(count)}
        strOKButtonText={BACKUP.importConfirmOk}
        strCancelButtonText={BACKUP.cancel}
        bDestructiveWarning
        onOK={() => settle(true)}
        onCancel={() => settle(false)}
      />,
      undefined,
      // Deferred so an onOK that fires during close still wins.
      { fnOnClose: () => setTimeout(() => settle(false), 0) },
    );
  });
}

/** Paste exported JSON, choose merge (default) or replace, show import_config errors inline. */
export function ImportModal({ closeModal }: { closeModal?: () => void }) {
  const [text, setText] = useState("");
  const [replace, setReplace] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const working = useRef(false);

  const submit = async () => {
    if (working.current) return;
    const trimmed = text.trim();
    if (trimmed === "") return setError(BACKUP.importEmpty);
    try {
      JSON.parse(trimmed);
    } catch {
      return setError(BACKUP.importNotJson);
    }
    setError(null);
    working.current = true;
    try {
      if (replace) {
        const current = await listDevices();
        if (current.length > 0 && !(await confirmReplace(current.length))) return;
      }
      setBusy(true);
      const result = await importConfig(trimmed, replace ? "replace" : "merge");
      if (!result.ok) {
        setError(result.error);
        return;
      }
      replaceDevices(result.devices);
      const n = result.devices.length;
      toastInfo(BACKUP.imported, replace ? BACKUP.importedReplace(n) : BACKUP.importedMerge(n));
      closeModal?.();
    } catch (e) {
      console.error("[Wake Dispatch] import_config failed", e);
      setError(BACKUP.importFailed);
    } finally {
      working.current = false;
      setBusy(false);
    }
  };

  return (
    <ModalRoot onCancel={closeModal} closeModal={closeModal}>
      <DialogHeader>{BACKUP.importTitle}</DialogHeader>
      <DialogBodyText style={{ marginBottom: "8px" }}>{BACKUP.importIntro}</DialogBodyText>
      <TextField
        label={BACKUP.importField}
        value={text}
        bShowClearAction
        onChange={(e) => {
          setText(e.target.value);
          setError(null);
        }}
      />
      <ToggleField
        label={BACKUP.importReplace}
        description={replace ? BACKUP.importReplaceOn : BACKUP.importReplaceOff}
        checked={replace}
        onChange={setReplace}
      />
      {error && (
        <div style={{ marginTop: "8px" }}>
          <InlineError>{error}</InlineError>
        </div>
      )}
      <DialogFooter>
        <Focusable flow-children="horizontal" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
          <DialogButtonPrimary onClick={() => void submit()}>{busy ? BACKUP.importing : BACKUP.importButton}</DialogButtonPrimary>
          <DialogButtonSecondary onClick={closeModal}>{BACKUP.cancel}</DialogButtonSecondary>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}

import {
  ConfirmModal,
  DialogButton,
  DialogFooter,
  DialogHeader,
  Focusable,
  ModalRoot,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import { useState } from "react";

import { importConfig, listDevices } from "../api";
import { toastInfo } from "../notify";
import { replaceDevices } from "../store";
import { BACKUP } from "../strings";
import { InlineError } from "./InlineError";

function confirmReplace(count: number): Promise<boolean> {
  return new Promise((resolve) => {
    showModal(
      <ConfirmModal
        strTitle={BACKUP.importConfirmTitle}
        strDescription={BACKUP.importConfirmBody(count)}
        strOKButtonText={BACKUP.importConfirmOk}
        strCancelButtonText={BACKUP.cancel}
        bDestructiveWarning
        onOK={() => resolve(true)}
        onCancel={() => resolve(false)}
      />,
      undefined,
      { fnOnClose: () => resolve(false) },
    );
  });
}

/** Paste exported JSON, choose merge (default) or replace, show import_config errors inline. */
export function ImportModal({ closeModal }: { closeModal?: () => void }) {
  const [text, setText] = useState("");
  const [replace, setReplace] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (busy) return;
    const trimmed = text.trim();
    if (trimmed === "") return setError(BACKUP.importEmpty);
    try {
      JSON.parse(trimmed);
    } catch {
      return setError(BACKUP.importNotJson);
    }
    setError(null);
    setBusy(true);
    try {
      if (replace) {
        const current = await listDevices();
        if (current.length > 0 && !(await confirmReplace(current.length))) return;
      }
      const result = await importConfig(trimmed, replace ? "replace" : "merge");
      if (!result.ok) {
        setError(result.error);
        return;
      }
      replaceDevices(result.devices);
      toastInfo(BACKUP.imported(result.devices.length), replace ? "Replaced your device list." : "Merged with your device list.");
      closeModal?.();
    } catch (e) {
      console.error("[Wake Dispatch] import_config failed", e);
      setError("Couldn't import. Try again, or restart Decky Loader.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalRoot onCancel={closeModal} closeModal={closeModal}>
      <DialogHeader>{BACKUP.importTitle}</DialogHeader>
      <div style={{ fontSize: "13px", marginBottom: "8px" }}>{BACKUP.importIntro}</div>
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
          <DialogButton onClick={closeModal}>{BACKUP.cancel}</DialogButton>
          <DialogButton onClick={() => void submit()}>{busy ? BACKUP.importing : BACKUP.importButton}</DialogButton>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}

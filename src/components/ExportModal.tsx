import {
  DialogBodyText,
  DialogButtonSecondary,
  DialogFooter,
  DialogHeader,
  Field,
  Focusable,
  ModalRoot,
  ScrollPanelGroup,
  Spinner,
  TextField,
} from "@decky/ui";
import { useEffect, useState } from "react";

import { exportConfig } from "../api";
import { BACKUP } from "../strings";
import { InlineError } from "./InlineError";

/** Compact single-line JSON fits a text field and pastes back into Import unchanged. */
function compact(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text));
  } catch {
    return text.replace(/\s*\n\s*/g, " ");
  }
}

/**
 * Shows the exported settings. There is no typed text-clipboard API in the Steam
 * client bindings, so the field uses Steam's own copy action (bShowCopyAction)
 * and the readable form is shown below it in a gamepad-scrollable panel.
 */
export function ExportModal({ closeModal }: { closeModal?: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    exportConfig()
      .then(setText)
      .catch((e: unknown) => {
        console.error("[Wake Dispatch] export_config failed", e);
        setFailed(true);
      });
  }, []);

  return (
    <ModalRoot onCancel={closeModal} closeModal={closeModal}>
      <DialogHeader>{BACKUP.exportTitle}</DialogHeader>
      {failed ? (
        <InlineError>{BACKUP.exportFailed}</InlineError>
      ) : text === null ? (
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <Spinner style={{ width: "20px", height: "20px" }} />
          {BACKUP.exportLoading}
        </div>
      ) : (
        <>
          <DialogBodyText style={{ marginBottom: "8px" }}>{BACKUP.exportIntro}</DialogBodyText>
          {/*
            Read-only: edits are ignored. Not `disabled`, because whether Steam
            still renders the copy action on a disabled field is unverified.
          */}
          <TextField
            label={BACKUP.exportField}
            description={BACKUP.exportFieldHint}
            value={compact(text)}
            bShowCopyAction
            onChange={() => undefined}
          />
          <div style={{ maxHeight: "40vh", overflowY: "auto", display: "flex", flexDirection: "column", marginTop: "8px" }}>
            <ScrollPanelGroup>
              <Field
                description={<pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0 }}>{text}</pre>}
                bottomSeparator="none"
                focusable={false}
              />
            </ScrollPanelGroup>
          </div>
        </>
      )}
      <DialogFooter>
        <Focusable style={{ display: "flex", marginTop: "12px" }}>
          <DialogButtonSecondary onClick={closeModal}>{BACKUP.close}</DialogButtonSecondary>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}

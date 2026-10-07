import {
  DialogBodyText,
  DialogButton,
  DialogButtonSecondary,
  DialogFooter,
  DialogHeader,
  Focusable,
  ModalRoot,
  showModal,
} from "@decky/ui";
import type { ReactElement } from "react";

import { BACKUP } from "../strings";
import { ExportModal } from "./ExportModal";
import { ImportModal } from "./ImportModal";

/** One entry point for backup: reassures that updates keep devices, then Export / Import. */
export function BackupModal({ closeModal }: { closeModal?: () => void }) {
  const open = (modal: ReactElement) => {
    closeModal?.();
    showModal(modal);
  };
  return (
    <ModalRoot onCancel={closeModal} closeModal={closeModal}>
      <DialogHeader>{BACKUP.title}</DialogHeader>
      <DialogBodyText>{BACKUP.intro}</DialogBodyText>
      <DialogBodyText style={{ marginTop: "8px" }}>{BACKUP.introMore}</DialogBodyText>
      <Focusable style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "16px" }}>
        <DialogButton onClick={() => open(<ExportModal />)}>{BACKUP.exportTitle}</DialogButton>
        <DialogButton onClick={() => open(<ImportModal />)}>{BACKUP.importTitle}</DialogButton>
      </Focusable>
      <DialogFooter>
        <Focusable style={{ display: "flex", marginTop: "16px" }}>
          <DialogButtonSecondary onClick={closeModal}>{BACKUP.close}</DialogButtonSecondary>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}

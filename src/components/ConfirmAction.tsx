import {
  DialogBodyText,
  DialogButtonPrimary,
  DialogButtonSecondary,
  DialogFooter,
  DialogHeader,
  Focusable,
  ModalRoot,
} from "@decky/ui";
import { useEffect, useRef } from "react";

import { S } from "../strings";
import { focusSoon } from "./focus";

interface Props {
  title: string;
  body: string;
  okText: string;
  destructive?: boolean;
  onOK: () => void;
  closeModal?: () => void;
}

/**
 * A yes/no question that opens focused on Cancel, so a stray A press does
 * nothing. Steam order: the action on the left, Cancel on the right.
 */
export function ConfirmAction({ title, body, okText, destructive, onOK, closeModal }: Props) {
  const cancelRef = useRef<HTMLDivElement>(null);
  // preferredFocus alone loses to the footer's first button, so move focus explicitly.
  useEffect(() => focusSoon(() => cancelRef.current, { retry: "always" }), []);
  return (
    <ModalRoot onCancel={closeModal} closeModal={closeModal} bDestructiveWarning={destructive}>
      <DialogHeader>{title}</DialogHeader>
      <DialogBodyText>{body}</DialogBodyText>
      <DialogFooter>
        <Focusable flow-children="horizontal" style={{ display: "flex", gap: "8px", marginTop: "16px" }}>
          <DialogButtonPrimary
            onClick={() => {
              closeModal?.();
              onOK();
            }}
          >
            {okText}
          </DialogButtonPrimary>
          <DialogButtonSecondary ref={cancelRef} preferredFocus onClick={closeModal}>
            {S.cancel}
          </DialogButtonSecondary>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}

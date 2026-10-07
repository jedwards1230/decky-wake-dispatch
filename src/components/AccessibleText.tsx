import type { CSSProperties, ReactNode } from "react";

// Visually hidden but read by screen readers.
const SR_ONLY: CSSProperties = {
  position: "absolute",
  width: "1px",
  height: "1px",
  padding: 0,
  margin: "-1px",
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

/**
 * Short visible text (or an icon) with a fuller accessible name, e.g. "Wake" on
 * screen read as "Wake Gaming PC". The @decky/ui button components don't type or forward
 * aria-label, so the name travels in the button's content instead.
 */
export function AccessibleText({ visible, label }: { visible: ReactNode; label: string }) {
  return (
    <>
      <span aria-hidden="true">{visible}</span>
      <span style={SR_ONLY}>{label}</span>
    </>
  );
}

import type { Status } from "../api";
import { S } from "../strings";

// Colour is secondary: the text label always says the state. Unknown and
// "No status check" are grey, never red.
export type BadgeValue = Status | "none" | undefined;

const COLOURS: Record<Status | "checking" | "none", string> = {
  awake: "#59bf40",
  asleep: "#d9a43b",
  unknown: "#8b929a",
  checking: "#8b929a",
  none: "#8b929a",
};

export function StatusBadge({ name, value }: { name: string; value: BadgeValue }) {
  const key = value ?? "checking";
  const text = S.status[key];
  return (
    <span role="status" aria-label={S.statusLabel(name, text)} style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "12px", whiteSpace: "nowrap" }}>
      <span
        aria-hidden="true"
        style={{
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          backgroundColor: COLOURS[key],
          flexShrink: 0,
        }}
      />
      <span aria-hidden="true">{text}</span>
    </span>
  );
}

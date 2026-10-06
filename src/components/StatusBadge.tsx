import type { Status } from "../api";
import { S } from "../strings";

// Colour is secondary: the text label always says the state. Unknown is grey, never red.
const COLOURS: Record<Status | "checking", string> = {
  awake: "#59bf40",
  asleep: "#d9a43b",
  unknown: "#8b929a",
  checking: "#8b929a",
};

export function StatusBadge({ value }: { value: Status | undefined }) {
  const key = value ?? "checking";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "12px", whiteSpace: "nowrap" }}>
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
      <span>{S.status[key]}</span>
    </span>
  );
}

import type { Status } from "../api";

// Decorative only: the row's description always says the state in words.
// Unknown and "checking" are grey, never red. Devices without a status check
// get no dot at all, so grey never stands in for "offline".
const COLOURS: Record<Status | "checking", string> = {
  awake: "#59bf40",
  asleep: "#d9a43b",
  unknown: "#8b929a",
  checking: "#8b929a",
};

export function StatusDot({ value }: { value: Status | "checking" }) {
  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-block",
        width: "8px",
        height: "8px",
        borderRadius: "50%",
        backgroundColor: COLOURS[value],
        marginRight: "6px",
        verticalAlign: "middle",
        flexShrink: 0,
      }}
    />
  );
}

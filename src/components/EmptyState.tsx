import { S } from "../strings";

export function EmptyState() {
  return (
    <div style={{ fontSize: "13px", lineHeight: 1.4 }}>
      <div style={{ fontWeight: "bold", marginBottom: "4px" }}>{S.emptyTitle}</div>
      <div style={{ marginBottom: "4px" }}>{S.emptyBody}</div>
      <div style={{ opacity: 0.75 }}>{S.emptyWolHint}</div>
    </div>
  );
}

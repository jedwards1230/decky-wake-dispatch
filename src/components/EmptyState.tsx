import { Field } from "@decky/ui";

import { S } from "../strings";

/** First run: what to do, in three steps, with the Wake-on-LAN prerequisite as a footnote. */
export function EmptyState() {
  return (
    <>
      <Field
        label={S.emptyTitle}
        description={
          <ol style={{ margin: "4px 0 0", paddingLeft: "20px" }}>
            {S.emptySteps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        }
        childrenLayout="below"
        bottomSeparator="none"
        focusable={false}
      />
      <Field description={<span style={{ opacity: 0.7 }}>{S.emptyWolHint}</span>} bottomSeparator="none" focusable={false} />
    </>
  );
}

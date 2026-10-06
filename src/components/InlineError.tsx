import type { ReactNode } from "react";

/** Inline validation / error text, used in field descriptions and modal bodies. */
export function InlineError({ children }: { children: ReactNode }) {
  return <span style={{ color: "#ff9d90" }}>{children}</span>;
}

/** Field description: the error when there is one, otherwise the hint. */
export function hintOrError(hint: ReactNode, error: string | null | undefined): ReactNode {
  return error ? <InlineError>{error}</InlineError> : hint;
}

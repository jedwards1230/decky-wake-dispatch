// Moving gamepad focus from code. Steam's focus navigation follows DOM focus, so
// focusing the element is enough. A second try ~250 ms later covers focus being
// taken back right after the first: a closing modal hands focus to whatever
// opened it a moment after it unmounts, and a new modal's footer grabs it on mount.
import { later } from "../notify";

const FOCUSABLE = ".DialogButton, button, input, [tabindex]";
const RETRY_MS = 250;

function resolve(el: HTMLElement | null | undefined): HTMLElement | null {
  if (!el || !el.isConnected) return null;
  if (el.matches(FOCUSABLE)) return el;
  // A focusable Field (for example a picker row) is itself the target.
  return el.querySelector<HTMLElement>(FOCUSABLE) ?? (el.tabIndex >= 0 ? el : null);
}

function focusNow(target: HTMLElement, centre: boolean): void {
  target.focus();
  target.scrollIntoView?.({ block: centre ? "center" : "nearest" });
}

export interface FocusSoonOptions {
  /** Scroll the target to the middle of the view rather than just into it. */
  centre?: boolean;
  /**
   * When to make the second try. "if-lost" (default) only refocuses when focus
   * fell to nothing, so a user who already moved on is left alone. "always" is
   * for the moments above, where Steam itself moves focus away right after.
   */
  retry?: "if-lost" | "always";
}

/** Focus `get()` (or the first focusable inside it) now, and once more shortly after if needed. */
export function focusSoon(get: () => HTMLElement | null | undefined, options: FocusSoonOptions = {}): void {
  const { centre = false, retry = "if-lost" } = options;
  let ours: HTMLElement | null = null;
  later(() => {
    ours = resolve(get());
    if (ours) focusNow(ours, centre);
  }, 0);
  later(() => {
    const target = resolve(get());
    if (!target) return;
    const active = target.ownerDocument.activeElement;
    if (active === target) return;
    const lost = active === null || active === target.ownerDocument.body || !active.isConnected;
    if (retry === "always" || lost || ours === null) focusNow(target, centre);
  }, RETRY_MS);
}

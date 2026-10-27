import { useEffect, type RefObject } from 'react';

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** Subtrees whose descendants cannot receive focus (no layout checks: jsdom has none). */
const UNAVAILABLE = '[hidden], [inert], [aria-hidden="true"]';

function focusableIn(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.matches(':disabled') && !el.closest(UNAVAILABLE),
  );
}

/** Keeps Tab / Shift+Tab cycling between the first and last focusable inside `container`. */
function wrapTab(e: KeyboardEvent, container: HTMLElement): void {
  const focusables = focusableIn(container);
  if (focusables.length === 0) {
    e.preventDefault();
    container.focus();
    return;
  }
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  const active = document.activeElement;
  if (!container.contains(active)) {
    e.preventDefault();
    (e.shiftKey ? last : first).focus();
  } else if (!focusables.includes(active as HTMLElement)) {
    // The focused control left the list (e.g. Save disabled mid-request), so the
    // browser's default move could leave the dialog: step to its neighbour here.
    e.preventDefault();
    neighbourOf(active as Element, focusables, e.shiftKey).focus();
  } else if (e.shiftKey && active === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && active === last) {
    e.preventDefault();
    first.focus();
  }
}

/** The next (or previous) focusable after `from` in document order, wrapping. */
function neighbourOf(from: Element, focusables: HTMLElement[], backwards: boolean): HTMLElement {
  if (backwards) {
    const before = focusables.filter(
      (el) => from.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_PRECEDING,
    );
    return before[before.length - 1] ?? focusables[focusables.length - 1];
  }
  const after = focusables.find(
    (el) => from.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING,
  );
  return after ?? focusables[0];
}

function restoreFocus(opener: Element | null): void {
  if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
}

/**
 * Modal focus management: focuses the dialog on mount, traps Tab inside it,
 * and returns focus to the element that opened it on unmount.
 */
export function useDialogFocus(dialogRef: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const opener = document.activeElement;
    (focusableIn(dialog)[0] ?? dialog).focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Tab') wrapTab(e, dialog);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      restoreFocus(opener);
    };
  }, [dialogRef]);
}

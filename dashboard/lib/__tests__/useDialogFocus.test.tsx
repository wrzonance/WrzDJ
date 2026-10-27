// @vitest-environment jsdom
import { useRef, useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { useDialogFocus } from '../useDialogFocus';

function Dialog({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useDialogFocus(ref);
  return (
    <div ref={ref} role="dialog" tabIndex={-1} aria-label="probe">
      {children}
    </div>
  );
}

function Harness({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>opener</button>
      <button onClick={() => setOpen(false)}>closer</button>
      {open && <Dialog>{children}</Dialog>}
    </>
  );
}

function openDialog() {
  const opener = screen.getByRole('button', { name: 'opener' });
  opener.focus();
  fireEvent.click(opener);
  return opener;
}

describe('useDialogFocus', () => {
  it('moves focus to the first focusable element on mount', () => {
    render(
      <Harness>
        <input aria-label="first" />
        <button>last</button>
      </Harness>,
    );
    openDialog();

    expect(screen.getByLabelText('first')).toHaveFocus();
  });

  it('focuses the dialog container when nothing inside is focusable', () => {
    render(
      <Harness>
        <p>read only</p>
      </Harness>,
    );
    openDialog();

    expect(screen.getByRole('dialog')).toHaveFocus();
  });

  it('wraps Tab from the last focusable to the first', () => {
    render(
      <Harness>
        <input aria-label="first" />
        <button>last</button>
      </Harness>,
    );
    openDialog();
    screen.getByRole('button', { name: 'last' }).focus();

    fireEvent.keyDown(document.activeElement as Element, { key: 'Tab' });

    expect(screen.getByLabelText('first')).toHaveFocus();
  });

  it('wraps Shift+Tab from the first focusable to the last', () => {
    render(
      <Harness>
        <input aria-label="first" />
        <button>last</button>
      </Harness>,
    );
    openDialog();

    fireEvent.keyDown(document.activeElement as Element, { key: 'Tab', shiftKey: true });

    expect(screen.getByRole('button', { name: 'last' })).toHaveFocus();
  });

  it('pulls focus back into the dialog when Tab is pressed from outside it', () => {
    render(
      <Harness>
        <input aria-label="first" />
        <button>last</button>
      </Harness>,
    );
    const opener = openDialog();
    opener.focus();

    fireEvent.keyDown(opener, { key: 'Tab' });

    expect(screen.getByLabelText('first')).toHaveFocus();
  });

  it('leaves Tab alone between the first and last focusable', () => {
    render(
      <Harness>
        <input aria-label="first" />
        <input aria-label="middle" />
        <button>last</button>
      </Harness>,
    );
    openDialog();
    const middle = screen.getByLabelText('middle');
    middle.focus();

    const notPrevented = fireEvent.keyDown(middle, { key: 'Tab' });

    expect(notPrevented).toBe(true);
    expect(middle).toHaveFocus();
  });

  it('restores focus to the opener when the dialog unmounts', () => {
    render(
      <Harness>
        <input aria-label="first" />
      </Harness>,
    );
    const opener = openDialog();
    expect(screen.getByLabelText('first')).toHaveFocus();

    fireEvent.click(screen.getByRole('button', { name: 'closer' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});

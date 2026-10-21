import { act, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { KioskKeyboard } from '../KioskKeyboard';

interface KeyboardOptions {
  layoutName: string;
  display: Record<string, string>;
  onChange: (input: string) => void;
  onKeyPress: (button: string) => void;
}

interface KeyboardInstance {
  options: KeyboardOptions;
  callbacks: Pick<KeyboardOptions, 'onChange' | 'onKeyPress'>;
  setOptions: ReturnType<typeof vi.fn>;
  setInput: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>;
}

const { instances } = vi.hoisted(() => ({ instances: [] as KeyboardInstance[] }));

vi.mock('simple-keyboard', () => ({
  default: class MockKeyboard {
    options: KeyboardOptions;
    callbacks: Pick<KeyboardOptions, 'onChange' | 'onKeyPress'>;
    setOptions = vi.fn((options: Partial<KeyboardOptions>) => {
      this.options = { ...this.options, ...options };
    });
    setInput = vi.fn();
    destroy = vi.fn();

    constructor(_container: HTMLElement, options: KeyboardOptions) {
      this.options = options;
      this.callbacks = options;
      instances.push(this);
    }
  },
}));

describe('KioskKeyboard', () => {
  it('handles layout changes and keeps callbacks, input, and cleanup in sync', () => {
    // Regression baseline 57cfcdc6867f: the captured simple-keyboard callbacks are the public
    // touchscreen boundary for layout transitions and must keep current parent callbacks.
    const firstOnChange = vi.fn();
    const firstOnDone = vi.fn();
    const firstResetTimer = vi.fn();
    const { rerender, unmount } = render(
      <KioskKeyboard
        inputValue="first value"
        onChange={firstOnChange}
        onDone={firstOnDone}
        resetTimer={firstResetTimer}
      />,
    );
    const keyboard = instances[0];

    expect(keyboard.setInput).toHaveBeenLastCalledWith('first value');
    expect(keyboard.options.layoutName).toBe('default');
    act(() => keyboard.callbacks.onKeyPress('{shift}'));
    expect(keyboard.options.layoutName).toBe('shift');
    act(() => keyboard.callbacks.onKeyPress('A'));
    expect(keyboard.options.layoutName).toBe('default');
    act(() => keyboard.callbacks.onKeyPress('{numbers}'));
    expect(keyboard.options.layoutName).toBe('numbers');
    act(() => keyboard.callbacks.onKeyPress('{abc}'));
    expect(keyboard.options.layoutName).toBe('default');
    expect(firstResetTimer).toHaveBeenCalledTimes(4);
    firstResetTimer.mockClear();

    const onChange = vi.fn();
    const onDone = vi.fn();
    const resetTimer = vi.fn();
    rerender(
      <KioskKeyboard
        inputValue="updated input"
        onChange={onChange}
        onDone={onDone}
        resetTimer={resetTimer}
        doneLabel="Submit"
      />,
    );
    expect(instances).toHaveLength(1);
    expect(keyboard.setInput).toHaveBeenLastCalledWith('updated input');
    expect(keyboard.options.display['{done}']).toBe('Submit');

    act(() => keyboard.callbacks.onChange('typed value'));
    act(() => keyboard.callbacks.onKeyPress('{done}'));
    expect(onChange).toHaveBeenCalledWith('typed value');
    expect(onDone).toHaveBeenCalledOnce();
    expect(resetTimer).toHaveBeenCalledTimes(2);
    expect(firstOnChange).not.toHaveBeenCalled();
    expect(firstOnDone).not.toHaveBeenCalled();
    expect(firstResetTimer).not.toHaveBeenCalled();

    unmount();
    expect(keyboard.destroy).toHaveBeenCalledOnce();
  });
});

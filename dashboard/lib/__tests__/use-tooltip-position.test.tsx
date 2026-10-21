import { useRef } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useTooltipPosition } from '../use-tooltip-position';

const wrapperRect = (left: number, top: number, width: number, height: number) =>
  new DOMRect(left, top, width, height);

function PositionProbe({ defaultVertical = 'above' }: { defaultVertical?: 'above' | 'below' }) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const position = useTooltipPosition(wrapperRef, tooltipRef, true, { defaultVertical });

  return (
    <div ref={wrapperRef} data-testid="wrapper">
      <div ref={tooltipRef} data-testid="tooltip" data-position={position.vertical}>
        <output data-testid="shift">{position.horizontalShiftPx}</output>
        <output data-testid="caret">{position.caretLeftPx}</output>
      </div>
    </div>
  );
}

function mockRects(tip: DOMRect, wrapper: DOMRect) {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.dataset.testid === 'tooltip' ? tip : wrapper;
  });
}

describe('useTooltipPosition', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('flips below and shifts an overflowing tooltip while keeping its caret aligned', () => {
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 600 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 400 });
    mockRects(wrapperRect(-5, 10, 60, 100), wrapperRect(15, 10, 30, 20));

    render(<PositionProbe />);

    expect(screen.getByTestId('tooltip')).toHaveAttribute('data-position', 'below');
    expect(screen.getByTestId('shift')).toHaveTextContent('13');
    expect(screen.getByTestId('caret')).toHaveTextContent('22');
  });

  it('flips a below-preferred tooltip above when there is more room there', () => {
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 200 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 400 });
    mockRects(wrapperRect(100, 150, 40, 20), wrapperRect(100, 150, 40, 20));

    render(<PositionProbe defaultVertical="below" />);

    expect(screen.getByTestId('tooltip')).toHaveAttribute('data-position', 'above');
  });

  it('shifts a right-overflowing tooltip to the viewport margin', () => {
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 600 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 300 });
    mockRects(wrapperRect(270, 300, 30, 20), wrapperRect(270, 300, 30, 20));

    render(<PositionProbe />);

    expect(screen.getByTestId('shift')).toHaveTextContent('-8');
    expect(screen.getByTestId('caret')).toHaveTextContent('18');
  });
});

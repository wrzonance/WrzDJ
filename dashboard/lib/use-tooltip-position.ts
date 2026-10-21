import { useLayoutEffect, useState, type RefObject } from 'react';

interface TooltipPositionOptions {
  viewportMargin?: number;
  gap?: number;
  caretInset?: number;
  defaultVertical?: 'above' | 'below';
}

interface TooltipPositionResult {
  vertical: 'above' | 'below';
  horizontalShiftPx: number;
  caretLeftPx: number | null;
}

const DEFAULT_RESULT: TooltipPositionResult = {
  vertical: 'above',
  horizontalShiftPx: 0,
  caretLeftPx: null,
};

export function useTooltipPosition(
  wrapperRef: RefObject<HTMLElement | null>,
  tooltipRef: RefObject<HTMLElement | null>,
  visible: boolean,
  options?: TooltipPositionOptions,
): TooltipPositionResult {
  const margin = options?.viewportMargin ?? 8;
  const gap = options?.gap ?? 8;
  const caretInset = options?.caretInset ?? 12;
  const defaultVertical = options?.defaultVertical ?? 'above';

  const [result, setResult] = useState<TooltipPositionResult>({
    ...DEFAULT_RESULT,
    vertical: defaultVertical,
  });

  useLayoutEffect(() => {
    if (!visible || !tooltipRef.current || !wrapperRef.current) return;

    const tip = tooltipRef.current.getBoundingClientRect();
    const wrapper = wrapperRef.current.getBoundingClientRect();
    const tipHeight = tip.height + gap;

    // Vertical: flip if not enough space in preferred direction
    const spaceAbove = wrapper.top - margin;
    const spaceBelow = window.innerHeight - wrapper.bottom - margin;
    let vertical: 'above' | 'below';
    if (defaultVertical === 'above') {
      vertical = tipHeight > spaceAbove && spaceBelow > spaceAbove ? 'below' : 'above';
    } else {
      vertical = tipHeight > spaceBelow && spaceAbove > spaceBelow ? 'above' : 'below';
    }

    // Horizontal: shift to stay within viewport
    let horizontalShiftPx = 0;
    let caretLeftPx: number | null = null;

    if (tip.left < margin) {
      horizontalShiftPx = margin - tip.left;
    } else if (tip.right > window.innerWidth - margin) {
      horizontalShiftPx = -(tip.right - (window.innerWidth - margin));
    }

    if (horizontalShiftPx !== 0) {
      const wrapperCenter = wrapper.left + wrapper.width / 2;
      const newTipLeft = tip.left + horizontalShiftPx;
      const caretPx = wrapperCenter - newTipLeft;
      caretLeftPx = Math.max(caretInset, Math.min(tip.width - caretInset, caretPx));
    }

    setResult({ vertical, horizontalShiftPx, caretLeftPx });
  }, [visible, margin, gap, caretInset, defaultVertical, tooltipRef, wrapperRef]);

  return result;
}

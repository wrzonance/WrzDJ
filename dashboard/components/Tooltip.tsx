'use client';

import { useState, useRef, useCallback, useEffect, type ReactNode } from 'react';
import { useTooltipPosition } from '@/lib/use-tooltip-position';

interface TooltipProps {
  /** Bold heading line */
  title?: string;
  /** Body text (or use children for custom content) */
  description?: string;
  /** Custom tooltip body — overrides title/description if provided */
  content?: ReactNode;
  /** The element that triggers the tooltip on hover */
  children: ReactNode;
  /** Max width in px (default 240) */
  maxWidth?: number;
  /** Hover delay in ms before showing (default 200) */
  delay?: number;
}

const GAP = 8;
const CARET_SIZE = 8;

export function Tooltip({
  title,
  description,
  content,
  children,
  maxWidth = 240,
  delay = 200,
}: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  const { vertical, horizontalShiftPx, caretLeftPx } = useTooltipPosition(
    wrapperRef,
    tooltipRef,
    visible,
    { defaultVertical: 'above' },
  );

  useEffect(() => () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const handleMouseEnter = useCallback(() => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      setVisible(true);
    }, delay);
  }, [delay]);

  const handleMouseLeave = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setVisible(false);
  }, []);

  const hasContent = !!(content || title || description);

  const body = content ?? (
    <>
      {title && (
        <div style={{ color: '#ededed', fontWeight: 600, marginBottom: description ? '0.25rem' : 0 }}>
          {title}
        </div>
      )}
      {description && (
        <div style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>{description}</div>
      )}
    </>
  );

  const isAbove = vertical === 'above';
  const leftStyle = horizontalShiftPx !== 0
    ? `calc(50% + ${horizontalShiftPx}px)`
    : '50%';
  const caretLeft = caretLeftPx !== null ? `${caretLeftPx}px` : '50%';

  return (
    <div
      ref={wrapperRef}
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}
      {visible && hasContent && (
        <div
          ref={tooltipRef}
          role="tooltip"
          style={{
            position: 'absolute',
            ...(isAbove
              ? { bottom: `calc(100% + ${GAP}px)` }
              : { top: `calc(100% + ${GAP}px)` }),
            left: leftStyle,
            transform: 'translateX(-50%)',
            background: '#1f1f1f',
            border: '1px solid var(--border)',
            borderRadius: '0.375rem',
            padding: '0.5rem 0.625rem',
            maxWidth: `${maxWidth}px`,
            width: 'max-content',
            fontSize: '0.75rem',
            zIndex: 1200,
            pointerEvents: 'none',
          }}
        >
          {body}
          {/* Caret arrow */}
          <div
            style={{
              position: 'absolute',
              ...(isAbove
                ? {
                    bottom: `-${CARET_SIZE / 2 + 1}px`,
                    borderRight: '1px solid var(--border)',
                    borderBottom: '1px solid var(--border)',
                  }
                : {
                    top: `-${CARET_SIZE / 2 + 1}px`,
                    borderLeft: '1px solid var(--border)',
                    borderTop: '1px solid var(--border)',
                  }),
              left: caretLeft,
              transform: 'translateX(-50%) rotate(45deg)',
              width: `${CARET_SIZE}px`,
              height: `${CARET_SIZE}px`,
              background: '#1f1f1f',
            }}
          />
        </div>
      )}
    </div>
  );
}

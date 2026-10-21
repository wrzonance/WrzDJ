'use client';

import { useState, useEffect, useRef, type ReactNode } from 'react';
import { useHelp } from '@/lib/help/HelpContext';
import { useTooltipPosition } from '@/lib/use-tooltip-position';

interface HelpSpotProps {
  spotId: string;
  page: string;
  order: number;
  title: string;
  description: string;
  children: ReactNode;
}

const GAP = 8;

export function HelpSpot({ spotId, page, order, title, description, children }: HelpSpotProps) {
  const { helpMode, onboardingActive, registerSpot } = useHelp();
  const [hovered, setHovered] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const deregister = registerSpot({ id: spotId, page, order, title, description, ref });
    return deregister;
  }, [spotId, page, order, title, description, registerSpot]);

  const showTooltip = helpMode && hovered && !onboardingActive;
  const showHighlight = helpMode;

  const { vertical, horizontalShiftPx } = useTooltipPosition(
    ref,
    tooltipRef,
    showTooltip,
    { viewportMargin: 16, defaultVertical: 'below' },
  );

  const tooltipStyle: React.CSSProperties = vertical === 'above'
    ? { bottom: `calc(100% + ${GAP}px)`, top: 'auto' }
    : { top: `calc(100% + ${GAP}px)`, bottom: 'auto' };

  if (horizontalShiftPx !== 0) {
    tooltipStyle.left = `${horizontalShiftPx}px`;
  }

  return (
    <div
      ref={ref}
      data-testid={`help-spot-${spotId}`}
      data-help-spot={spotId}
      className={showHighlight ? 'help-spot-highlight' : undefined}
      style={showHighlight ? { position: 'relative', overflow: 'visible' } : { display: 'contents' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {children}
      {showTooltip && (
        <div
          ref={tooltipRef}
          className="help-tooltip"
          role="tooltip"
          aria-live="polite"
          style={tooltipStyle}
        >
          <div className="help-tooltip-title">{title}</div>
          <div className="help-tooltip-desc">{description}</div>
        </div>
      )}
    </div>
  );
}

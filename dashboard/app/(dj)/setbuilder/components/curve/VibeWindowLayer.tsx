import { useEffect, useState } from 'react';
import { SvgFixedText } from './FixedSvgLabels';
import type { VibeWindowView } from '../types';

type WindowDrag = {
  id: string;
  mode: 'move' | 'left' | 'right';
  startMouseT: number;
  startT0: number;
  startT1: number;
};

interface VibeWindowLayerProps {
  windows: VibeWindowView[];
  domainSec: number;
  visibleStartSec: number;
  pxPerSecond: number;
  height: number;
  labelScaleX: number;
  labelScaleY: number;
  domainTimeAtClientX: (clientX: number) => number | null;
  onWindowChange?: (id: string, patch: Partial<VibeWindowView>) => void;
  onWindowCommit?: (id: string) => void;
  onWindowDelete?: (id: string) => void;
}

export function VibeWindowLayer({
  windows,
  domainSec,
  visibleStartSec,
  pxPerSecond,
  height,
  labelScaleX,
  labelScaleY,
  domainTimeAtClientX,
  onWindowChange,
  onWindowCommit,
  onWindowDelete,
}: VibeWindowLayerProps) {
  const [drag, setDrag] = useState<WindowDrag | null>(null);

  useEffect(() => {
    if (!drag) return;
    const onMove = (event: PointerEvent) => {
      if (!onWindowChange) return;
      const mouseT = domainTimeAtClientX(event.clientX);
      if (mouseT == null) return;
      const deltaT = mouseT - drag.startMouseT;
      if (drag.mode === 'move') {
        const span = drag.startT1 - drag.startT0;
        const t0 = Math.max(0, Math.min(1 - span, drag.startT0 + deltaT));
        onWindowChange(drag.id, { t0, t1: t0 + span });
      } else if (drag.mode === 'left') {
        const t0 = Math.max(0, Math.min(drag.startT1 - 0.02, drag.startT0 + deltaT));
        onWindowChange(drag.id, { t0 });
      } else {
        const t1 = Math.max(drag.startT0 + 0.02, Math.min(1, drag.startT1 + deltaT));
        onWindowChange(drag.id, { t1 });
      }
    };
    const onUp = () => {
      onWindowCommit?.(drag.id);
      setDrag(null);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [drag, domainTimeAtClientX, onWindowChange, onWindowCommit]);

  const startDrag = (
    id: string,
    mode: WindowDrag['mode'],
    t0: number,
    t1: number,
  ) => (event: React.PointerEvent) => {
    const mouseT = domainTimeAtClientX(event.clientX);
    if (mouseT == null || !onWindowChange) return;
    event.preventDefault();
    event.stopPropagation();
    setDrag({ id, mode, startMouseT: mouseT, startT0: t0, startT1: t1 });
  };

  return windows.map((win) => {
    const startSec = win.t0 * domainSec;
    const endSec = win.t1 * domainSec;
    const x = (startSec - visibleStartSec) * pxPerSecond;
    const width = Math.max(2, (endSec - startSec) * pxPerSecond);
    const isDragging = drag?.id === win.id;
    const headerHeight = 22;
    return (
      <g key={win.id} data-testid={`vibe-window-${win.id}`}>
        <rect
          x={x}
          y={0}
          width={width}
          height={height}
          fill={isDragging ? 'rgba(183,139,255,0.18)' : 'rgba(183,139,255,0.07)'}
          stroke="rgba(183,139,255,0.4)"
          strokeWidth="1"
          pointerEvents="none"
        />
        <line x1={x} x2={x} y1={0} y2={height} stroke="rgba(183,139,255,0.6)" strokeWidth="1.5" pointerEvents="none" />
        <line x1={x + width} x2={x + width} y1={0} y2={height} stroke="rgba(183,139,255,0.6)" strokeWidth="1.5" pointerEvents="none" />
        <rect
          x={x}
          y={0}
          width={width}
          height={headerHeight}
          fill={isDragging ? 'rgba(183,139,255,0.5)' : 'rgba(183,139,255,0.28)'}
          stroke="rgba(183,139,255,0.5)"
          strokeWidth="0.5"
          style={{ cursor: 'move' }}
          data-testid={`vibe-window-header-${win.id}`}
          data-scrub-ignore="1"
          onContextMenu={(event) => {
            event.preventDefault();
            onWindowDelete?.(win.id);
          }}
          onPointerDown={startDrag(win.id, 'move', win.t0, win.t1)}
        />
        <SvgFixedText
          x={x + 7}
          y={headerHeight / 2 + 3.5}
          scaleX={labelScaleX}
          scaleY={labelScaleY}
          testId={`vibe-window-label-${win.id}`}
          fontSize="9.5"
          fill="rgb(220,200,255)"
          fontWeight="700"
          letterSpacing="0.06em"
          pointerEvents="none"
        >
          {win.label.toUpperCase()}
        </SvgFixedText>
        <rect
          x={x - 5}
          y={0}
          width={10}
          height={height}
          fill="transparent"
          style={{ cursor: 'ew-resize' }}
          data-scrub-ignore="1"
          onPointerDown={startDrag(win.id, 'left', win.t0, win.t1)}
        />
        <rect
          x={x + width - 5}
          y={0}
          width={10}
          height={height}
          fill="transparent"
          style={{ cursor: 'ew-resize' }}
          data-scrub-ignore="1"
          onPointerDown={startDrag(win.id, 'right', win.t0, win.t1)}
        />
      </g>
    );
  });
}

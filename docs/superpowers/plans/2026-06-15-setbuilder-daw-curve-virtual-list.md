# Setbuilder DAW Curve Virtual List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add DAW-style horizontal curve zoom and large-set-safe virtualized timeline list rendering.

**Architecture:** `CurvePanel` owns curve zoom/scroll state and passes viewport props into `CurveEditor`, which renders a visible time range with level-of-detail rules. `TimelinePanel` keeps the vertical set list workflow but delegates row markup to a row component and uses a local measured virtualizer so only visible slot groups mount.

**Tech Stack:** Next.js 16, React 19, TypeScript, vanilla CSS modules, Vitest, Testing Library, no new runtime dependency.

---

## File Map

- Create: `dashboard/app/(dj)/setbuilder/components/curveViewport.ts`
  - Pure time/zoom/LOD helpers for the DAW curve viewport.
- Create: `dashboard/app/(dj)/setbuilder/__tests__/curveViewport.test.ts`
  - Unit tests for visible-range geometry, fit scale, zooming, and LOD thresholds.
- Modify: `dashboard/app/(dj)/setbuilder/components/CurveEditor.tsx`
  - Render visible slot geometry, hide handles/actions by LOD, expose horizontal scroll events.
- Modify: `dashboard/app/(dj)/setbuilder/components/CurvePanel.tsx`
  - Own `pxPerSecond`, `scrollLeft`, and viewport width; wire toolbar zoom controls.
- Modify: `dashboard/app/(dj)/setbuilder/components/CurveToolbar.tsx`
  - Add zoom out, zoom in, and fit controls.
- Create: `dashboard/app/(dj)/setbuilder/components/useMeasuredVirtualList.ts`
  - Local measured virtualizer hook for vertical slot groups.
- Create: `dashboard/app/(dj)/setbuilder/components/__tests__/useMeasuredVirtualList.test.tsx`
  - Unit-style hook/component tests for visible ranges and scroll-to-index math.
- Create: `dashboard/app/(dj)/setbuilder/components/TimelineRow.tsx`
  - Extract one slot group row with the current timeline interactions.
- Modify: `dashboard/app/(dj)/setbuilder/components/TimelinePanel.tsx`
  - Use the virtualizer, render spacers and visible rows, preserve row actions.
- Modify: `dashboard/app/(dj)/setbuilder/components/curve.module.css`
  - Add curve scroll viewport styles and virtualized list spacer/group styles.
- Modify: `dashboard/app/(dj)/setbuilder/__tests__/CurveEditor.test.tsx`
  - Update expectations for LOD and visible-range rendering.
- Modify: `dashboard/app/(dj)/setbuilder/__tests__/BuilderWorkspace.test.tsx`
  - Add large-set regression tests for curve simplification and virtualized list behavior.

---

### Task 1: Add Pure Curve Viewport Helpers

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/curveViewport.ts`
- Create: `dashboard/app/(dj)/setbuilder/__tests__/curveViewport.test.ts`

- [ ] **Step 1: Write failing tests for curve viewport math**

Create `dashboard/app/(dj)/setbuilder/__tests__/curveViewport.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { SlotView } from '../components/types';
import {
  CURVE_LOD_THRESHOLDS,
  clampPxPerSecond,
  curveViewportRange,
  fitPxPerSecond,
  lodForMedianSlotWidth,
  slotTimeRanges,
  visibleBlocksFromSlots,
  zoomPxPerSecond,
} from '../components/curveViewport';

function mkSlot(idx: number, durationSec = 200): SlotView {
  return {
    id: idx + 1,
    position: idx,
    locked: false,
    targetEnergy: null,
    transitionScore: null,
    nextPairingId: null,
    nextIsDjPairing: false,
    track: {
      id: `t${idx}`,
      title: `Track ${idx}`,
      artist: `Artist ${idx}`,
      durationSec,
      energy: 5 + (idx % 4),
      bpm: 120,
      key: '8A',
    },
  };
}

describe('curveViewport helpers', () => {
  it('computes slot time ranges from ordered slot durations', () => {
    const ranges = slotTimeRanges([mkSlot(0, 100), mkSlot(1, 200), mkSlot(2, 300)]);
    expect(ranges.map((r) => [r.startSec, r.endSec, r.midSec])).toEqual([
      [0, 100, 50],
      [100, 300, 200],
      [300, 600, 450],
    ]);
  });

  it('fits full duration into the visible viewport with a bounded scale', () => {
    expect(fitPxPerSecond({ totalSec: 1000, viewportWidth: 500 })).toBe(0.5);
    expect(fitPxPerSecond({ totalSec: 0, viewportWidth: 500 })).toBe(CURVE_LOD_THRESHOLDS.minPxPerSecond);
    expect(fitPxPerSecond({ totalSec: 1000, viewportWidth: 1 })).toBe(CURVE_LOD_THRESHOLDS.minPxPerSecond);
  });

  it('derives visible seconds from scroll and scale', () => {
    expect(curveViewportRange({ scrollLeft: 250, viewportWidth: 500, pxPerSecond: 2, totalSec: 1000 })).toEqual({
      startSec: 125,
      endSec: 375,
    });
  });

  it('returns only visible blocks plus overscan in viewport-local coordinates', () => {
    const slots = Array.from({ length: 20 }, (_, i) => mkSlot(i, 60));
    const blocks = visibleBlocksFromSlots({
      slots,
      visibleStartSec: 300,
      visibleEndSec: 600,
      pxPerSecond: 2,
      overscanSec: 60,
    });
    expect(blocks[0].idx).toBe(4);
    expect(blocks.at(-1)?.idx).toBe(10);
    expect(blocks[0].x0).toBe(-120);
    expect(blocks[1].x0).toBe(0);
    expect(blocks[1].width).toBe(120);
  });

  it('uses median visible slot width for LOD thresholds', () => {
    expect(lodForMedianSlotWidth([2, 3, 4])).toBe('overview');
    expect(lodForMedianSlotWidth([6, 12, 20])).toBe('medium');
    expect(lodForMedianSlotWidth([28, 60, 90])).toBe('detail');
  });

  it('zooms around a center point without exceeding configured bounds', () => {
    const next = zoomPxPerSecond({
      currentPxPerSecond: 1,
      direction: 'in',
      scrollLeft: 200,
      viewportWidth: 400,
      totalSec: 1000,
    });
    expect(next.pxPerSecond).toBeCloseTo(1.35);
    expect(next.scrollLeft).toBeCloseTo(340);

    const clamped = clampPxPerSecond(999);
    expect(clamped).toBe(CURVE_LOD_THRESHOLDS.maxPxPerSecond);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/curveViewport.test.ts
```

Expected: FAIL because `../components/curveViewport` does not exist.

- [ ] **Step 3: Implement curve viewport helpers**

Create `dashboard/app/(dj)/setbuilder/components/curveViewport.ts`:

```ts
import type { SlotView } from './types';
import { effectiveTarget } from './types';

export type CurveLod = 'overview' | 'medium' | 'detail';

export const CURVE_LOD_THRESHOLDS = {
  overviewMaxMedianSlotPx: 6,
  detailMinMedianSlotPx: 28,
  minPxPerSecond: 0.02,
  maxPxPerSecond: 12,
  zoomStep: 1.35,
} as const;

export interface SlotTimeRange {
  idx: number;
  slot: SlotView;
  startSec: number;
  endSec: number;
  midSec: number;
}

export interface VisibleSlotBlock extends SlotTimeRange {
  x0: number;
  x1: number;
  xMid: number;
  width: number;
  energy: number;
  target: number;
}

export function clampPxPerSecond(pxPerSecond: number): number {
  if (!Number.isFinite(pxPerSecond)) return CURVE_LOD_THRESHOLDS.minPxPerSecond;
  return Math.min(
    CURVE_LOD_THRESHOLDS.maxPxPerSecond,
    Math.max(CURVE_LOD_THRESHOLDS.minPxPerSecond, pxPerSecond),
  );
}

export function fitPxPerSecond({
  totalSec,
  viewportWidth,
}: {
  totalSec: number;
  viewportWidth: number;
}): number {
  if (totalSec <= 0 || viewportWidth <= 1) return CURVE_LOD_THRESHOLDS.minPxPerSecond;
  return clampPxPerSecond(viewportWidth / totalSec);
}

export function curveViewportRange({
  scrollLeft,
  viewportWidth,
  pxPerSecond,
  totalSec,
}: {
  scrollLeft: number;
  viewportWidth: number;
  pxPerSecond: number;
  totalSec: number;
}): { startSec: number; endSec: number } {
  const scale = clampPxPerSecond(pxPerSecond);
  const startSec = Math.max(0, scrollLeft / scale);
  const spanSec = Math.max(1, viewportWidth / scale);
  return {
    startSec,
    endSec: Math.min(Math.max(totalSec, 1), startSec + spanSec),
  };
}

export function slotTimeRanges(slots: SlotView[]): SlotTimeRange[] {
  let cursor = 0;
  return slots.map((slot, idx) => {
    const durationSec = Math.max(0, slot.track.durationSec);
    const startSec = cursor;
    const endSec = cursor + durationSec;
    cursor = endSec;
    return {
      idx,
      slot,
      startSec,
      endSec,
      midSec: startSec + durationSec / 2,
    };
  });
}

export function visibleBlocksFromSlots({
  slots,
  visibleStartSec,
  visibleEndSec,
  pxPerSecond,
  overscanSec = 0,
}: {
  slots: SlotView[];
  visibleStartSec: number;
  visibleEndSec: number;
  pxPerSecond: number;
  overscanSec?: number;
}): VisibleSlotBlock[] {
  const start = Math.max(0, visibleStartSec - overscanSec);
  const end = visibleEndSec + overscanSec;
  const scale = clampPxPerSecond(pxPerSecond);
  return slotTimeRanges(slots)
    .filter((range) => range.endSec > start && range.startSec < end)
    .map((range) => {
      const x0 = (range.startSec - visibleStartSec) * scale;
      const x1 = (range.endSec - visibleStartSec) * scale;
      return {
        ...range,
        x0,
        x1,
        xMid: (range.midSec - visibleStartSec) * scale,
        width: Math.max(0, x1 - x0),
        energy: range.slot.track.energy,
        target: effectiveTarget(range.slot),
      };
    });
}

export function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

export function lodForMedianSlotWidth(widths: number[]): CurveLod {
  const med = median(widths);
  if (med < CURVE_LOD_THRESHOLDS.overviewMaxMedianSlotPx) return 'overview';
  if (med < CURVE_LOD_THRESHOLDS.detailMinMedianSlotPx) return 'medium';
  return 'detail';
}

export function zoomPxPerSecond({
  currentPxPerSecond,
  direction,
  scrollLeft,
  viewportWidth,
  totalSec,
}: {
  currentPxPerSecond: number;
  direction: 'in' | 'out';
  scrollLeft: number;
  viewportWidth: number;
  totalSec: number;
}): { pxPerSecond: number; scrollLeft: number } {
  const current = clampPxPerSecond(currentPxPerSecond);
  const multiplier = direction === 'in'
    ? CURVE_LOD_THRESHOLDS.zoomStep
    : 1 / CURVE_LOD_THRESHOLDS.zoomStep;
  const nextScale = clampPxPerSecond(current * multiplier);
  const centerPx = scrollLeft + viewportWidth / 2;
  const centerSec = centerPx / current;
  const nextScroll = centerSec * nextScale - viewportWidth / 2;
  const maxScroll = Math.max(0, totalSec * nextScale - viewportWidth);
  return {
    pxPerSecond: nextScale,
    scrollLeft: Math.min(maxScroll, Math.max(0, nextScroll)),
  };
}
```

- [ ] **Step 4: Run the viewport helper test**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/curveViewport.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/\(dj\)/setbuilder/components/curveViewport.ts \
  dashboard/app/\(dj\)/setbuilder/__tests__/curveViewport.test.ts
git commit -m "test: add curve viewport math"
```

---

### Task 2: Render Curve By Viewport And Hide Dense Actions By LOD

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/CurveEditor.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/components/curve.module.css`
- Modify: `dashboard/app/(dj)/setbuilder/__tests__/CurveEditor.test.tsx`

- [ ] **Step 1: Add failing CurveEditor tests for LOD and visible range**

Append these tests inside the existing `describe('CurveEditor', () => { ... })` block in `dashboard/app/(dj)/setbuilder/__tests__/CurveEditor.test.tsx`:

```tsx
  it('renders only viewport-visible slot blocks in detail zoom', () => {
    // Regression for b2d595a: large sets must not render every SVG slot node at once.
    const slots = Array.from({ length: 200 }, (_, i) => mkSlot(i, { durationSec: 60 }));
    renderEditor({
      slots,
      pxPerSecond: 2,
      scrollLeft: 60 * 50 * 2,
      viewportWidth: 600,
    });

    expect(screen.queryByTestId('slot-block-0')).not.toBeInTheDocument();
    expect(screen.getByTestId('slot-block-50')).toBeInTheDocument();
    expect(document.querySelectorAll('[data-testid^="slot-block-"]').length).toBeLessThan(30);
  });

  it('hides per-slot drag handles at overview zoom', () => {
    // Regression for b2d595a: overview mode should not expose hundreds of tiny handles.
    const slots = Array.from({ length: 200 }, (_, i) => mkSlot(i, { durationSec: 60 }));
    renderEditor({
      slots,
      pxPerSecond: 0.02,
      scrollLeft: 0,
      viewportWidth: 600,
    });

    expect(screen.getByTestId('curve-lod')).toHaveTextContent('overview');
    expect(screen.queryByTestId('target-handle-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('slot-block-0')).not.toBeInTheDocument();
    expect(screen.getByTestId('curve-line')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/CurveEditor.test.tsx
```

Expected: FAIL because `CurveEditorProps` does not accept `pxPerSecond`, `scrollLeft`, or `viewportWidth`, and it renders all blocks/handles.

- [ ] **Step 3: Add viewport props and imports to CurveEditor**

Modify `dashboard/app/(dj)/setbuilder/components/CurveEditor.tsx` imports:

```ts
import {
  curveViewportRange,
  fitPxPerSecond,
  lodForMedianSlotWidth,
  visibleBlocksFromSlots,
} from './curveViewport';
```

Extend `CurveEditorProps`:

```ts
  pxPerSecond?: number;
  scrollLeft?: number;
  viewportWidth?: number;
  onScrollLeftChange?: (scrollLeft: number) => void;
  onViewportWidthChange?: (width: number) => void;
```

Add defaults in the component parameter list:

```ts
  pxPerSecond,
  scrollLeft = 0,
  viewportWidth,
  onScrollLeftChange,
  onViewportWidthChange,
```

Add a scroll viewport ref next to the existing refs:

```ts
  const scrollViewportRef = useRef<HTMLDivElement>(null);
```

- [ ] **Step 4: Replace curve geometry setup in CurveEditor**

Replace the current block from `const totalSec = ...` through `const blocks = ...` with:

```ts
  const totalSec = slots.reduce((acc, s) => acc + s.track.durationSec, 0);
  const rawTargetSec = rawTargetSecForSlots(
    targetDurationSec,
    slots.length,
    avgTransitionOverlapSec,
  );
  const domainSec = Math.max(totalSec, rawTargetSec ?? 0, 1);
  const effectiveViewportWidth = viewportWidth ?? w;
  const effectivePxPerSecond = pxPerSecond ?? fitPxPerSecond({
    totalSec: domainSec,
    viewportWidth: effectiveViewportWidth,
  });
  const visibleRange = curveViewportRange({
    scrollLeft,
    viewportWidth: effectiveViewportWidth,
    pxPerSecond: effectivePxPerSecond,
    totalSec: domainSec,
  });
  const overscanSec = Math.max(30, effectiveViewportWidth / effectivePxPerSecond);
  const targetX = rawTargetSec == null
    ? null
    : Math.round((rawTargetSec - visibleRange.startSec) * effectivePxPerSecond);
  const baseBlocks = visibleBlocksFromSlots({
    slots,
    visibleStartSec: visibleRange.startSec,
    visibleEndSec: visibleRange.endSec,
    pxPerSecond: effectivePxPerSecond,
    overscanSec,
  });
  const blocks = baseBlocks.map((b) =>
    dragIdx === b.idx && dragEnergy != null ? { ...b, target: dragEnergy } : b,
  );
  const lod = lodForMedianSlotWidth(blocks.map((b) => b.width));
  const showBlocks = lod !== 'overview';
  const showSlotHandles = lod === 'detail';
  const showDenseSeams = lod === 'detail';
  const scrollableWidth = Math.max(effectiveViewportWidth, domainSec * effectivePxPerSecond);
```

Replace the target-drag `onUp` block lookup:

```ts
        const b = blocks.find((block) => block.idx === dragIdx);
```

This matters because `blocks` becomes a visible subset while `dragIdx` remains the global slot
index.

- [ ] **Step 5: Add scroll container behavior**

Wrap the existing `<svg ...>` with a scroll viewport and an inner spacer. The return should start:

```tsx
    <div
      className={styles.canvasWrap}
      ref={wrapRef}
      data-testid="curve-canvas"
      data-lod={lod}
    >
      <span data-testid="curve-lod" className={styles.srOnly}>{lod}</span>
      <div
        ref={scrollViewportRef}
        className={styles.curveScrollViewport}
        data-testid="curve-scroll-viewport"
        onScroll={(event) => onScrollLeftChange?.(event.currentTarget.scrollLeft)}
      >
        <div
          className={styles.curveScrollInner}
          style={{ width: scrollableWidth }}
          aria-hidden="true"
        />
        <svg
          ref={svgRef}
          className={styles.svg}
          viewBox={`0 0 ${effectiveViewportWidth} ${h}`}
          preserveAspectRatio="none"
          onClickCapture={handleSvgClickCapture}
        >
```

Close the two new divs after `</svg>`.

Update the resize observer to notify `CurvePanel`:

```ts
        const nextW = Math.max(300, e.contentRect.width);
        const nextH = Math.max(140, e.contentRect.height);
        setW(nextW);
        setH(nextH);
        onViewportWidthChange?.(nextW);
```

Keep the effect dependency array as `[onViewportWidthChange]`.

Add this effect after the resize observer so programmatic zoom/fit scroll state updates the DOM
scroll container:

```ts
  useEffect(() => {
    if (!scrollViewportRef.current) return;
    if (Math.abs(scrollViewportRef.current.scrollLeft - scrollLeft) < 1) return;
    scrollViewportRef.current.scrollLeft = scrollLeft;
  }, [scrollLeft]);
```

- [ ] **Step 6: Gate dense SVG groups by LOD**

Wrap current slot block rendering:

```tsx
        {showBlocks && blocks.map((b) => {
```

Wrap friction seams and use global slot indices from each visible block:

```tsx
        {showDenseSeams && view !== 'normal' &&
          blocks.slice(0, -1).map((b, i) => {
            const next = blocks[i + 1];
            const a = slots[b.idx].track;
            const z = slots[next.idx].track;
```

Inside the existing seam block, replace local-index hover and test IDs with global-index values:

```tsx
            const isHovered = hoveredIdx === b.idx || hoveredIdx === next.idx;
            return (
              <g key={`seam-${b.idx}`} pointerEvents="none" data-testid={`seam-${view}-${b.idx}`}>
```

Use `b.idx` for `seam-band` and `seam-chip` test IDs:

```tsx
                  data-testid={`seam-band-${b.idx}`}
```

```tsx
                    data-testid={`seam-chip-${b.idx}`}
```

Wrap pairing seam markers and use global slot indices:

```tsx
        {showDenseSeams && blocks.slice(0, -1).map((b, i) => {
          if (!slots[b.idx].nextIsDjPairing) return null;
          const next = blocks[i + 1];
```

Use `b.idx` in the pairing key/test ID:

```tsx
              key={`pairing-pin-${b.idx}`}
              data-testid={`pairing-pin-${b.idx}`}
```

Wrap target handles:

```tsx
        {showSlotHandles && blocks.map((b) => {
```

Keep the derived `curve-line` rendering in all LOD modes.

- [ ] **Step 7: Fix viewport-local coordinate calculations**

Replace target marker and over-region width calculations with viewport-local math:

```tsx
            {totalSec > rawTargetSec && targetX != null ? (
              <rect
                data-testid="curve-over-region"
                x={targetX}
                y={0}
                width={Math.max(0, ((totalSec - rawTargetSec) * effectivePxPerSecond))}
                height={h}
                fill="rgba(245,158,11,0.12)"
              />
            ) : null}
```

Replace `secToX`:

```ts
  const secToX = (sec: number) =>
    (Math.max(0, Math.min(domainSec, sec)) - visibleRange.startSec) * effectivePxPerSecond;
```

Replace scrub mapping:

```ts
    const sec = visibleRange.startSec + t * (effectiveViewportWidth / effectivePxPerSecond);
    onScrub(Math.min(totalSec, Math.max(0, sec)));
```

Replace vibe window x/width math:

```ts
          const startSec = win.t0 * domainSec;
          const endSec = win.t1 * domainSec;
          const x = (startSec - visibleRange.startSec) * effectivePxPerSecond;
          const width = Math.max(2, (endSec - startSec) * effectivePxPerSecond);
```

- [ ] **Step 8: Add CSS for curve scroll viewport**

Add to `dashboard/app/(dj)/setbuilder/components/curve.module.css` near `.canvasWrap`:

```css
.curveScrollViewport {
  position: absolute;
  inset: 0;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}

.curveScrollInner {
  height: 1px;
  pointer-events: none;
}

.srOnly {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

Keep `.svg` absolute and visible as it is today.

- [ ] **Step 9: Run CurveEditor tests**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/curveViewport.test.ts app/\(dj\)/setbuilder/__tests__/CurveEditor.test.tsx
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add dashboard/app/\(dj\)/setbuilder/components/CurveEditor.tsx \
  dashboard/app/\(dj\)/setbuilder/components/curve.module.css \
  dashboard/app/\(dj\)/setbuilder/__tests__/CurveEditor.test.tsx
git commit -m "fix: render setbuilder curve by viewport"
```

---

### Task 3: Add Curve Toolbar Zoom Controls And CurvePanel State

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/CurveToolbar.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/components/CurvePanel.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/components/curve.module.css`
- Modify: `dashboard/app/(dj)/setbuilder/__tests__/BuilderWorkspace.test.tsx`

- [ ] **Step 1: Add failing integration test for zoom controls**

Add this test to `BuilderWorkspace.test.tsx`:

```tsx
  it('zooms the curve timeline in, out, and back to fit', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('curve-toolbar')).toBeInTheDocument());

    const canvas = screen.getByTestId('curve-canvas');
    const initialScale = canvas.getAttribute('data-px-per-second');

    fireEvent.click(screen.getByTestId('curve-zoom-in'));
    expect(screen.getByTestId('curve-canvas').getAttribute('data-px-per-second')).not.toBe(initialScale);

    fireEvent.click(screen.getByTestId('curve-zoom-out'));
    fireEvent.click(screen.getByTestId('curve-zoom-fit'));

    expect(screen.getByTestId('curve-zoom-label')).toHaveTextContent('Fit');
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/BuilderWorkspace.test.tsx -t "zooms the curve"
```

Expected: FAIL because zoom controls do not exist.

- [ ] **Step 3: Extend CurveToolbar props and markup**

In `CurveToolbarProps`, add:

```ts
  zoomLabel: string;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomFit: () => void;
```

Destructure these props:

```ts
  zoomLabel,
  onZoomIn,
  onZoomOut,
  onZoomFit,
```

Insert this block after the view switch:

```tsx
      <div className={styles.zoomControls} aria-label="Curve zoom controls">
        <button
          type="button"
          className={styles.toolbarIconBtn}
          onClick={onZoomOut}
          data-testid="curve-zoom-out"
          aria-label="Zoom out"
          title="Zoom out"
        >
          -
        </button>
        <span className={styles.zoomLabel} data-testid="curve-zoom-label">
          {zoomLabel}
        </span>
        <button
          type="button"
          className={styles.toolbarIconBtn}
          onClick={onZoomIn}
          data-testid="curve-zoom-in"
          aria-label="Zoom in"
          title="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          className={styles.toolbarBtn}
          onClick={onZoomFit}
          data-testid="curve-zoom-fit"
        >
          Fit
        </button>
      </div>
```

- [ ] **Step 4: Add toolbar CSS**

Add near toolbar styles in `curve.module.css`:

```css
.zoomControls {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding-left: 0.25rem;
}

.toolbarIconBtn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-raised);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: var(--font-mono), monospace;
  font-size: 0.875rem;
}

.toolbarIconBtn:hover {
  color: var(--text);
  border-color: var(--text-tertiary);
}

.zoomLabel {
  min-width: 2.75rem;
  color: var(--text-tertiary);
  font-family: var(--font-mono), monospace;
  font-size: 0.625rem;
  text-align: center;
}
```

- [ ] **Step 5: Wire CurvePanel zoom state**

In `CurvePanel.tsx`, import helpers:

```ts
import {
  fitPxPerSecond,
  zoomPxPerSecond,
} from './curveViewport';
```

Add state near existing `useState` calls:

```ts
  const [curveViewportWidth, setCurveViewportWidth] = useState(800);
  const [curvePxPerSecond, setCurvePxPerSecond] = useState(0.08);
  const [curveScrollLeft, setCurveScrollLeft] = useState(0);
  const [curveFitMode, setCurveFitMode] = useState(true);
```

Add derived values and handlers after `totalSec`:

```ts
  const curveDomainSec = Math.max(totalSec, targetDurationSec ?? 0, 1);
  const fitScale = fitPxPerSecond({
    totalSec: curveDomainSec,
    viewportWidth: curveViewportWidth,
  });
  const effectiveCurvePxPerSecond = curveFitMode ? fitScale : curvePxPerSecond;
  const zoomLabel = curveFitMode ? 'Fit' : `${Math.round(effectiveCurvePxPerSecond * 60)} px/min`;

  const zoomCurve = (direction: 'in' | 'out') => {
    const next = zoomPxPerSecond({
      currentPxPerSecond: effectiveCurvePxPerSecond,
      direction,
      scrollLeft: curveScrollLeft,
      viewportWidth: curveViewportWidth,
      totalSec: curveDomainSec,
    });
    setCurveFitMode(false);
    setCurvePxPerSecond(next.pxPerSecond);
    setCurveScrollLeft(next.scrollLeft);
  };

  const fitCurve = () => {
    setCurveFitMode(true);
    setCurveScrollLeft(0);
  };
```

Pass the new props to `CurveToolbar`:

```tsx
        zoomLabel={zoomLabel}
        onZoomIn={() => zoomCurve('in')}
        onZoomOut={() => zoomCurve('out')}
        onZoomFit={fitCurve}
```

Pass viewport props to `CurveEditor`:

```tsx
        pxPerSecond={effectiveCurvePxPerSecond}
        scrollLeft={curveScrollLeft}
        viewportWidth={curveViewportWidth}
        onScrollLeftChange={(next) => {
          setCurveFitMode(false);
          setCurveScrollLeft(next);
        }}
        onViewportWidthChange={setCurveViewportWidth}
```

- [ ] **Step 6: Expose scale for tests**

In `CurveEditor.tsx`, add these attributes to `curve-canvas`:

```tsx
      data-px-per-second={effectivePxPerSecond.toFixed(4)}
      data-scroll-left={scrollLeft.toFixed(0)}
```

- [ ] **Step 7: Run BuilderWorkspace zoom test**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/BuilderWorkspace.test.tsx -t "zooms the curve"
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add dashboard/app/\(dj\)/setbuilder/components/CurveToolbar.tsx \
  dashboard/app/\(dj\)/setbuilder/components/CurvePanel.tsx \
  dashboard/app/\(dj\)/setbuilder/components/CurveEditor.tsx \
  dashboard/app/\(dj\)/setbuilder/components/curve.module.css \
  dashboard/app/\(dj\)/setbuilder/__tests__/BuilderWorkspace.test.tsx
git commit -m "feat: add DAW curve zoom controls"
```

---

### Task 4: Add A Local Measured Virtual List Hook

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/useMeasuredVirtualList.ts`
- Create: `dashboard/app/(dj)/setbuilder/components/__tests__/useMeasuredVirtualList.test.tsx`

- [ ] **Step 1: Write failing virtualizer tests**

Create `dashboard/app/(dj)/setbuilder/components/__tests__/useMeasuredVirtualList.test.tsx`:

```tsx
import { renderHook, act } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useMeasuredVirtualList } from '../useMeasuredVirtualList';

describe('useMeasuredVirtualList', () => {
  it('returns a bounded visible range with spacer heights', () => {
    const { result } = renderHook(() =>
      useMeasuredVirtualList({
        itemCount: 500,
        estimateHeight: 48,
        viewportHeight: 240,
        scrollTop: 480,
        overscan: 2,
      }),
    );

    expect(result.current.startIdx).toBe(8);
    expect(result.current.endIdx).toBe(17);
    expect(result.current.beforeHeight).toBe(384);
    expect(result.current.afterHeight).toBe((500 - 17) * 48);
    expect(result.current.items.map((item) => item.idx)).toEqual([8, 9, 10, 11, 12, 13, 14, 15, 16]);
  });

  it('uses measured heights for offsets and scroll targets', () => {
    const { result } = renderHook(() =>
      useMeasuredVirtualList({
        itemCount: 10,
        estimateHeight: 50,
        viewportHeight: 150,
        scrollTop: 0,
        overscan: 1,
      }),
    );

    act(() => {
      result.current.setMeasuredHeight(0, 80);
      result.current.setMeasuredHeight(1, 20);
    });

    expect(result.current.scrollTopForIndex(2)).toBe(100);
    expect(result.current.indexFromScrollTop(99)).toBe(1);
    expect(result.current.indexFromScrollTop(100)).toBe(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/components/__tests__/useMeasuredVirtualList.test.tsx
```

Expected: FAIL because the hook does not exist.

- [ ] **Step 3: Implement the hook**

Create `dashboard/app/(dj)/setbuilder/components/useMeasuredVirtualList.ts`:

```ts
'use client';

import { useCallback, useMemo, useState } from 'react';

export interface VirtualListItem {
  idx: number;
  key: number;
  top: number;
  height: number;
}

export interface UseMeasuredVirtualListInput {
  itemCount: number;
  estimateHeight: number;
  viewportHeight: number;
  scrollTop: number;
  overscan?: number;
}

export interface UseMeasuredVirtualListResult {
  startIdx: number;
  endIdx: number;
  beforeHeight: number;
  afterHeight: number;
  totalHeight: number;
  items: VirtualListItem[];
  setMeasuredHeight: (idx: number, height: number) => void;
  scrollTopForIndex: (idx: number) => number;
  indexFromScrollTop: (top: number) => number;
}

function buildOffsets(itemCount: number, estimateHeight: number, measured: Map<number, number>) {
  const offsets: number[] = new Array(itemCount + 1);
  offsets[0] = 0;
  for (let i = 0; i < itemCount; i++) {
    offsets[i + 1] = offsets[i] + (measured.get(i) ?? estimateHeight);
  }
  return offsets;
}

function findIndexAtOffset(offsets: number[], top: number): number {
  if (offsets.length <= 1) return 0;
  let lo = 0;
  let hi = offsets.length - 2;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (offsets[mid + 1] <= top) lo = mid + 1;
    else if (offsets[mid] > top) hi = mid - 1;
    else return mid;
  }
  return Math.max(0, Math.min(offsets.length - 2, lo));
}

export function useMeasuredVirtualList({
  itemCount,
  estimateHeight,
  viewportHeight,
  scrollTop,
  overscan = 4,
}: UseMeasuredVirtualListInput): UseMeasuredVirtualListResult {
  const [measuredHeights, setMeasuredHeights] = useState<Map<number, number>>(() => new Map());

  const offsets = useMemo(
    () => buildOffsets(itemCount, estimateHeight, measuredHeights),
    [estimateHeight, itemCount, measuredHeights],
  );

  const totalHeight = offsets[itemCount] ?? 0;
  const rawStart = findIndexAtOffset(offsets, Math.max(0, scrollTop));
  const rawEnd = findIndexAtOffset(offsets, Math.max(0, scrollTop + viewportHeight));
  const startIdx = Math.max(0, rawStart - overscan);
  const endIdx = Math.min(itemCount, rawEnd + overscan + 1);
  const beforeHeight = offsets[startIdx] ?? 0;
  const afterHeight = Math.max(0, totalHeight - (offsets[endIdx] ?? totalHeight));

  const items = useMemo(
    () =>
      Array.from({ length: Math.max(0, endIdx - startIdx) }, (_, offset) => {
        const idx = startIdx + offset;
        return {
          idx,
          key: idx,
          top: offsets[idx] ?? 0,
          height: (offsets[idx + 1] ?? 0) - (offsets[idx] ?? 0),
        };
      }),
    [endIdx, offsets, startIdx],
  );

  const setMeasuredHeight = useCallback((idx: number, height: number) => {
    if (!Number.isFinite(height) || height <= 0) return;
    setMeasuredHeights((prev) => {
      if (prev.get(idx) === height) return prev;
      const next = new Map(prev);
      next.set(idx, height);
      return next;
    });
  }, []);

  const scrollTopForIndex = useCallback(
    (idx: number) => offsets[Math.max(0, Math.min(itemCount, idx))] ?? 0,
    [itemCount, offsets],
  );

  const indexFromScrollTop = useCallback(
    (top: number) => findIndexAtOffset(offsets, top),
    [offsets],
  );

  return {
    startIdx,
    endIdx,
    beforeHeight,
    afterHeight,
    totalHeight,
    items,
    setMeasuredHeight,
    scrollTopForIndex,
    indexFromScrollTop,
  };
}
```

- [ ] **Step 4: Run virtualizer tests**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/components/__tests__/useMeasuredVirtualList.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/\(dj\)/setbuilder/components/useMeasuredVirtualList.ts \
  dashboard/app/\(dj\)/setbuilder/components/__tests__/useMeasuredVirtualList.test.tsx
git commit -m "test: add measured timeline virtualizer"
```

---

### Task 5: Extract Timeline Row Without Changing Behavior

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/TimelineRow.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/components/TimelinePanel.tsx`

- [ ] **Step 1: Create TimelineRow component**

Create `dashboard/app/(dj)/setbuilder/components/TimelineRow.tsx` by moving the slot-group JSX from `TimelinePanel.tsx` into this component:

```tsx
'use client';

import { type DragEvent, useState } from 'react';
import { fmtTime } from './curveMath';
import { readPoolTrackDragPayload } from './dnd';
import { localPositionSec } from './transportMath';
import type { SlotView } from './types';
import { effectiveTarget } from './types';
import styles from './curve.module.css';

export interface TimelineRowProps {
  slot: SlotView;
  prevSlot: SlotView | null;
  nextSlot: SlotView | null;
  idx: number;
  slots: SlotView[];
  hoveredIdx: number | null;
  currentIdx: number;
  positionSec: number;
  playing: boolean;
  dropIdx: number | null;
  setDropIdx: (idx: number | null) => void;
  onHover: (idx: number | null) => void;
  onRowDoubleClick?: (idx: number) => void;
  onPoolTrackDrop?: (poolTrackId: number, insertIdx: number) => void | Promise<void>;
  setMenu: (menu: { x: number; y: number; idx: number } | null) => void;
  setRowRef?: (idx: number, el: HTMLDivElement | null) => void;
  measureRef?: (idx: number, el: HTMLDivElement | null) => void;
}

export default function TimelineRow({
  slot,
  prevSlot,
  nextSlot,
  idx,
  slots,
  hoveredIdx,
  currentIdx,
  positionSec,
  playing,
  dropIdx,
  setDropIdx,
  onHover,
  onRowDoubleClick,
  onPoolTrackDrop,
  setMenu,
  setRowRef,
  measureRef,
}: TimelineRowProps) {
  const [localDropIdx, setLocalDropIdx] = useState<number | null>(null);
  const seamScore = prevSlot?.transitionScore ?? slot.transitionScore;
  const isPairedSeam = Boolean(prevSlot?.nextIsDjPairing);
  const isCurrent = currentIdx === idx;
  const progress =
    isCurrent && slot.track.durationSec > 0
      ? Math.min(
          100,
          Math.max(0, (localPositionSec(slots, idx, positionSec) / slot.track.durationSec) * 100),
        )
      : 0;
  const pairingActionLabel = slot.nextIsDjPairing
    ? `Open saved pairing after ${slot.track.title}`
    : `Save ${slot.track.title} into ${nextSlot?.track.title ?? 'next track'} as pairing`;

  const markPoolTrackDrop = (event: DragEvent<HTMLElement>, insertIdx: number) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    setDropIdx(insertIdx);
    setLocalDropIdx(insertIdx);
  };

  const handlePoolTrackDrop = (event: DragEvent<HTMLElement>, insertIdx: number) => {
    event.preventDefault();
    event.stopPropagation();
    setDropIdx(null);
    setLocalDropIdx(null);
    const payload = readPoolTrackDragPayload(event.dataTransfer);
    if (!payload) return;
    void onPoolTrackDrop?.(payload.poolTrackId, insertIdx);
  };

  const clearDropIfLeaving = (event: DragEvent<HTMLElement>) => {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
    setDropIdx(null);
    setLocalDropIdx(null);
  };

  const groupDropIdx = localDropIdx ?? dropIdx;

  return (
    <div
      className={styles.timelineSlotGroup}
      ref={(el) => measureRef?.(idx, el)}
      data-testid={`timeline-slot-group-${idx}`}
    >
      {idx > 0 && (isPairedSeam || seamScore != null) && (
        <div
          className={`${styles.timelineTransition} ${
            isPairedSeam ? styles.timelineTransitionPairing : ''
          }`}
          data-testid={`timeline-transition-${idx - 1}`}
        >
          {seamScore != null && (
            <span className={styles.timelineScoreChip}>{Math.round(seamScore)}</span>
          )}
          {isPairedSeam && (
            <span className={styles.timelinePairingChip}>
              <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M10.5 13.5 13.5 10.5M8.5 17.5H7.8a4.8 4.8 0 0 1 0-9.6h3.4M12.8 16.1h3.4a4.8 4.8 0 1 0 0-9.6h-.7"
                  fill="none"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.9"
                />
              </svg>
              DJ pairing
            </span>
          )}
        </div>
      )}
      <div
        ref={(el) => setRowRef?.(idx, el)}
        className={`${styles.timelineRow} ${hoveredIdx === idx ? styles.timelineRowHover : ''} ${
          isCurrent ? styles.timelineRowNow : ''
        } ${groupDropIdx === idx ? styles.timelineRowDrop : ''}`}
        onMouseEnter={() => onHover(idx)}
        onMouseLeave={() => onHover(null)}
        onDoubleClick={() => onRowDoubleClick?.(idx)}
        onDragOver={(event) => {
          event.stopPropagation();
          markPoolTrackDrop(event, idx);
        }}
        onDragLeave={clearDropIfLeaving}
        onDrop={(event) => handlePoolTrackDrop(event, idx)}
        onContextMenu={(event) => {
          if (!nextSlot) return;
          event.preventDefault();
          setMenu({ x: event.clientX, y: event.clientY, idx });
        }}
        data-testid={`timeline-row-${idx}`}
      >
        {isCurrent ? (
          <span
            className={styles.timelineRowProgress}
            style={{ width: `${progress}%` }}
            aria-hidden="true"
          />
        ) : null}
        <span className={styles.timelinePos}>
          {isCurrent ? (
            playing ? (
              <span className={`${styles.rowVu} ${styles.rowVuActive}`} data-testid={`timeline-vu-${idx}`}>
                <span />
                <span />
                <span />
                <span />
              </span>
            ) : (
              <span className={styles.timelinePauseIcon} data-testid={`timeline-pause-${idx}`}>
                <span />
                <span />
              </span>
            )
          ) : (
            String(idx + 1).padStart(2, '0')
          )}
        </span>
        <span className={styles.timelineTitle}>
          {slot.track.title}
          {slot.track.artist ? (
            <span className={styles.timelineArtist}> - {slot.track.artist}</span>
          ) : null}
        </span>
        <span className={styles.timelineBadge}>{fmtTime(slot.track.durationSec)}</span>
        <span className={styles.timelineBadge}>
          {slot.track.bpm != null ? `${Math.round(slot.track.bpm)} BPM` : '- BPM'}
        </span>
        <span className={styles.timelineBadge}>{slot.track.key ?? '-'}</span>
        <span className={styles.timelineBadge}>e{slot.track.energy}</span>
        <span className={styles.timelineTarget} title="Target energy">
          ◎ {effectiveTarget(slot).toFixed(1)}
        </span>
        {nextSlot && (
          <button
            type="button"
            className={styles.timelinePairingAction}
            aria-label={pairingActionLabel}
            title={pairingActionLabel}
            onClick={(event) => {
              event.stopPropagation();
              const rect = event.currentTarget.getBoundingClientRect();
              setMenu({ x: rect.left, y: rect.bottom + 4, idx });
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M10.5 13.5 13.5 10.5M8.5 17.5H7.8a4.8 4.8 0 0 1 0-9.6h3.4M12.8 16.1h3.4a4.8 4.8 0 1 0 0-9.6h-.7"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.9"
              />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Replace TimelinePanel map body with TimelineRow**

In `TimelinePanel.tsx`, remove imports that moved to `TimelineRow`:

```ts
import { type DragEvent, useEffect, useRef, useState } from 'react';
```

should become:

```ts
import { type DragEvent, useEffect, useRef, useState } from 'react';
import TimelineRow from './TimelineRow';
```

Keep current top-level list drop helpers.

Replace the full `slots.map((s, i) => { ... })` JSX with:

```tsx
      {slots.map((slot, i) => (
        <TimelineRow
          key={slot.id}
          slot={slot}
          prevSlot={i > 0 ? slots[i - 1] : null}
          nextSlot={slots[i + 1] ?? null}
          idx={i}
          slots={slots}
          hoveredIdx={hoveredIdx}
          currentIdx={currentIdx}
          positionSec={positionSec}
          playing={playing}
          dropIdx={dropIdx}
          setDropIdx={setDropIdx}
          onHover={onHover}
          onRowDoubleClick={onRowDoubleClick}
          onPoolTrackDrop={onPoolTrackDrop}
          setMenu={setMenu}
          setRowRef={(idx, el) => {
            rowRefs.current[idx] = el;
          }}
        />
      ))}
```

- [ ] **Step 3: Run existing timeline behavior tests**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/BuilderWorkspace.test.tsx -t "timeline|dropping|double-clicking|pairing"
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/\(dj\)/setbuilder/components/TimelineRow.tsx \
  dashboard/app/\(dj\)/setbuilder/components/TimelinePanel.tsx
git commit -m "refactor: extract setbuilder timeline row"
```

---

### Task 6: Virtualize TimelinePanel While Preserving Row Actions

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/TimelinePanel.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/components/curve.module.css`
- Modify: `dashboard/app/(dj)/setbuilder/__tests__/BuilderWorkspace.test.tsx`

- [ ] **Step 1: Add failing large-list virtualized behavior test**

Add helpers near `documentSnapshot()` in `BuilderWorkspace.test.tsx`:

```ts
function largeSlots(count: number): SetSlotOut[] {
  return Array.from({ length: count }, (_, idx) => ({
    ...SLOTS[idx % SLOTS.length],
    id: idx + 1,
    position: idx,
    track_id: `large-${idx}`,
    target_energy: idx % 3 === 0 ? 7 : null,
  }));
}

function largePoolTracks(count: number): PoolTrack[] {
  return Array.from({ length: count }, (_, idx) => ({
    ...POOL_TRACKS[idx % POOL_TRACKS.length],
    id: 1000 + idx,
    track_id: `large-${idx}`,
    title: `Large Track ${idx}`,
    artist: `Large Artist ${idx}`,
    duration_sec: 180 + (idx % 40),
  }));
}
```

Add test:

```tsx
  it('virtualizes hundreds of timeline rows while preserving visible row actions', async () => {
    // Regression for b2d595a: large timelines must not mount every row.
    mockGetSetSlots.mockResolvedValue(largeSlots(400));
    mockGetPool.mockResolvedValue({ sources: [], tracks: largePoolTracks(400) });

    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-0')).toBeInTheDocument());

    expect(screen.getByTestId('timeline-list')).toHaveAttribute('data-virtualized', 'true');
    expect(document.querySelectorAll('[data-testid^="timeline-row-"]').length).toBeLessThan(60);

    fireEvent.doubleClick(screen.getByTestId('timeline-row-1'));
    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));
    expect(mockSendTransportCommand).toHaveBeenCalledWith(
      5,
      expect.objectContaining({
        action: 'play',
        slot_index: 1,
        title: 'Large Track 1',
      }),
    );
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/BuilderWorkspace.test.tsx -t "virtualizes hundreds"
```

Expected: FAIL because `TimelinePanel` still renders every row and has no `data-virtualized` attribute.

- [ ] **Step 3: Import virtualizer in TimelinePanel**

In `TimelinePanel.tsx`, add:

```ts
import { useMeasuredVirtualList } from './useMeasuredVirtualList';
```

Add constants near imports:

```ts
const TIMELINE_ESTIMATED_SLOT_GROUP_HEIGHT = 52;
const TIMELINE_OVERSCAN = 8;
```

- [ ] **Step 4: Add viewport height and scroll state**

Inside `TimelinePanel`, add state after existing `dropIdx`:

```ts
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(480);
```

Add resize observer:

```ts
  useEffect(() => {
    if (!listRef.current) return;
    const list = listRef.current;
    const update = () => setViewportHeight(Math.max(1, list.clientHeight));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(list);
    return () => ro.disconnect();
  }, []);
```

Create virtualizer:

```ts
  const virtual = useMeasuredVirtualList({
    itemCount: slots.length,
    estimateHeight: TIMELINE_ESTIMATED_SLOT_GROUP_HEIGHT,
    viewportHeight,
    scrollTop,
    overscan: TIMELINE_OVERSCAN,
  });
```

- [ ] **Step 5: Replace scrollRequest DOM-ref behavior**

Replace the `scrollRequest` effect with:

```ts
  useEffect(() => {
    if (!scrollRequest || !listRef.current) return;
    listRef.current.scrollTop = virtual.scrollTopForIndex(scrollRequest.idx);
    setScrollTop(listRef.current.scrollTop);
  }, [scrollRequest, virtual.scrollTopForIndex]);
```

- [ ] **Step 6: Render virtual spacers and visible TimelineRows**

Add `onScroll` to the list div:

```tsx
      onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
      data-virtualized="true"
```

Replace the row render block with:

```tsx
      <div style={{ height: virtual.beforeHeight }} aria-hidden="true" />
      {virtual.items.map(({ idx }) => {
        const slot = slots[idx];
        if (!slot) return null;
        return (
          <TimelineRow
            key={slot.id}
            slot={slot}
            prevSlot={idx > 0 ? slots[idx - 1] : null}
            nextSlot={slots[idx + 1] ?? null}
            idx={idx}
            slots={slots}
            hoveredIdx={hoveredIdx}
            currentIdx={currentIdx}
            positionSec={positionSec}
            playing={playing}
            dropIdx={dropIdx}
            setDropIdx={setDropIdx}
            onHover={onHover}
            onRowDoubleClick={onRowDoubleClick}
            onPoolTrackDrop={onPoolTrackDrop}
            setMenu={setMenu}
            setRowRef={(rowIdx, el) => {
              rowRefs.current[rowIdx] = el;
            }}
            measureRef={(rowIdx, el) => {
              if (el) virtual.setMeasuredHeight(rowIdx, el.getBoundingClientRect().height);
            }}
          />
        );
      })}
      <div style={{ height: virtual.afterHeight }} aria-hidden="true" />
```

- [ ] **Step 7: Preserve list-level append drop behavior**

Keep existing list-level `onDragOver`, `onDragLeave`, and `onDrop`. Update append drop index to use pointer position when dropping on the virtualized list background:

```ts
  const insertIdxFromListPointer = (event: DragEvent<HTMLElement>) => {
    const list = listRef.current;
    if (!list) return slots.length;
    const rect = list.getBoundingClientRect();
    const top = list.scrollTop + Math.max(0, event.clientY - rect.top);
    return Math.max(0, Math.min(slots.length, virtual.indexFromScrollTop(top)));
  };
```

Use it in list-level handlers:

```tsx
      onDragOver={(event) => markPoolTrackDrop(event, insertIdxFromListPointer(event))}
      onDrop={(event) => handlePoolTrackDrop(event, insertIdxFromListPointer(event))}
```

Visible row drops still use exact row index from `TimelineRow`.

- [ ] **Step 8: Run timeline virtualizer test**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/BuilderWorkspace.test.tsx -t "virtualizes hundreds"
```

Expected: PASS.

- [ ] **Step 9: Run existing timeline behavior tests**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/BuilderWorkspace.test.tsx -t "timeline|dropping|double-clicking|pairing|click on a curve block"
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add dashboard/app/\(dj\)/setbuilder/components/TimelinePanel.tsx \
  dashboard/app/\(dj\)/setbuilder/components/curve.module.css \
  dashboard/app/\(dj\)/setbuilder/__tests__/BuilderWorkspace.test.tsx
git commit -m "fix: virtualize setbuilder timeline list"
```

---

### Task 7: Large-Set Curve Integration And Full Verification

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/__tests__/BuilderWorkspace.test.tsx`

- [ ] **Step 1: Add large-set curve regression test**

Add this test to `BuilderWorkspace.test.tsx`:

```tsx
  it('uses overview curve LOD for hundreds of tracks at fit zoom', async () => {
    // Regression for b2d595a: fit zoom must not render hundreds of target handles.
    mockGetSetSlots.mockResolvedValue(largeSlots(400));
    mockGetPool.mockResolvedValue({ sources: [], tracks: largePoolTracks(400) });

    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('curve-canvas')).toBeInTheDocument());

    expect(screen.getByTestId('curve-lod')).toHaveTextContent('overview');
    expect(document.querySelectorAll('[data-testid^="target-handle-"]').length).toBe(0);
    expect(screen.getByTestId('curve-line')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('curve-zoom-in'));
    fireEvent.click(screen.getByTestId('curve-zoom-in'));
    fireEvent.click(screen.getByTestId('curve-zoom-in'));

    await waitFor(() =>
      expect(screen.getByTestId('curve-canvas').getAttribute('data-px-per-second')).not.toBe('0.0200'),
    );
  });
```

- [ ] **Step 2: Run focused large-set tests**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/BuilderWorkspace.test.tsx -t "hundreds|large"
```

Expected: PASS.

- [ ] **Step 3: Run setbuilder frontend tests**

Run:

```bash
cd dashboard
npm test -- --run app/\(dj\)/setbuilder/__tests__/curveViewport.test.ts \
  app/\(dj\)/setbuilder/__tests__/CurveEditor.test.tsx \
  app/\(dj\)/setbuilder/__tests__/BuilderWorkspace.test.tsx \
  app/\(dj\)/setbuilder/components/__tests__/useMeasuredVirtualList.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Run frontend lint and typecheck**

Run:

```bash
cd dashboard
npm run lint
npx tsc --noEmit
```

Expected: PASS.

- [ ] **Step 5: Run full dashboard Vitest suite**

Run:

```bash
cd dashboard
npm test -- --run
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dashboard/app/\(dj\)/setbuilder/__tests__/BuilderWorkspace.test.tsx
git commit -m "test: cover large setbuilder timelines"
```

---

## Completion Checklist

- [ ] `git status --short` shows only intentional files or is clean.
- [ ] `cd dashboard && npm run lint` passes.
- [ ] `cd dashboard && npx tsc --noEmit` passes.
- [ ] `cd dashboard && npm test -- --run` passes.
- [ ] The curve can zoom in/out/fit from the toolbar.
- [ ] Fit zoom on hundreds of songs renders overview LOD with no target handles.
- [ ] Detail zoom renders handles only for visible slots.
- [ ] The vertical timeline list keeps row interactions while mounting a bounded number of rows.

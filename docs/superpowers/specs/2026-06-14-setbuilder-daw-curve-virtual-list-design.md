# Setbuilder DAW Curve Zoom And Virtual Timeline List Design

Date: 2026-06-14
Branch: `fix/setbuilder-daw-curve-virtual-list`

## Context

The setbuilder curve currently maps the full set duration into the visible curve panel width. In
`CurveEditor`, `slotBlocksFromSlots()` creates one SVG block and one draggable handle per slot,
and each block is clamped to at least one pixel wide. With several hundred songs, the logical time
domain and the forced minimum block widths diverge: blocks, handles, hit targets, seam markers,
and text labels overlap inside a fixed-width SVG. This causes the curve timeline to look stretched
and distorted.

The set list below the curve also renders every row directly. Each row can include badges, pairing
actions, progress state, drag/drop handlers, hover handlers, and transition chips. At several
hundred songs this creates too many DOM nodes and event targets, which can make scrolling and row
interactions unstable.

## Goals

- Add DAW-style horizontal zoom for the curve timeline.
- Stop compressing the full set into one fixed-width SVG at large set sizes.
- Reduce curve DOM/SVG work by rendering only visible time-range detail.
- Keep the set list as an independent vertical list with no zoom behavior.
- Preserve all current set list row functionality.
- Make large sets with hundreds of songs scroll and render predictably.

## Non-Goals

- Do not redesign the set list as a DAW lane.
- Do not add numbered pagination as the primary list experience.
- Do not add Tailwind or a UI framework.
- Do not change backend setbuilder APIs unless implementation uncovers a hard data limitation.
- Do not remove existing row actions, drag/drop insertion, playback controls, or pairing actions.

## Approved Approach

Use a DAW-style curve viewport plus a local virtualized vertical set list.

The curve owns horizontal scale and scroll state. Zoom changes seconds-per-pixel instead of
changing song data. The full set has a logical pixel width derived from total duration and zoom,
while the visible SVG renders the current time range plus small overscan.

The set list remains a vertical list. It switches from rendering every row to rendering only rows
inside the visible scroll window plus overscan. Row behavior stays attached to the row component,
so visible rows keep the same interactions as today.

## Curve Architecture

The curve needs explicit viewport state:

- `pxPerSecond`: horizontal zoom scale.
- `scrollLeft`: horizontal scroll position in pixels.
- `viewportWidth`: measured curve viewport width.
- `visibleStartSec` and `visibleEndSec`: derived from scroll and zoom.
- `fit` action: compute a scale that fits the full set duration in the panel.

`CurvePanel` should own this state because it already coordinates `CurveToolbar` and
`CurveEditor`. `BuilderWorkspace` should continue to own slots, playback position, and list
navigation. Low-level math helpers should remain pure and receive a viewport input rather than
reading DOM state.

The curve editor should render inside a horizontal scroll container. The scrollable inner width is
`max(viewportWidth, totalSec * pxPerSecond)`. The SVG itself can stay viewport-sized and translate
time values into viewport-local x coordinates:

```text
x = (slotTimeSec - visibleStartSec) * pxPerSecond
```

Visible block generation should filter slots by time intersection with the visible range plus
overscan. The current all-slots `slotBlocksFromSlots()` helper can be kept for tests or small
cases, but the new curve rendering path should use viewport-aware geometry.

## Curve Levels Of Detail

Curve zoom should intentionally reduce interactivity when zoomed out:

- Overview zoom: show a simplified target curve, playhead, coarse grid, target-duration marker,
  and broad energy shapes. Hide draggable target handles, dense hit targets, seam chips, tiny
  labels, and per-slot drag actions.
- Medium zoom: show visible slot blocks and readable hover/click targets. Keep target handles
  hidden until slots have enough horizontal space.
- Detail zoom: show draggable target handles, mismatch overlays, seam details, pairing markers,
  and existing slot-level interactions.

LOD thresholds should be based on rendered pixels per slot or pixels per second, not on the raw
number of songs alone. This keeps behavior consistent across short and long tracks.

Default thresholds:

- Overview: median visible slot width is below 6 px.
- Medium: median visible slot width is at least 6 px but below 28 px.
- Detail: median visible slot width is at least 28 px.

At fit/overview zoom, clicks should prefer scrub or coarse navigation. Slot-level editing should
only appear once targets are large enough to avoid accidental tiny clicks.

## Set List Architecture

`TimelinePanel` should be split into a lightweight virtualizer and a row component:

- The scroll container owns `scrollTop` and measured viewport height.
- Virtual items should represent current slot groups, not only bare rows, because each slot can
  include a transition band above it.
- Use a measured-height virtualizer with a conservative default estimate. Cache each mounted slot
  group's measured height, and use prefix-sum offsets to compute spacer heights and scroll targets.
- The renderer computes `startIdx` and `endIdx` from scroll position, cached/estimated item
  offsets, viewport height, and overscan.
- Top and bottom spacer elements preserve total scroll height.
- Only visible rows and nearby overscan rows are mounted.

Current row behavior should move into a reusable row component:

- hover sync with the curve
- double-click to jump/play
- pool-track drag/drop insertion
- pairing context menu/action
- current row progress and VU/pause state
- target, BPM, key, duration, energy, and pairing badges

The list should keep a list-level drop target for appending. For large virtualized lists, insertion
around the visible window should use pointer-position-to-index calculation in the scroll container,
with visible row drop targets still handling direct row drops.

Curve-to-list navigation must use virtualizer offsets instead of DOM refs for every row. When the
curve requests row `idx`, the virtual list should scroll to that index using the measured offset
cache, falling back to estimated offsets for rows not yet measured.

## Playback And Scroll Behavior

The playhead should remain visible on the curve while playback advances unless the user has
manually scrolled away from the playhead. A simple follow mode can be implicit:

- If the playhead is visible or the user has not manually scrolled recently, keep it in view.
- If the user scrolls horizontally away, stop auto-follow until the user presses a follow/fit action
  or playback jumps back into view.

The vertical set list should not auto-zoom or change density. Current-track visibility should be
handled by virtualized index scrolling when playback jumps or when the user chooses a curve/list
navigation action.

## Testing Plan

Unit and component tests should pin the large-set regression:

- Render hundreds of slots and assert the curve renders a bounded visible subset in detail mode.
- Assert overview zoom hides target handles and dense slot hit targets.
- Assert detail zoom restores handles for visible slots.
- Assert fit/full-set mode does not render one handle per song for hundreds of songs.
- Assert virtualized `TimelinePanel` renders a bounded number of rows with spacer height matching
  the full set length.
- Assert visible timeline rows keep double-click, hover, pairing action, current-track state, and
  drag/drop insertion behavior.
- Assert curve-click-to-list navigation scrolls the virtualized list to the requested row.

For the bug-fix regression tests, include the eventual fix commit SHA in the test comment as
required by project testing notes.

## Implementation Notes

- Create the implementation branch before editing code.
- Keep frontend styling in vanilla CSS modules or inline React styles.
- Avoid adding a virtualization dependency. The required behavior is narrow enough for a local
  measured virtualizer.
- Prefer pure helpers for viewport/time math so behavior is easy to test without a browser.
- Preserve existing test IDs where practical for visible rows and existing curve elements. Tests
  that assumed every row or every handle is always mounted will need updates to reflect
  virtualization and LOD behavior.

## Risks

- Drag/drop into virtualized gaps can be awkward if insertion index math is not explicit.
- SVG interactions may need careful event handling because overview mode and detail mode expose
  different hit targets.
- Current tests may rely on all rows existing in the DOM; those expectations must be updated to
  visible-window semantics.
- Follow-playhead behavior can fight user scrolling if the manual-scroll escape hatch is unclear.
  Use implicit follow mode initially: auto-follow only while the playhead remains visible or until
  the user manually scrolls away.

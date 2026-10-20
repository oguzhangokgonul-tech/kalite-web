# Original Landing Scroll Fix - 2026-10-19

## Scope and User Decision

The initial light redesign was rejected. It has been removed, including the
generated dashboard screenshot. The original dark template and stylesheet from
HEAD are the baseline. No new UI, workflow tabs, backend, database or tenant
changes are included. Production is unchanged.

## Changes on the Original Design

- Preserved the original hero, typography, colors, glass cards, sample panels,
  reference strip, footer and scroll-driven story.
- Fixed the body overflow rule that prevented sticky elements attaching to the
  viewport. Header compact mode no longer scales/translates the text.
- Positioned the shared desktop scene below the header, with content-sized grid
  tracks instead of absolute panels extending outside a fixed-height container.
- Matched each desktop story step's minimum height to its scene. Kept floating
  labels outside panel content, including their animation travel. Per the user's
  2026-10-20 correction, short desktop viewports KEEP the left-copy/right-sticky-
  panel layout. Only internal panel spacing is compacted at heights up to 850px.
- Replaced callback-local scene selection with deterministic nearest-step
  selection across cached step positions. Both scroll directions use the same rule.
- Scroll and pointer events share one pending requestAnimationFrame. Geometry is
  refreshed on resize/content changes, not every scroll frame. Wheel and touch
  scrolling remain native, with no fixed-rate interpolation or forced snapping.
- Moved each original scene after its matching description on narrow
  screens; resizing back restores the shared desktop visual without duplication.
- Replaced animated margin and border-color with composited movement. Floating
  chips no longer use moving backdrop filters. Inactive/offscreen scenes and
  hidden documents pause decorative animation. Reduced-motion disables it.
- Added header-aware anchors, initial/deep-link correction and history support.
  The footer is the final section: scroll naturally clamps at the document end.
  The top anchor belongs to the page root, keeping the mobile navigation visible.
- Repaired Demo and Modules destinations without adding a new section. Demo uses
  the existing contact email; synthetic panels/reference placeholders are labelled
  as examples rather than live records/verified customers.
- Retained readable content when JavaScript is unavailable.

## Verification

- Planner and independent UX/QA reviews used the original HEAD design.
- `tests/test_landing_dynamic.py`: 8 passed (59.08s on 2026-10-20), covering anchors, preview labels,
  assets, original layout hooks, no-JavaScript content, session-aware links and
  absence of private user/company display names.
- `tests/ui/landing_dynamic.mjs`: six widths (320, 390, 768, 1024, 1440, 1920),
  all five scenes forward/backward, sticky bounds, inline ordering, footer
  overlap, resize round trip, no JavaScript, reduced motion and history. Passed
  on 2026-10-20 after all changes, including root top-anchor navigation and the
  earlier 1440x768 inline fallback. That height fallback was subsequently rejected
  and replaced by the side-by-side correction below. No horizontal overflow, broken images or missing
  anchor destinations at the six tested widths.
- Browser outputs: `.tmp-ui-audit/landing-original-scroll/` (local only).
- Independent final static QA on 2026-10-20 found no blocking scroll regression
  in root-anchor handling or the synchronized short-viewport threshold. An earlier
  review attempt was interrupted by the service limit; the follow-up completed.
- Residual accessibility gap: marquee focus-within pause has no keyboard focus
  target. Reduced-motion still disables animation. Hero-chip clearance was checked
  visually, not covered by the automated story-chip bounds assertion.
- The full application suite is not required for this scoped presentation-only
  change; no broad regression or physical-device guarantee is claimed.

```powershell
$env:PLAYWRIGHT_MODULE_PATH = (Resolve-Path '.tmp-playwright/node_modules/playwright').Path
$env:UI_BASE_URL = 'http://127.0.0.1:5132'
# Software rendering is available if headless GPU screenshot capture fails:
$env:UI_DISABLE_GPU = '1'
node tests/ui/landing_dynamic.mjs
.\venv\Scripts\python.exe -m pytest tests/test_landing_dynamic.py -q
```

## Performance and Release Limits

- High-refresh rendering is the target, not a verified 144 FPS promise. Headless
  synthetic frame intervals are recorded separately from layout counts; they are
  not evidence of hardware-accelerated performance on a physical 144 Hz display.
- Real 144 Hz verification needs the target device, acceleration enabled, browser
  performance recording and normal foreground operation.
- Earlier software-rendered browser runs recorded zero trigger geometry reads
  and zero layout passes during synthetic scrolling. Slow headless frame times
  do not substantiate a high-FPS claim; physical-device verification remains open.
- The mailto link opens an email client. Mailbox existence/delivery is not tested.
- Preview: `http://127.0.0.1:5132/landing-dynamic-preview#top`.
- No commit, push or deployment was performed. Publication requires approval.

## Side-by-Side Correction - 2026-10-20

- Removed the height-based inline layout condition in both CSS and JavaScript.
  Widths above 1100px keep the visual next to the text regardless of height.
- Preserved the original panel artwork and scroll selection algorithm; reduced
  panel whitespace for short laptops instead of moving panels below descriptions.
- Extended the browser suite to 1440x768, 1366x768, 1280x720 and 1101x720, checking
  panel/text horizontal position, both scroll directions, badge viewport clearance,
  height-only resize and mobile-to-desktop restoration.
- Updated asset versions to avoid stale CSS/JavaScript layout combinations.
- At desktop heights up to 650px, an oversized visual remains beside the text
  and scrolls internally; the panel is not reparented under the description.
- Focused server tests after this correction: 8 passed (219.61s).
- A browser attempt timed out while capturing a full-page screenshot. The rerun
  uses viewport screenshots, retaining all layout and scroll assertions.
- Final rerun passed all ten viewport configurations, all five desktop scenes in
  both directions, mobile ordering, resize restoration, no-JavaScript and reduced-
  motion checks. The 1366x600 internal-scroll test confirmed the panel footer is
  reachable and the visual remains beside the text inside the viewport.
- Independent planning/UX and final static QA reviews completed; no unresolved
  blocking findings for the side-by-side correction. Physical high-refresh-device
  performance remains unverified.
- No deployment performed.

## Subsequent Publication - 2026-10-20

The approved landing and side-by-side corrections were deployed with the
company-code login release at `827a3b0`. Anonymous platform-root visitors now
see this landing. See `COMPANY_LOGIN_RELEASE_2026-10-20.md` for backup, restore,
service and live-browser evidence.

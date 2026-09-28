# Design spec: visual redesign ("Ink, Paper and One Blue")

Scope: `src/styles.css` (almost everything), plus 3 inline colour literals in TSX (section 9). Light theme only. There is no new DOM, no new class names in TSX, and no text or ARIA changes.

---

## 1. Aesthetic direction

**Editorial ink on archival paper, with one Ambedkar blue.** The archive should read like a well-set printed record, not an app dashboard. Surfaces are a warm, unbleached paper (`#f6f3ec`), with white "sheets" for content and near-black ink for text. Headlines are big, heavy Noto Serif, set tight. One saturated blue (`#1a3fb8`, the blue of the Ambedkarite movement) carries every action, every current state, and a signature element: **the Blue Rule**, a short, thick blue bar that sits above every page title and marks the kiosk's active destination. Brass is kept only as a functional "archival stamp" for citations and verified quotes. Structure comes from hairline rules and heavy ink rules, not shadows or gradients. Corners are nearly square (4px) and chips look like catalogue tags. Nothing is dark-mode: the rail, signage, attract screen and dialogs all become light. The result should feel calm, dignified and unmistakably civic, and the bold part comes from type and one colour.

Rules that make it hold together:
- Blue (`--indigo`) is used only for interactive or current things: buttons, links, the active nav, selected tabs, pager current, the Blue Rule and timeline spine. It is never used for decorative fills, with one exception, the story cards.
- Brass (`--brass*`) is used only for citation and verification: `.cite`, `.cite-link`, `.chip.verified`, `.sources .n`, `.passage.target`, `.badge`.
- No letter-spacing, `text-transform: uppercase` or italics anywhere. Letter-spacing breaks the Devanagari headstroke (shirorekha), and Devanagari has no true italic. The only exception is the numeric drawer tab.

---

## 2. Tokens: replace the `:root` block wholesale

> The unit test `src/a11y.test.tsx` ("design token contrast") parses the **first** `:root {` block and the `:root[data-contrast="high"] {` block with `/--([\w-]+):\s*(#[0-9a-f]{6})/`. So:
> - write every colour token as **6-digit lowercase hex** (no `#fff`, no `rgb()`),
> - keep every existing token name (`--indigo`, `--brass`, and so on; the names are now historical, and `--indigo` means "accent blue"),
> - keep each block free of nested braces, and close it with `}` on its own line.
>
> The e2e test also requires the body background to change under high contrast, so `--paper` must not be `#ffffff` in the default theme.

```css
:root {
  --scale: 1;
  /* Accent: "Ambedkar blue". Name kept for tests. */
  --indigo: #1a3fb8;
  --indigo-deep: #10266f;
  --indigo-soft: #e3e8f8;
  /* Surfaces */
  --paper: #f6f3ec;
  --sheet: #ffffff;
  --sheet-2: #fbf9f4;
  --scan-bg: #dcd6c8;
  /* Ink */
  --ink: #16171d;
  --ink-2: #4b4f5c;
  --rule: #dcd6c8;
  --rule-strong: #b8b0a0;
  /* Archival stamp: citations and verification only */
  --brass: #c9a24a;
  --brass-ink: #6b5214;
  --brass-wash: #f7efd9;
  /* Status */
  --danger: #a61b1b;
  --danger-deep: #7f1414;
  --danger-wash: #fbeceb;
  --ok: #1d6b43;
  /* Focus: ink ring (outline) + gold band (box-shadow) in the offset gap. */
  --focus: #f0b400;
  --focus-ring: #0b0c10;
  /* Boundary of text fields, selects, chip-links: >= 3:1 on sheet and paper (WCAG 1.4.11). */
  --field: #6b6f7c;
  /* Shape */
  --radius: 4px;
  --radius-lg: 8px;
  --radius-pill: 999px;
  --rail: 132px;
  /* Elevation (used sparingly; structure comes from rules) */
  --shadow-1: 0 1px 2px rgba(22, 23, 29, 0.06);
  --shadow-2: 0 10px 28px -10px rgba(22, 23, 29, 0.22);
  --shadow-dialog: 0 24px 64px -12px rgba(22, 23, 29, 0.35);
  /* Spacing (4px base) */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --space-7: 48px;
  --space-8: 64px;
  --space-9: 96px;
  /* Motion */
  --ease: cubic-bezier(0.2, 0, 0, 1);
  --dur: 160ms;
  /* Type */
  --ui: "Mukta", "Noto Sans Devanagari", system-ui, sans-serif;
  --read: "Noto Serif", "Noto Serif Devanagari", Georgia, serif;
  --mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
  --step--1: calc(0.9375rem * var(--scale));
  --step-0: calc(1.125rem * var(--scale));
  --step-1: calc(1.375rem * var(--scale));
  --step-2: calc(1.75rem * var(--scale));
  --step-3: calc(2.375rem * var(--scale));
  --step-4: calc(3.25rem * var(--scale));
  --step-5: calc(4rem * var(--scale));
  color-scheme: light;
}
```

Type scale in px at `--scale: 1`: 15 / 18 / 22 / 28 / 38 / 52 / 64. `--scale` still multiplies every step.

### Contrast (WCAG relative luminance, computed)

| Pair | Ratio | Need |
|---|---|---|
| ink on paper / sheet | 16.1 / 17.9 | 4.5 |
| ink-2 on paper / sheet / indigo-soft | 7.37 / 8.17 / 6.67 | 4.5 |
| indigo on paper / sheet / indigo-soft | 7.74 / 8.58 / 7.01 | 4.5 |
| #ffffff on indigo / indigo-deep | 8.58 / 13.7 | 4.5 |
| #dfe4f3 on indigo / indigo-deep | 6.75 / 10.8 | 4.5 |
| #a9b3d6 on indigo-deep (tested literal) | 6.61 | 4.5 |
| brass-ink on brass-wash / sheet / paper | 6.44 / 7.39 / 6.67 | 4.5 |
| ink on brass | 7.45 | 4.5 |
| brass on indigo-deep | 5.72 | 4.5 |
| danger on sheet / danger-wash; #ffffff on danger | 7.52 / 6.55 / 7.52 | 4.5 |
| ok on sheet | 6.49 | 4.5 |
| focus-ring on paper / sheet | 17.6 / 19.6 | 3 |
| focus on indigo / indigo-deep | 4.59 / 7.35 | 3 |
| field on sheet / paper | 5.01 / 4.52 | 3 |

`--rule` and `--rule-strong` are decorative hairlines only. They never form the sole boundary of a control.

### High-contrast block: replace wholesale

```css
:root[data-contrast="high"] {
  --indigo: #0a1f7a;
  --indigo-deep: #000000;
  --indigo-soft: #ffffff;
  --paper: #ffffff;
  --sheet: #ffffff;
  --sheet-2: #ffffff;
  --scan-bg: #ffffff;
  --ink: #000000;
  --ink-2: #000000;
  --rule: #000000;
  --rule-strong: #000000;
  --field: #000000;
  --brass: #ffd24a;
  --brass-ink: #000000;
  --brass-wash: #fff4c2;
  --danger: #8a0000;
  --danger-deep: #5c0000;
  --danger-wash: #ffffff;
  --ok: #00542a;
  --focus: #f0b400;
  --focus-ring: #000000;
}
```

HC ratios: #ffffff on indigo 14.1; focus on indigo 7.5; danger on sheet 10.1; ok on sheet 9.1; everything else is black on white (21) or black on #ffd24a / #fff4c2 (above 14).

---

## 3. Fonts

Replace lines 1 to 11. All weights below exist in `node_modules/@fontsource/*` v5.3.0 (verified). `vite.config.ts` precaches `**/*.woff2`, so the new files are cached offline automatically. There are no network fonts.

```css
@import "@fontsource/mukta/latin-400.css";
@import "@fontsource/mukta/latin-500.css";
@import "@fontsource/mukta/latin-600.css";
@import "@fontsource/mukta/latin-700.css";
@import "@fontsource/mukta/devanagari-400.css";
@import "@fontsource/mukta/devanagari-500.css";
@import "@fontsource/mukta/devanagari-600.css";
@import "@fontsource/mukta/devanagari-700.css";
@import "@fontsource/noto-serif/latin-400.css";
@import "@fontsource/noto-serif/latin-600.css";
@import "@fontsource/noto-serif/latin-700.css";
@import "@fontsource/noto-serif-devanagari/devanagari-400.css";
@import "@fontsource/noto-serif-devanagari/devanagari-600.css";
@import "@fontsource/noto-serif-devanagari/devanagari-700.css";
```

Usage:
- **Display and headings**: `--read` at 700 (h1, h2, drawer titles, signage) and 600 (h3, story cards).
- **Reading text** (`.passage`, `.sentence`, blockquotes, captions): `--read` at 400.
- **UI**: `--ui` Mukta 400 for body, 500 for labels and nav, 600 for buttons, 700 for the badge and the selected tab.
- **Devanagari line-height**. Add this after the heading rules:
  ```css
  :lang(hi), :lang(mr) { line-height: 1.7; }
  :is(h1, h2, h3):lang(hi), :is(h1, h2, h3):lang(mr) { line-height: 1.35; }
  .passage:lang(hi), .passage:lang(mr), .sentence:lang(hi), .sentence:lang(mr) { line-height: 1.95; }
  ```
  Latin defaults: body 1.6, h1 1.1, h2 and h3 1.2, passage and sentence 1.8.
- `code, pre { font-family: var(--mono); font-size: 0.9em; }` uses system fonts only.

---

## 4. Global and shared elements

### Base
- `body`: background `--paper`, colour `--ink`, font `var(--step-0)/1.6 var(--ui)`.
- `h1, h2, h3`: `--read`, colour `--ink`, `text-wrap: balance`, margin `0 0 0.5em`. h1 is `--step-3` at 700 with line-height 1.1. h2 is `--step-2` at 700 with line-height 1.2. h3 is `--step-1` at 600 with line-height 1.2.
- **The Blue Rule** (signature):
  ```css
  .page h1::before, .phone h1::before {
    content: ""; display: block; width: 56px; height: 6px;
    margin-bottom: var(--space-4); background: var(--indigo); border-radius: 1px;
  }
  .staff .page h1::before { content: none; }
  ```
- Page deck: `.page > h1 + p.muted { font-size: var(--step-1); line-height: 1.45; color: var(--ink-2); margin-bottom: var(--space-6); }`.
- `a`: colour `--indigo`, `text-decoration-thickness: 1px`, `text-underline-offset: 0.2em`. On hover: colour `--indigo-deep`, thickness 2px.
- `::placeholder { color: var(--ink-2); opacity: 1; }`
- `input[type=checkbox], input[type=radio] { accent-color: var(--indigo); }`

### Focus ring (all interactive elements)
```css
:focus-visible {
  outline: 3px solid var(--focus-ring);
  outline-offset: 3px;
  box-shadow: 0 0 0 3px var(--focus);   /* gold band fills the offset gap */
}
.main:focus, .main:focus-visible,
.staff main:focus, .staff main:focus-visible { outline: none; box-shadow: none; }
.sources li:focus { outline: 3px solid var(--focus-ring); outline-offset: 3px; box-shadow: 0 0 0 3px var(--focus); }
```
- **Delete** the rule `.rail, .attract, .signage, .scan-pane, dialog.idle-warning { --focus-ring: var(--focus); }`. Every surface is light now, so one ring works everywhere. Keep the `--focus` token because the test checks it.
- Components must not set `box-shadow` inside their own `:focus-visible` states, because that would erase the gold band. The drawer's `:focus-visible` gets only border and transform changes, as below.
- `input:focus-visible, select:focus-visible, textarea:focus-visible { border-color: var(--indigo); }` stays, and the global ring still applies.

### Buttons (`.btn`)
| Variant | Default | Hover | Active | Disabled |
|---|---|---|---|---|
| `.btn` | bg `--indigo`, border 2px `--indigo`, colour `#ffffff` | bg and border `--indigo-deep` | `transform: translateY(1px)` | `opacity: .5; cursor: not-allowed` with no hover change |
| `.secondary` | bg `--sheet`, colour `--indigo`, border 2px `--indigo` | bg `--indigo-soft` | same | same |
| `.quiet` | transparent, colour `--indigo`, border transparent, `text-decoration: underline 1px`, offset 0.2em | bg `--indigo-soft`, no underline | same | same |
| `.danger` | bg and border `--danger`, colour `#ffffff` | bg and border `--danger-deep` | same | same |
| `.small` | min-height 48px, font `--step--1`, padding `0 0.9em` | | | |

Shared declarations: `min-height: 48px; min-width: 48px; padding: 0 1.25em; border-radius: var(--radius); font: 600 var(--step-0)/1 var(--ui); gap: 0.5em; transition: background-color var(--dur) var(--ease), border-color var(--dur) var(--ease), color var(--dur) var(--ease), transform var(--dur) var(--ease);`. Use `.btn:disabled:hover` to cancel hover colours.

### Inputs, selects and textareas
- `min-height: 52px; padding: 0.5em 0.85em; border: 2px solid var(--field); border-radius: var(--radius); background: var(--sheet); color: var(--ink);`. On hover (when not focused): border-colour `--ink-2`.
- `select`: `appearance: none; padding-right: 44px; background: var(--sheet) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1.5l5 5 5-5' fill='none' stroke='%2316171d' stroke-width='2'/%3E%3C/svg%3E") no-repeat right 16px center;`. The CSP allows `data:` images.
- `label`: weight 500, colour `--ink`. Labels in the filter and form grids are `--step--1` with a 6px gap.

### Chips
- `.chip` (catalogue tag, not interactive): `min-height: 28px; padding: 2px 10px; border-radius: 3px; border: 1px solid var(--rule-strong); background: var(--paper); color: var(--ink-2); font: 500 var(--step--1)/1.3 var(--ui);`.
- `.chip.verified`: bg `--brass-wash`, border `--brass`, colour `--brass-ink`, weight 600, plus a decorative dot: `.chip.verified::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--brass-ink); }`.
- `.chip.ai`: bg `--indigo-soft`, border `--indigo`, colour `--indigo`, weight 600.
- `.chip.mt`: bg `--sheet`, border `--danger`, colour `--danger`, weight 600.
- `.chip.fixture`: `border-style: dashed`.
- `.chip-link` (interactive, touch): `min-height: 48px; min-width: 48px; padding: 4px 18px; border-radius: var(--radius-pill); border: 1px solid var(--field); background: var(--sheet); color: var(--indigo); font: 500 var(--step--1) var(--ui);`. On hover: bg `--indigo-soft`, border `--indigo`. When `[aria-pressed=true]`: bg `--indigo`, border `--indigo`, colour `#ffffff`, weight 600.

### Citations (brass stamp)
- `.cite`: `display: block; padding: 10px 14px; border-left: 4px solid var(--brass); border-radius: 0 var(--radius) var(--radius) 0; background: var(--brass-wash); color: var(--brass-ink); font: 500 var(--step--1)/1.5 var(--ui);`.
- `.cite-link` keeps its 48 by 48px box. The inner `> span`: `min-width: 28px; padding: 2px 7px; border-radius: 3px; background: var(--brass-wash); border: 1px solid var(--brass-ink); color: var(--brass-ink); font: 700 calc(0.85rem * var(--scale))/1.4 var(--ui);`. On hover or focus-visible of the link, the span gets bg `--brass` and colour `--ink`.

### Cards and sheets
- `.sheet`: `background: var(--sheet); border: 1px solid var(--rule); border-radius: var(--radius); padding: 28px 32px;`. No shadow.
- `.result`: the same surface, `padding: 24px 28px; gap: 10px 24px`, with `transition: border-color var(--dur) var(--ease)`. On hover: border `--rule-strong`. On `:focus-within`: border `--indigo`.
- `.result h2 a, .result h3 a`: colour `--indigo`, `font-family: var(--read); font-weight: 700; text-decoration: none`. On hover: underline 2px.
- `.result blockquote`: serif 400 at `--step-0` with line-height 1.7, colour `--ink`, `padding-left: 16px; border-left: 3px solid var(--rule)`. The 4-line clamp stays.
- `.result .thumb`: radius `--radius`, border 1px `--rule`.
- `.results`: gap 16px.
- `.meta`: colour `--ink-2`, `--step--1`, gap `6px 14px`, with separator dots: `.meta > span + span::before { content: ""; display: inline-block; width: 4px; height: 4px; margin-right: 14px; border-radius: 50%; background: var(--ink-2); vertical-align: middle; }`.
- `dl.facts`: `gap: 8px 24px`. `dt` is colour `--ink-2` at weight 500. `dd` is colour `--ink`.

### Status, empty, error and loading states
- `.notice`: `padding: 14px 18px; border-left: 4px solid var(--indigo); border-radius: 0 var(--radius) var(--radius) 0; background: var(--indigo-soft); color: var(--ink); margin: 16px 0;`.
- `.notice.bad`: border-left `--danger`, bg `--danger-wash`, colour `--danger`. This replaces the literal `#fbe9e9`. The retry `.btn.secondary.small` inside it keeps its 48px height.
- `.banner` (full-width strip at the top of `<main>`): `padding: 12px var(--space-7); border-left: 6px solid var(--brass); background: var(--brass-wash); color: var(--brass-ink); font: 500 var(--step--1) var(--ui);`. `.offline`: border `--indigo`, bg `--indigo-soft`, colour `--ink`. `.warn`: border `--danger`, bg `--danger-wash`, colour `--danger`.
- `.empty-state`: `padding: 56px 32px; text-align: center; background: var(--sheet); border: 2px dashed var(--rule-strong); border-radius: var(--radius); color: var(--ink-2); font: 400 var(--step-1)/1.5 var(--read);`.
- Loading is text only (`Loading` renders `p.muted[role=status]`). Keep it as text in `--ink-2`, with no spinners or skeletons. Note that the DOM is fixed and it is read by `role=status`.
- `.status.ok` uses colour `--ok`. `.status.bad` uses colour `--danger`. Both are weight 700.

### Dialogs
- `dialog`: `background: var(--sheet); color: var(--ink); border: 0; border-top: 6px solid var(--indigo); border-radius: var(--radius-lg); padding: 32px 36px; max-width: 560px; box-shadow: var(--shadow-dialog);`. The backdrop is `rgba(22, 23, 29, 0.55)`. `.actions` has gap 12px and margin-top 28px.
- `dialog.idle-warning`: **light**. Delete its indigo background, white h2 and white button overrides. It gets `border-top-color: var(--brass)`. `.countdown` is `font: 700 var(--step-4)/1 var(--read); color: var(--indigo); font-variant-numeric: tabular-nums; margin: 8px 0 0`. Its `.btn` stays primary blue with `min-height: 56px`.

### Skip link
`.skip-link`: `background: var(--ink); color: #ffffff; border: 0; font-weight: 600; border-radius: var(--radius);`. It keeps the 48px height and the `top: -80px` to `8px` behaviour.

---

## 5. Surfaces

### 5.1 Shell and nav rail (`Shell.tsx`, `.shell`, `.rail`, `.main`)
The rail becomes **light**:
- `.rail`: `background: var(--sheet); color: var(--ink); border-right: 1px solid var(--rule); padding: 20px 12px; gap: 4px`.
- `.rail .mark`: `color: var(--ink); font: 700 1.05rem/1.15 var(--read); padding: 4px 6px 20px`. It gets its own Blue Rule: `.rail .mark::before { content: ""; display: block; width: 32px; height: 5px; margin-bottom: 10px; background: var(--indigo); }`.
- `.rail a.navlink`: colour `--ink-2`, weight 500, `border-radius: var(--radius)`, and transition. On hover: bg `--indigo-soft`, colour `--indigo`. When `[aria-current="page"]`: bg `--indigo`, colour `#ffffff`, weight 700. Icons stay 26px.
- `.rail .badge`: bg `--brass`, colour `--ink`, radius pill, weight 700, 0.8rem. This is unchanged in principle.
- `.rail .controls`: `border-top: 1px solid var(--rule); padding-top: 16px; gap: 8px`.
- `.rail .langs button, .rail .toggle`: `border: 2px solid var(--field); background: var(--sheet); color: var(--ink); font: 500 0.95rem/1 var(--ui)`. On hover: border `--indigo`, colour `--indigo`. When `[aria-pressed="true"]`: bg `--indigo`, border `--indigo`, colour `#ffffff`.
- `.rail .finish`: `background: var(--ink); color: #ffffff; border: 0; font: 700 1.05rem/1 var(--ui); min-height: 56px`. On hover: bg `#000000`. The black button is the one "leave" action, deliberately different from blue.
- `.main`: unchanged behaviour.
- `.page`: `max-width: 1280px; padding: 40px 48px 96px`.

### 5.2 Home (`Home.tsx`)
- `.hero`: `grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 56px; align-items: end; padding: 32px 0 48px; border-bottom: 3px solid var(--ink)`. The heavy ink rule is the masthead line.
- `.hero h1`: `font-size: var(--step-5); line-height: 1.05; color: var(--ink); max-width: 15ch; margin-bottom: 0.35em`. On `:lang(hi)` or `:lang(mr)` the line-height is 1.25. It gets the Blue Rule automatically through `.page h1::before`; make that rule 80 by 8px here with `.hero h1::before { width: 80px; height: 8px; }`.
- `.hero .lead`: `--step-1`, colour `--ink-2`, max-width 38ch, line-height 1.45.
- `.bigsearch`: gap 12px. The input is `min-height: 64px; font-size: var(--step-1); border-color: var(--ink)`, which is a bolder field for the primary action. Buttons are `min-height: 60px`. The first is primary and the second is secondary; that is already the markup.
- `.drawers` (card catalogue): `grid-template-columns: repeat(3, 1fr); gap: 56px 24px; margin: 72px 0 56px`.
- `.drawer`: `min-height: 168px; padding: 28px 24px 22px; background: var(--sheet); border: 1px solid var(--rule-strong); border-radius: 0 var(--radius) var(--radius) var(--radius); transition: transform var(--dur) var(--ease), border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease)`.
- `.drawer::before` (numbered tab): `top: -32px; height: 32px; padding: 0 16px; background: var(--sheet); border: 1px solid var(--rule-strong); border-bottom: 0; font: 700 0.9rem/1 var(--read); color: var(--indigo); letter-spacing: 0.04em` (digits only). The `--tab-offset` mechanism is kept.
- `.drawer:hover` gets `transform: translateY(-3px); border-color: var(--indigo); box-shadow: var(--shadow-2)`. `.drawer:focus-visible` gets `transform: translateY(-3px); border-color: var(--indigo)` and no box-shadow, so the focus band is kept. On both hover and focus-visible, `::before` gets `background: var(--indigo); color: #ffffff; border-color: var(--indigo)`.
- `.drawer h3`: `font: 700 var(--step-2)/1.15 var(--read); color: var(--ink)`. `.count`: colour `--ink-2`, `--step--1`, weight 500.
- `.drawer.empty` and `.drawer.empty::before`: `border-style: dashed`. No fading.
- `#stories-h`: normal h2 with `margin-top: 16px`.
- `.story-strip`: `grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px`.
- `.story-card` (the one solid-blue block): `min-height: 148px; padding: 24px; background: var(--indigo); color: #ffffff; border-radius: var(--radius); font: 600 var(--step-1)/1.25 var(--read); transition: background-color var(--dur) var(--ease)`. On hover: bg `--indigo-deep`. `span`: `font: 500 var(--step--1) var(--ui); color: #dfe4f3; border-top: 1px solid rgba(255, 255, 255, 0.3); padding-top: 10px; margin-top: 16px`.

### 5.3 Search results and filters (`Search.tsx`)
- `h1`: standard page title with the Blue Rule.
- `.searchbar`: `grid-template-columns: 1fr auto; gap: 12px; margin-bottom: 20px`. The input is 56px tall, and the button is `min-height: 56px; min-width: 144px`.
- `.filters`: the fieldset has inline `border: 0; padding: 0`, which beats the stylesheet, so do not box it or pad it. Set only `grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 16px 20px; margin-bottom: 24px`. The separator goes on whatever follows it: `.filters + p[role=status], .filters + .results { border-top: 3px solid var(--ink); padding-top: 16px; }`.
- `.filters label`: `--step--1`, weight 600, colour `--ink`, gap 6px. The "clear filters" `.btn.secondary` keeps `align-self: end` inline.
- The result count `p[role=status].muted` is `--step--1` at weight 600.
- `.result` cards are as in section 4. The chips column is right-aligned (inline). The `.row` of actions has `margin-top: 4px`.
- Photo cards: `.thumb` is 128 by 96, and `.card-caption` is serif `--step-0`.
- `.empty-state` for "collection empty". "No results" is the muted status line.

### 5.4 Item reader (`Item.tsx`, `ScanViewer.tsx`)
- `.reader-head`: `padding-bottom: 24px; margin-bottom: 32px; border-bottom: 3px solid var(--ink); gap: 32px`. The h1 is `--step-3`. `.meta` is below it.
- The summary `.sheet` keeps its inline `marginBottom: 20`.
- `.pager-step`: `gap: 16px`. `.step-btn` is `min-height: 56px; min-width: 56px; font-weight: 700` and secondary. `.pager` has gap 8px, and `.pager .btn[aria-current="true"]` is `background: var(--indigo); color: #ffffff; border-color: var(--indigo)`.
- `.reader`: **keep two equal columns** (e2e asserts that the scan is left of the text on the same row), with `gap: 32px`.
- `.scan-pane`: `position: sticky; top: 16px; background: var(--scan-bg); border: 1px solid var(--rule-strong); border-radius: var(--radius); overflow: hidden`. This is a light "lightbox" and replaces `#2a2f3d`.
- `.scan-pane .osd`: `height: min(72vh, 860px)`, unchanged.
- `.osd-tools`: `top: 12px; right: 12px; gap: 8px`. Each button is `min-width: 48px; min-height: 48px; border: 2px solid var(--ink); border-radius: var(--radius); background: var(--sheet); color: var(--ink); box-shadow: var(--shadow-1); font: 700 1.4rem/1 var(--ui)`. On hover: bg `--indigo-soft`, colour `--indigo`, border `--indigo`.
- `.scan-pane .caption`: `background: var(--sheet); color: var(--ink-2); border-top: 1px solid var(--rule-strong); padding: 10px 14px; font: 500 var(--step--1) var(--ui)`. This replaces `#1d212c` / `#dfe4f3`.
- `.text-pane`: gap 16px. The `.sheet` inside has `padding: 28px 32px`.
- `.tabs`: `border-bottom: 2px solid var(--rule); gap: 4px; margin-bottom: 20px`. The buttons are `min-height: 48px; padding: 0 18px; border-bottom: 4px solid transparent; color: var(--ink-2); font: 500 var(--step-0) var(--ui)`. On hover: colour `--indigo`. When `[aria-selected="true"]`: colour `--ink`, `border-bottom-color: var(--indigo)`, weight 700.
- `.passage`: `font: 400 calc(1.1875rem * var(--scale))/1.8 var(--read); max-width: 68ch; color: var(--ink)`.
- `.passage.target`: `background: var(--brass-wash); box-shadow: 0 0 0 10px var(--brass-wash); outline: 2px solid var(--brass-ink); outline-offset: 10px; border-radius: 2px`. The class name is unchanged and is used by e2e.
- `.segments`: gap 6px. `.segment` has `padding: 12px; border-radius: var(--radius); border: 1px solid transparent`. `.segment.active` has `background: var(--indigo-soft); border-color: var(--indigo)`. `.segment button.time` has `border: 1px solid var(--field); color: var(--indigo); font: 600 var(--step--1) var(--ui); font-variant-numeric: tabular-nums`, and on hover bg `--indigo-soft`.
- The provenance and related `.sheet` / `.results` are as in section 4.
- **Scan highlight overlay** (inline style in `ScanViewer.tsx:45`): change it to `border:3px solid #1a3fb8;background:rgba(26,63,184,.12);pointer-events:none`. The old brass border was about 1.8:1 on cream scans and failed 1.4.11.

### 5.5 Ask (`Ask.tsx`, `VoiceQuestion.tsx`)
- The page keeps its inline `max-width: 1000px`.
- `.ask-form`: `grid-template-columns: 1fr auto; gap: 12px; align-items: stretch`. The textarea is `min-height: 104px; font-size: var(--step-1); border-color: var(--ink); resize: vertical`. The submit `.btn` is `min-width: 144px`.
- `.voice-question`: `margin-top: 12px`. `.voice-note` is `--step--1` in colour `--ink-2`. `.voice-clock` keeps the red `--danger` dot and is weight 600.
- `.answer`: `margin-top: 32px; padding-top: 24px; border-top: 3px solid var(--ink)`. The question h2 (inline `--step-1`) is serif 700.
- `.answer .label-row`: gap 8px, margin-bottom 16px.
- `.answer .sentence`: `font: 400 calc(1.1875rem * var(--scale))/1.8 var(--read); max-width: 68ch`.
- `.sources`: `gap: 12px; margin-top: 16px`. `li` is a sheet card with `padding: 20px 24px`.
- `.sources .n`: `display: inline-flex; align-items: center; justify-content: center; min-width: 32px; height: 32px; border-radius: 3px; background: var(--brass-wash); border: 1px solid var(--brass-ink); color: var(--brass-ink); font: 700 var(--step--1) var(--ui); margin-right: 4px`.
- `.sources blockquote`: `margin: 12px 0; padding-left: 16px; border-left: 3px solid var(--rule); font-family: var(--read)`.
- `.suggestions`: gap 8px, margin-top 16px (these are chip-links).
- The busy status `p[role=status]` shows text only.

### 5.6 Constitution (`Constitution.tsx`)
- The list uses the `Page` title and deck, then `.notice`, then `.results`. The article link in each card (h2 a) uses `--read` 700. The article title `p` (inline serif) is `--step-0` in colour `--ink`. The `.chip` debates count is right-aligned.
- Article page: the back link `.link-target` is weight 600 with the underline. The h1's inner span (inline `--step-1`, weight 400) inherits colour `--ink-2` via `.page h1 > span { color: var(--ink-2); }`.
- Entry cards are as in section 4. The "open original" link is a primary `.btn`.

### 5.7 Explore: timeline, stories, story, map, list (`Explore.tsx`)
- `.timeline`: `padding-left: 32px; border-left: 3px solid var(--indigo); margin-left: 8px`. `li` is `padding: 0 0 40px 24px`.
- `.timeline li::before`: `left: -43px; top: 8px; width: 20px; height: 20px; background: var(--indigo); border: 4px solid var(--paper); box-shadow: 0 0 0 2px var(--indigo)`. `li.approx::before` is `background: var(--paper); border: 3px dashed var(--indigo); box-shadow: none`.
- `.timeline .date`: `font: 700 var(--step-2)/1.1 var(--read); color: var(--indigo)`.
- Timeline item links are `.btn.secondary.small`.
- Stories page: the `.story-strip` and `.story-card` from section 5.2.
- `.story-block`: `gap: 40px; padding: 40px 0; border-bottom: 1px solid var(--rule)`. The first block gets `border-top: 3px solid var(--ink); margin-top: 24px`. `img` has radius `--radius`, border 1px `--rule`, and bg `#ffffff`.
- `.map-wrap`: sheet card. `.map-edge` uses stroke `--rule-strong` at 1.5. `.map-edge.sel` uses stroke `--indigo` at 3. `.map-node circle` is `stroke: var(--indigo); stroke-width: 2.5; fill: var(--sheet)`. `.sel` gets fill `--indigo`. `.dim circle` stays at opacity .3. `text` is `font: 500 18px var(--ui); fill: var(--ink)`, and `.dim text` uses fill `--ink-2`.
- The map `aside.sheet` uses `position: sticky; top: 16px` at 1001px and up.
- List (basket): the result cards. `.qr-panel` is `grid-template-columns: 280px 1fr; gap: 32px`. `.qr` has bg `#ffffff`, `padding: 16px`, border 1px `--rule-strong`, radius `--radius`.
- `.phone` (shared list on a visitor's phone): `padding: 24px 20px`. `.phone-langs button` uses the rail language-button styling (2px `--field`, and pressed means blue fill).

### 5.8 Signage (`Signage.tsx`, 1920×1080 unattended display)
Light and poster-like:
- `.signage`: `background: var(--paper); color: var(--ink); padding: 5vh 5vw; grid-template-rows: auto 1fr auto; overflow: hidden`.
- `.signage h1`: `font: 700 2.2vw/1.1 var(--read); color: var(--ink); padding-bottom: 2vh; border-bottom: 0.35vh solid var(--ink)`. `.signage h1::before`: `content: ""; display: block; width: 5vw; height: 0.8vh; background: var(--indigo); margin-bottom: 1.6vh`.
- `.signage .slide`: `grid-template-columns: 1fr 1fr; gap: 5vw; align-items: center; animation: slide-in 600ms var(--ease) both`, with `@keyframes slide-in { from { opacity: 0; transform: translateY(1.5vh); } to { opacity: 1; transform: none; } }`. The existing reduced-motion block disables it.
- `.signage .slide .date`: `font: 700 6vw/1 var(--read); color: var(--indigo)`.
- The slide `h2` is ink, serif 700, and keeps the inline `2.6vw` size.
- `.signage .slide p`: `font-size: 1.8vw; line-height: 1.5; color: var(--ink-2); max-width: 40ch`.
- `.signage .slide img`: `max-height: 62vh; max-width: 100%; border-radius: var(--radius); background: #ffffff; border: 1px solid var(--rule-strong); box-shadow: var(--shadow-2)`.
- `.signage footer`: `color: var(--ink-2); font-size: 1.2vw; border-top: 1px solid var(--rule); padding-top: 2vh`.
- **Required inline changes** (otherwise the text is white on paper):
  - `Signage.tsx:63`: remove `color: "#fff"` from the h2 style, and keep `fontSize` and `marginTop`.
  - `Signage.tsx:65`: `color: "#c9a24a"` becomes `color: "var(--brass-ink)"`.

### 5.9 Attract screen (`.attract`, kiosk idle)
- `.attract`: `background: var(--paper); color: var(--ink); border: 0; border-left: 24px solid var(--indigo); padding: 7vw; justify-content: flex-end`.
- `.attract-title`: `font: 700 clamp(2.8rem, 6vw, 5.5rem)/1.06 var(--read); color: var(--ink); max-width: 14ch`. `.attract-title::before`: `content: ""; display: block; width: 96px; height: 8px; background: var(--indigo); margin-bottom: 32px`. Devanagari line-height is 1.25.
- `.attract-lead`: `font: 500 1.75rem/1.3 var(--ui); color: var(--indigo)`.
- `.attract:focus-visible`: `outline: 4px solid var(--focus-ring); outline-offset: -20px; box-shadow: none`. The button fills the viewport, so the ring must sit inside it.

### 5.10 Staff console (`Staff.tsx`)
The staff console is denser: scope tokens down inside `.staff` only.
- `.staff`: `--step-0: calc(1rem * var(--scale)); --step-1: calc(1.25rem * var(--scale)); --step-2: calc(1.5rem * var(--scale)); --step-3: calc(2rem * var(--scale)); font-size: var(--step-0); background: var(--paper); min-height: 100%`.
- `.staff .page`: `max-width: 1440px; padding: 28px 32px 64px`. There is no Blue Rule on h1.
- `.staff-top`: `background: var(--sheet); border-top: 4px solid var(--indigo); border-bottom: 1px solid var(--rule-strong); padding: 8px 24px; gap: 20px`. `strong` is `font: 700 var(--step-1) var(--read); color: var(--ink)`.
- `.staff-top nav a`: `min-height: 48px; padding: 0 14px; border-radius: var(--radius); color: var(--ink-2); font-weight: 500; text-decoration: none`. On hover: bg `--indigo-soft`, colour `--indigo`. When `[aria-current="page"]`: bg `--indigo`, colour `#ffffff`, weight 600.
- `.staff-top .who`: colour `--ink-2`, `--step--1`. The `.staff-lang select` is 48px tall and keeps its 48px target (the test checks `.staff-top`).
- Section `.sheet`: `padding: 24px 28px`. Its h2 (inline `--step-1`) is serif 700.
- `table.grid`: `background: var(--sheet); border: 1px solid var(--rule); font-size: var(--step--1)`. `th` is `background: var(--paper); color: var(--ink); font-weight: 700; border-bottom: 2px solid var(--ink); padding: 10px 14px`. `td` is `padding: 10px 14px; border-bottom: 1px solid var(--rule)`. `tbody tr:hover td` gets bg `--sheet-2`.
- `.form-grid`: `gap: 16px 20px`. `.review-pair`: gap 24px. `.review-pair img`: border 1px `--rule-strong`. `.review-pair textarea`: `font-family: var(--read); line-height: 1.7; min-height: 420px`.
- `details > summary`: `min-height: 48px; display: flex; align-items: center; font-weight: 600; color: var(--indigo); cursor: pointer`.
- `pre`: `font-family: var(--mono)`. The inline diff background (`var(--paper)`) is kept.
- The login page uses the same tokens: a centred 460px column with an h1 and the form stacked with a 16px gap.

---

## 6. Responsive

| Breakpoint | Changes |
|---|---|
| ≥ 1001px | As specified. |
| ≤ 1000px | `--rail: 96px`. `.rail` padding is `16px 8px`, and the `.mark::before` bar is 24px. `.hero`, `.reader`, `.story-block`, `.qr-panel` and `.review-pair` become one column. `.hero h1` uses `--step-4`. `.scan-pane` is `position: static` with `.osd` at 55vh. `.drawers` has 2 columns. `.page` padding is `28px 24px 64px`. The map aside is not sticky. |
| ≤ 640px | The existing rail-to-header behaviour is kept exactly. `.rail` gets `border-right: 0; border-bottom: 1px solid var(--rule)`. `.drawers` has 1 column with `gap: 48px`. `.searchbar` and `.ask-form` have 1 column. `.hero h1` uses `--step-3`. `.page` padding is `20px 16px 48px`. `.sheet` and `.result` padding is `20px`. |

---

## 7. High-contrast override rules (after the token block)

Keep the existing section and update it to:
```css
:root[data-contrast="high"] .notice,
:root[data-contrast="high"] .banner,
:root[data-contrast="high"] .cite,
:root[data-contrast="high"] .empty-state,
:root[data-contrast="high"] .sheet,
:root[data-contrast="high"] .result,
:root[data-contrast="high"] .drawer,
:root[data-contrast="high"] .drawer::before { border: 2px solid #000000; }
:root[data-contrast="high"] .drawer::before { border-bottom: 0; }
:root[data-contrast="high"] .segment.active { outline: 3px solid #000000; }
:root[data-contrast="high"] .chip:not(.mt) { border-color: #000000; color: #000000; }
:root[data-contrast="high"] .rail { border-right: 2px solid #000000; }
:root[data-contrast="high"] .rail .langs button,
:root[data-contrast="high"] .rail .toggle { border-color: #000000; }
:root[data-contrast="high"] .btn.secondary:hover,
:root[data-contrast="high"] .btn.quiet:hover,
:root[data-contrast="high"] .chip-link:hover,
:root[data-contrast="high"] .rail a.navlink:hover { background: var(--brass-wash); color: #000000; }
:root[data-contrast="high"] .passage.target { outline-width: 3px; }
```
Note: the rail border rule changes from `#fff` to `#000`, because the rail is now white.

---

## 8. Motion

- Transitions are `var(--dur) var(--ease)` on background-color, border-color, color and transform, for `.btn`, `.chip-link`, `.drawer`, `.rail a.navlink`, `.staff-top nav a`, `.result` and `.story-card`. There are no transitions on layout properties.
- There are only 2 transforms: drawer lift (−3px) and button press (+1px). The only animation is the signage slide-in.
- Keep the `prefers-reduced-motion: reduce` block as the last rule in the file, unchanged.
- ScanViewer already reads reduced-motion for OSD animation. No change there.

Optional safety net:
```css
@media (forced-colors: active) {
  :focus-visible { outline-color: Highlight; box-shadow: none; }
  .btn, .chip-link, .rail .langs button, .rail .toggle { border: 2px solid ButtonText; }
}
```

---

## 9. Constraints for the developer

1. **Do not change** class names, DOM structure, ARIA, `role`s, ids, or text content. The tests locate elements by `.chip`, `.chip.ai`, `.chip.mt`, `.passage.target`, `.reader-head .meta`, `.step-btn.prev/.next`, `.pager [aria-current=true]`, `.slide`, `main.signage footer span`, `.qr svg`, `.card-caption`, `.cite`, `.notice(.bad)`, `.banner.offline`, `.staff-top nav a`, `table.grid`, `.empty-state`, `.map-wrap`, `.attract`, `.rail .toggle` and `[role=tab]`. Pseudo-elements must be decorative (`content: ""`) so textContent is unchanged.
2. **The only TSX edits allowed** are `Signage.tsx:63` (drop `color`), `Signage.tsx:65` (`var(--brass-ink)`) and `ScanViewer.tsx:45` (the highlight colours). These are colour literals only.
3. **Token test:** colour tokens must be 6-digit hex in `:root {` and `:root[data-contrast="high"] {`. Default `--paper` must differ from HC `--paper` (e2e checks the body background changes).
4. **Touch targets:** every interactive element keeps `min-height ≥ 48px`, and `min-width ≥ 48px` when its label is 3 characters or fewer (`smallTargets()` in `a11y.test.tsx`). No interactive element may become `display: inline`. Keep `.link-target`, `.title-link`, `.result h2 a` and `.result h3 a` as `inline-flex` with 48px. `.cite-link` stays `inline-flex` 48×48.
5. **Side-by-side reader** at kiosk width (above 1000px) must stay two columns, with the scan on the left and top-aligned.
6. **Focus:** the ink outline plus gold band is visible on every surface. Never set `outline: none` except on `.main` and `.staff main`, which are programmatic focus targets.
7. **Reduced motion:** the existing block stays last.
8. **Fonts:** only the `@fontsource` imports in section 3. No `@import url(http…)` and no Google Fonts.
9. Replace every remaining literal in `styles.css` that referred to the dark theme (`#2a2f3d`, `#1d212c`, `#dfe4f3` except on `.story-card span`, `#a9b3d6`, `#c7cfea`, `#fbe9e9`, the `rgba(255,255,255,…)` hover colours on the rail, and the radial gradient on `.attract`) with the tokens above.

---

## 10. Deviations from the brief and prior design (deliberate)

- **The rail, signage, attract screen and idle dialog change from dark indigo to light.** The brief says "light themed". Contrast is held by ink text and the blue active state.
- **The focus ring changes from amber/gold-by-surface to one universal ink ring with a gold band.** One rule now works on every light surface and in HC.
- **The focus-surface override rule is deleted.** It existed only for dark surfaces.
- **Font weights are added:** Mukta 600, Noto Serif 700 and Noto Serif Devanagari 700 (latin and devanagari subsets only). This adds about 4 woff2 files to the offline precache, which is needed for bold editorial headings.
- **The base text size goes from 17px to 18px**, because kiosk reading distance is about 60 to 80cm. The staff console is scoped back to 16px.
- **Brass is no longer an accent** and is restricted to citation and verification semantics. The one solid-blue block is the story card.
- **Three TSX colour literals change** (section 9.2). Without this, signage text would be white on paper and the scan highlight would fail 1.4.11.

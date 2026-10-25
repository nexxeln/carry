# Engines

Carry depends on the shaping engine running its GSUB lookups as the OpenType specification describes. This page lists what has been tested, what each engine does differently, and how to work around it.

## Tested

| Engine | Used by | Tested with | Result |
| --- | --- | --- | --- |
| HarfBuzz 15.0.0 | Chrome, Firefox, Android, LibreOffice, many Linux apps | `hb-shape`, 20,038 cases | all pass |
| CoreText, macOS 27.0.1 | Safari, TextEdit, Pages, most Mac apps | `tools/ctshape`, 20,038 cases | all pass |
| TextKit 1, macOS 27.0.1 | TextEdit's text view | `tools/tkshape`, 20,038 cases | all pass |
| Chromium 145 | Chrome, Edge, Arc | Playwright, 638 cases drawn on canvas and as page text, plus typing | all pass |
| Firefox 146 | Firefox | Playwright, same cases | all pass |
| WebKit 26 | Safari | Playwright, same cases | all pass with `word-break: keep-all` |

Not tested: DirectWrite (Windows apps outside the browser), Safari.app itself, and any app other than through the engines above. Google Docs cannot use Carry at all, because Docs only offers fonts from the Google Fonts library.

The browser checks compare pixels against Carry Plain, the same font with its GSUB table removed, so a correct answer is pixel-identical. Chrome and Firefox run web fonts through the OTS sanitizer first, so a rejected font would fail every case.

The extended arithmetic suite adds 3,086 signed, spaced, decimal, and division cases per direct shaping engine. The browser suite has 874 canvas cases in Chromium and WebKit, and 791 in Firefox after excluding unsupported non-breaking-space inputs. Representative spaced, decimal, and division DOM text is also checked pixel for pixel. WebKit's spaced inline width differences are reported separately, not counted as correct measurements.

## Using Carry on a web page

```css
@font-face {
  font-family: "Carry";
  src: url("Carry.woff2") format("woff2");
  font-display: block;
}

.carry {
  font-family: "Carry", monospace;
  letter-spacing: normal;
  font-feature-settings: "calt" 1;
  word-break: keep-all;
}
```

Each property works around one engine below. `font-display: block` avoids a flash of the fallback font, which would show sums without answers.

## Differences between engines

### Spaces in browser text

ASCII spaces work around operators, before `=`, and between a unary sign and its number. CoreText, TextKit, and direct HarfBuzz shaping also support non-breaking spaces.

Chromium canvas needs this setting before drawing spaced expressions:

```js
ctx.textRendering = "optimizeLegibility";
ctx.font = "24px Carry";
ctx.fillText("128 + 256 =", 0, 30);
```

Firefox can split short runs containing only non-breaking spaces through its word cache, preventing the font from seeing the complete expression. Use ASCII spaces instead. Non-breaking-space expressions are outside Firefox's supported syntax, including editable text.

WebKit draws spaced inline DOM expressions correctly but can omit the generated answer from the inline width. This can affect surrounding layout, clipping, and selection. Use unspaced expressions for width-sensitive inline text. Canvas and editable text are tested separately; a correct canvas render is not proof of correct inline measurement.

### Chromium turns contextual alternates off under letter-spacing

Carry's rules live in the `calt` feature. Chromium disables it whenever `letter-spacing` is not zero, so every answer disappears. Firefox and WebKit keep it on. `font-variant-ligatures: contextual` does not bring it back. `font-feature-settings: "calt" 1` does.

### WebKit splits page text at a hyphen before shaping

In WebKit, `5-7=` in normal page text reaches the font as `5-` and `7=`, so subtraction typed with an ASCII hyphen draws no answer. `white-space: nowrap` and `pre` do not stop the split. `word-break: keep-all` does, and so does an editable element like `<textarea>`. Canvas text is not affected, and neither is the real minus sign `−` (U+2212). Chromium and Firefox do not split.

### Chromium reshapes from the last safe break after an edit

When text is edited, Chromium keeps the shaping of the text before the edit and reshapes only from the last point HarfBuzz marked safe to break. HarfBuzz marks a point unsafe only where a rule matched across it. Before `=` is typed, nothing matches across the digits of the second number, so typing `=` used to reshape only the tail, which never sees the whole sum. Carry's first pass replaces every digit, operator, or `=` after a digit or operator with itself, which marks every boundary in an expression unsafe. `tests/typing_test.mjs` types and edits sums key by key in all three browsers.

### CoreText repeats long contextual insertions

CoreText re-applies a multiple substitution called from a contextual rule when it inserts more than 64 glyphs in front of the matched glyph. At 65 glyphs it produces 512. Plain multiple substitutions are fine at any length, and so are ones that insert after the matched glyph. HarfBuzz handles every case. Carry inserts at most 63 pads per pass, so builds wider than 64 digits get extra padding passes. `probe/probe.py` reproduces the behaviour.

### HarfBuzz has a per-call operation budget

HarfBuzz gives each shaping call a budget of 4,096 operations per input character (at least 65,536) and silently stops applying lookups when it runs out. Every successful contextual match charges the length of its context, except ranges longer than 255 glyphs. A short input that expands into a long line is exactly what the budget guards against. Carry reads zero digits through a context-free fallback rule, so only real digits pay. At the shipped widths, lines of 64 maximum-length sums or products all draw their answers.

## macOS font pickers

macOS lists and picks fonts by PostScript name (`Carry-Regular`), and some pickers only show fonts that support the document's language. `tests/check_install.py` runs Apple's `FontValidator` and looks the font up by name. Carry includes printable ASCII so that CoreText reports English among its supported languages.

If subtraction does not compute in TextEdit, check **Edit → Substitutions → Smart Dashes**, which may replace a typed `-` with a dash. This has not been tested.

## Checks

`uv run scripts/release.py` builds the font and writes `dist/` only if every check passes. It needs macOS, HarfBuzz's `hb-shape`, Xcode's `swiftc`, Node, and Playwright's Chromium, Firefox, and WebKit (`bun install && npx playwright install chromium firefox webkit`).

| Check | What it proves |
| --- | --- |
| `tests/test_shape.py` | 20,000 random sums, differences, and products, plus edge cases, draw the right answer in HarfBuzz, CoreText, and TextKit |
| `tests/test_extended.py` | signed, spaced, decimal, and division expressions, malformed inputs, maximum-width results, and dense lines draw the expected text and advances |
| `tests/check_install.py` | Apple's `FontValidator` passes and macOS finds the font by name |
| `tests/browser_test.mjs` | Chromium, Firefox, and WebKit draw every answer, pixel for pixel |
| `tests/typing_test.mjs` | answers survive typing, deleting, and editing key by key |
| `tests/hero_test.mjs` | the README caret follows typing, resets on repeat, and respects reduced motion |
| `tests/playground_test.mjs` | real example answers, display modes, source text, keyboard focus, mobile layout, and missing-font behavior work in all three browsers |
| fontbakery | `check-universal` reports no failures |

`scripts/sweep.py` measures size and speed at other widths, and `probe/probe.py` reproduces the engine behaviours the design depends on.

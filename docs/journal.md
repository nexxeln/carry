# Carry build journal

Carry is a font that does arithmetic. Type `128+256=` in it and it draws `128+256=384`. All of the work happens in OpenType GSUB substitution rules: no HarfBuzz WASM shaper, no code, nothing outside the font file. `generate.py` writes every glyph and every rule. Nothing in `build/` is written by hand.

Entries are in the order things happened. Numbers are from the build at that point.

## 0. Name and setup

- The name is **Carry**. The carry ripple is the one step that needs a GSUB lookup type almost nobody uses (reverse chaining, type 8), and it is the part that makes multi-digit addition work. A font named after its hardest moving part felt right.
- Python 3.13 with fontTools 4.67 (feaLib for the rules, FontBuilder for the tables), managed with `uv`.
- Engines on this machine: `hb-shape` from HarfBuzz 15.0.0 (Homebrew), and CoreText on macOS 27.0.1.

## 1. Probe the engines before designing anything

The design depends on engine behaviour that the spec allows but that I had never checked on CoreText. So the first artifact was a throwaway font (`probe/probe.py`) with one rule per question:

| Question | Rule | HarfBuzz | CoreText |
| --- | --- | --- | --- |
| Does a reverse chaining lookup (type 8) see its own earlier output in its lookahead? | `rsub a' b by b;` on `aaaab` | `bbbbb` | `bbbbb` |
| Does a chaining lookup (type 6) see its own earlier output in its backtrack? | `sub c a' by c;` on `caaaa` | `ccccc` | `ccccc` |
| Can a contextual rule call a multiple substitution? | `sub e' lookup EXPAND;` | `a e x x x` | `a e x x x` |
| How long can a backtrack context be? | `s` + (n-1) wildcards + `t'`, n up to 100 | all pass | all pass |
| How long can a lookahead context be? | same, mirrored | all pass | all pass |

Two findings shaped everything after this:

1. **One lookup can move information across the whole line.** A left-to-right chaining lookup reads glyphs it has already rewritten, so it can carry state rightward in a single pass. A reverse chaining lookup does the same right to left. I had expected to need one lookup per step of propagation.
2. **Long contexts are fine.** I expected HarfBuzz's `HB_MAX_CONTEXT_LENGTH` (64) to cap backtrack and lookahead. It does not cap them: both engines matched a 100-glyph backtrack and a 100-glyph lookahead. I did not test long *input* sequences, because this design never needs an input longer than one glyph.

To trust the CoreText column I wrote a second, independent harness: `tools/ctshape.swift` loads the font with `CTFontManagerCreateFontDescriptorsFromData`, lays out each line with `CTLineCreateWithAttributedString`, and prints glyph names and advances. It agrees with `hb-shape --shapers=coretext` on every probe. OTS (the sanitizer Chrome and Firefox run on web fonts, `opentype-sanitizer` 9.2.0) accepts the probe font.

## 2. Design: pad the operands so every distance is a constant

The brief suggested tagging each digit with its place value, then ferrying digit values across the line with contextual passes. Finding 2 above made a simpler design possible, so I dropped place tags and ferrying entirely.

The problem with "ferrying" is that the distance between a digit of A and the answer slot that needs it depends on the lengths of both operands. A contextual rule only matches a fixed shape. So instead of moving the digits, make the distance fixed:

1. **Pad.** The first digit of each operand looks ahead, counts how many digits follow it before the operator (or `=`), and uses a multiple substitution to put the right number of zero-width `pad` glyphs in front of itself. With n = 4, `128` becomes `pad 1 2 8`. Both operands are now exactly n glyphs long.
2. **Slots.** An `=` that follows a padded operand, an operator, and another padded operand becomes `=` followed by a carry slot and n answer slots.
3. **Read.** After padding, the layout is always `A[n-1]..A[0] op B[n-1]..B[0] = C R[n-1]..R[0]`. Slot `R[j]` finds `B[j]` exactly n+2 glyphs to its left and `A[j]` exactly 2n+3 to its left, for every j and every pair of input lengths. So "fetch the digit" becomes one fixed-length backtrack context with wildcards in between. Ten rules read B (one per digit value), ten rules read A.

This removes the per-digit place tags (10 glyphs per digit position) and all ferrying passes. The glyph count no longer depends on n at all. What grows with n is context length and the number of padding rules.

### Subtraction falls out of signed columns

I designed subtraction into the column model from the start instead of bolting it on later:

- Reading B into an addition slot stores `+b`. Reading it into a subtraction slot stores `-b`. Reading A then adds `a`. Every column ends up holding a signed value from -9 to 18.
- A left-to-right **sign** pass copies the sign of the first nonzero column into every later slot. The most significant nonzero column decides the sign of the whole answer, because the columns after it can add or remove at most 10^k - 1.
- The right-to-left **carry** pass (reverse chaining) starts from the last slot, which knows the final sign. If the answer is negative, every column is negated before settling, so the font computes `B - A` and the carry pass only ever produces a carry of -1, 0, or +1.
- The **show** pass turns leading zeros into zero-width blanks, turns the carry slot of a negative answer into a minus sign, and turns the rest into visible digits.

Each pass consumes one family of glyphs and produces the next (`slot` → `b.*` → `col.*` → `col.*.{z,p,n}` → `d*.c*.{p,n}` → `res.*`). No pass can accidentally match glyphs that belong to another stage.

### Guard rails

Some rules exist only to stop the font from computing when it should not:

- `ignore sub [@DIGIT period comma] @DIGIT';`: only the first digit of a number pads itself, and `1.5` does not count as the number `5`.
- `ignore sub equal' [@PADDED period comma];`: if the answer is already typed (`12+3=15`), do not draw a second one.
- `ignore sub [@DIGIT @OP equal period comma] A op B equal';`: an operand longer than n digits, or a chain like `1+2+3=`, draws nothing rather than a wrong answer.

## 3. First build: addition and subtraction at n = 4

The first build computed every hand-picked case on both engines, which made me suspicious of the check rather than pleased with the font. So the next step was a real harness.

`test_shape.py` builds a suite of expressions, shapes all of them in one batch per engine (`hb-shape --text-file` for HarfBuzz, `tools/ctshape` for CoreText), and maps each glyph back to the character it draws. Zero-width `pad` and `blank` glyphs map to nothing. Any intermediate glyph that survives to the output maps to `<name>` and fails the case. It also checks that the total advance equals 600 units times the expected number of characters, so an invisible glyph with a width would fail too. Hand-picked edge cases cover `9999+9999`, `0-9999`, leading zeros, an answer already typed, chained operators, and operands one digit too long.

To check that the harness can fail, I built a mutant whose carry pass ignores the incoming carry. The harness rejected it: 242 of 523 passed, with failures like `9999+1=9990`.

| Build | Max digits | Glyphs | Lookups (top-level passes) | Context rules | GSUB bytes | File bytes | HarfBuzz | CoreText |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| n = 4 | 4 | 226 | 38 (7) | 44 | 3,912 | 12,292 | 3023/3023 | 3023/3023 |

## 4. Sweep: where it breaks

`sweep.py` builds the font at many widths, runs the harness on each, times 1000 maximum-length sums per engine, and counts how many `9+9=` fit on one line before an answer goes missing. Glyph count stays at 226 for every width, so the "glyph explosion" I expected never happened. Width shows up as longer contexts and more padding rules instead.

### Wall 1: CoreText and long insertions (n > 64)

At n = 96, CoreText drew no answers for 74 of 223 cases. The glyph stream for `1+1=` had 1,045 pads where HarfBuzz had 190: the 95-pad insertion had run 11 times.

- **Dead end.** At n = 96 the GSUB passes 64 KB and fontTools wraps every lookup in an Extension lookup (type 7). I forced extensions at n = 4 and n = 64 with `useExtension`. CoreText handled both correctly, so extensions were not the cause.
- **Isolation.** Four tiny fonts at 64, 65, 66, and 100 output glyphs: contextual vs plain, and inserting before vs after the matched glyph. Only one shape fails, and it fails exactly at 65: **a multiple substitution called from a contextual rule that puts more than 64 glyphs in front of the glyph it matched.** CoreText produces 512 or more glyphs instead of 65. Plain multiple substitutions are fine at 100. So are contextual ones that append after the glyph. That explains why n = 64 passed even though its `=` expansion emits 66 glyphs: they go after the `=`.
- **Fix.** Each PAD pass inserts at most 63 pads (`PADS_PER_PASS` in `generate.py`). Wider builds get a second or third PAD pass, and each one finds the first digit by the pad now in front of it. CoreText is green again at n = 96 and n = 128.

### Wall 2: HarfBuzz's operation budget (n > 72 with several sums per line)

At n = 192, `1+2= 3+4=` drew the first answer and then leaked `b.0` glyphs for the second. HarfBuzz gives every shaping call an operation budget of `max(4096 × input length, 65536)` (`HB_BUFFER_MAX_OPS_FACTOR` and `HB_BUFFER_MAX_OPS_MIN` in `hb-limits.hh`). When the budget runs out, HarfBuzz stops applying lookups and returns what it has.

Inserting glyphs costs budget, but the main cost here is that every successful contextual match marks its whole context range unsafe-to-break, and `_infos_set_glyph_flags` charges the length of that range (`hb-buffer.hh`). The two read passes match once per slot with contexts of n + 2 and 2n + 3 glyphs, so one sum costs roughly n × 3n. A sum like `9+9= ` brings only 5 characters, which is 20,480 of budget.

| n | `9+9=` per line, HarfBuzz | CoreText |
| --- | --- | --- |
| 64, 72 | 256 (all tested) | 256 |
| 80 to 96 | 2 | 256 |
| 104 to 120 | 1 | 256 |
| 128 | 256 | 256 |
| 136 to 168 | 2 | 256 |
| 176 to 192 | 1 | 256 |

The recovery at n = 128 looked like a bug in my test. It turned out to be HarfBuzz: `_set_glyph_flags` returns early for ranges longer than 255 glyphs (`hb-buffer.hh:494`). From n = 127, the `read_a` context is 2n + 3 > 255 glyphs, so it stops costing anything, and only `read_b` is charged. The model "cost per sum ≈ n × (sum of read contexts no longer than 255)" predicts every row of the table.

So a single sum works up to at least n = 192 in both engines. A line full of sums only works in HarfBuzz (Chrome, Firefox, Android) up to n = 72. CoreText showed no budget at all.

| n | Glyphs | Lookups (passes) | GSUB bytes | File bytes | µs per max-length sum, HarfBuzz | CoreText |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | 226 | 38 (7) | 3,912 | 12,292 | 8.8 | 18.0 |
| 8 | 226 | 42 (7) | 5,198 | 13,580 | 20.8 | 36.3 |
| 16 | 226 | 50 (7) | 8,862 | 17,244 | 63.1 | 89.2 |
| 32 | 226 | 66 (7) | 20,798 | 29,180 | 211.4 | 264.3 |
| 64 | 226 | 98 (7) | 63,102 | 71,484 | 774.2 | 905.5 |
| 96 | 226 | 99 (8) | 80,838 | 89,220 | 2,857.8 | 2,010.2 |
| 128 | 226 | 100 (9) | 105,852 | 114,232 | 8,560.5 | 3,578.6 |

Shaping time grows roughly with n squared, because n slots each check contexts that are O(n) long. Lookups grow by one per padding size until the cap of 63 pads per pass.

## 5. Multiplication (v3)

Multiplication worked, and it is where the costs finally show up.

### Design

Schoolbook long multiplication, one row per digit of B. Both operands are padded to **2m** glyphs, and `=` grows 2m slots that all start as `mc0.c0` (digit 0, carry 0):

    A[2m-1] .. A[0]  ×  B[2m-1] .. B[0]  =  R[2m-1] .. R[0]

Row j adds `A[k-j] × B[j]` into every slot `R[k]`, in three passes:

1. **Spread B[j].** The first slot reads B[j], which is always j + 2 glyphs to its left. Every later slot copies that digit from its left neighbour, so one left-to-right pass reaches all 2m slots. A slot now holds the pair (current digit, b): the `acc*.b*` family, 100 glyphs.
2. **Multiply.** Every slot reads the glyph 4m + 2 - j to its left. For every k, that is `A[k-j]`, the A digit that lines up with this slot in row j. The slot becomes `val.(r + a×b)`, a total from 0 to 90.
3. **Carry.** A reverse chaining pass, right to left, adds the carry from the right neighbour, keeps the last digit, and passes the rest (0 to 9) left: the `mc*.c*` family, 100 glyphs.

The padding to 2m is what makes this safe. When k - j is out of range, the 4m + 2 - j position lands on the `×` or on one of B's leading pads, never on a real digit. So no operand tags are needed. A context-free fallback rule reads "anything that is not a nonzero digit" as 0.

That adds 291 glyphs, in families of fixed size: 517 glyphs in total, for any width. Passes grow by 3 per digit of m.

### Checks

- A mutant whose row carries ignore the incoming carry fails 263 of 324 multiplication cases. One failure is `9999×9999=1234321`.
- **Bug found by the sweep.** At d = 1, `10*2=` drew `20`. The arithmetic was right, but 10 has two digits and the limit was one. Multiplication validation only checked for a block of 2m padded glyphs, and an operand of exactly 2m digits fills that block with no pads. At m = 8, a 16-digit × 16-digit product would have drawn a wrong, truncated answer. The fix requires the first m glyphs of each multiplication operand to be pads. A real m-digit operand always has at least that many. The harness now includes 2m-digit operands.

### The zero-digit fallback

The budget model from section 4 said a long context costs HarfBuzz budget only when it *matches*. Multiplication already read zero digits through a context-free fallback, and short products were cheap. The add/sub read passes matched a full context even for pads (digit value 0). I moved zero to a fallback rule there too.

- Lines of `9+9=` at n = 96 went from 2 to 256 (all tested). n = 192 went from 1 to 256.
- Lines of max-length sums at n = 96: 16 per line (all tested), on both engines. Long operands bring budget in proportion to their length.
- It is not free. Measured back to back with `hb-shape` (2,000 lines, best of 7 interleaved runs, n = 16): max-length sums went from 129.0 to 116.1 µs, and 2-to-3-digit sums went from 54.7 to 156.7 µs. HarfBuzz checks a backtrack from the nearest glyph outward, and the glyph that decides a read is the farthest one. For a pad slot, each of the nine nonzero rules now walks all n + 1 wildcards before failing, and only then does the fallback fire. Before, the zero rule came first and matched in one walk. I kept the fallback. A tenth of a millisecond is cheaper than a sum that silently draws nothing.
- My first version of this bullet said shaping time "stayed about the same". I had compared two sweep runs made at different times. Between them, products got 2× slower even though their rules did not change, so those runs are not comparable. The table below has the same problem across rows run at different times. Compare within a row, not across sweeps.

### Numbers, every operator at width d

| d | Glyphs | Lookups (passes) | File bytes | µs per max sum, HarfBuzz / CoreText | µs per max product, HarfBuzz / CoreText |
| --- | --- | --- | --- | --- | --- |
| 1 | 517 | 60 (10) | 23,700 | 3.7 / 17.3 | 5.3 / 21.2 |
| 4 | 517 | 75 (19) | 28,036 | 15.5 / 39.4 | 113.7 / 157.7 |
| 8 | 517 | 95 (31) | 36,632 | 38.3 / 75.6 | 627.2 / 743.6 |
| 12 | 517 | 115 (43) | 48,972 | 68.3 / 120.2 | 1,909.5 / 2,110.0 |
| 16 | 517 | 135 (55) | 65,056 | 110.8 / 178.0 | 4,201.5 / 4,611.6 |
| 24 | 517 | 175 (79) | 125,512 | 224.6 / 319.4 | 13,332.4 / 14,324.1 |

Sums grow with d squared and products with d cubed: 2m slots per row, m rows, and a read context of up to 4m + 2 glyphs. Wide sums with multiplication capped at 4 digits stay green on both engines up to n = 192, the widest I built. At that width a single sum takes 87 ms in HarfBuzz and 15 ms in CoreText, far too slow to type into.

### What ships

`uv run generate.py` builds **16 digits for `+` and `-`**, and **8 digits for `×` and `*`** (16-digit products). Both beat JavaScript's `Number`, which loses integers past 2^53 (16 digits).

| Build | Glyphs | Lookups (passes) | Context rules | GSUB bytes | File bytes | HarfBuzz | CoreText |
| --- | --- | --- | --- | --- | --- | --- | --- |
| n = 16, m = 8 | 517 | 95 (31) | 406 | 24,972 | 37,804 | 20032/20032 | 20032/20032 |

## 6. Real browsers and TextEdit

`browser_test.mjs` serves the font to Chromium, Firefox, and WebKit (Playwright 1.58) and draws 632 harness cases two ways: on a canvas, and as DOM text. The reference is the expected text in **Carry Plain**, a copy of the font with GSUB deleted. The outlines and advances are identical, so a correct answer is pixel-identical. Chrome and Firefox run web fonts through OTS before HarfBuzz sees them, so a rejected font would fail every case.

| Engine | Canvas and DOM (`word-break: keep-all`) | DOM without `keep-all` |
| --- | --- | --- |
| Chromium 145 | 632/632 | 632/632 |
| Firefox 146 | 632/632 | 632/632 |
| WebKit 26 | 632/632 | 476/632 |
| TextKit 1 (`tools/tkshape`, TextEdit's layout engine) | 5032/5032 | n/a |

### WebKit splits DOM text at a hyphen

In WebKit, every subtraction typed with an ASCII hyphen-minus lost its answer in DOM text, and only there. Canvas drew it correctly, and `5−7=` with a real minus sign (U+2212) worked everywhere. A probe of span styles showed the cause: WebKit breaks DOM text into separate pieces at the hyphen *before* shaping. `5-7=` reaches the font as `5-` and `7=`, so no rule ever sees the whole expression. `white-space: nowrap` and `white-space: pre` do not stop it. `word-break: keep-all` does. `<textarea>` and `contenteditable` elements also draw it correctly, so editing-mode layout must not split there.

Chromium and Firefox never split it, and TextKit does not either. A page that sets Carry text should use `word-break: keep-all`, or take typing in a `<textarea>`.

A dead end on the way: my first `<input>` check reported a mismatch in every browser, including Chromium on `128+256=`, which certainly works. `<input>` centers text vertically, so the screenshot did not line up with the reference. The method was broken, not the font.

### Engine differences found so far

1. **CoreText** repeats a contextual multiple substitution that puts more than 64 glyphs in front of the matched glyph. Worked around with at most 63 pads per pass.
2. **HarfBuzz** charges a per-call operation budget for unsafe-to-break marking over matched contexts, and silently stops when the budget runs out. Worked around with the context-free zero-digit fallback.
3. **WebKit DOM** splits text at ASCII hyphens before shaping. Fixed with `word-break: keep-all`, U+2212, or an editable element.
4. **Google Docs** cannot use the font at all. Docs only offers fonts from the Google Fonts library and cannot load an uploaded `.ttf` (Google's Docs support threads say so).

## 7. Two more findings from real pages

- **Chromium turns `calt` off under letter-spacing.** Text set in Carry with `letter-spacing: 0.01em` drew every sum without its answer in Chromium. In a probe, Chromium dropped the answer at any nonzero letter-spacing, and Firefox and WebKit kept it. `font-variant-ligatures: contextual` did not bring it back. `font-feature-settings: "calt" 1` did. `tests/browser_test.mjs` now reports it: with letter-spacing, Chromium loses the answer in every case that computes, and Firefox and WebKit lose none.
- **A measurement mistake on the way.** My first letter-spacing check compared spaced text against the expected string and reported failures in all three browsers. Letter-spacing is added per character, and the answer glyphs belong to the `=` character, so those widths can never match. The check now asks whether the answer vanished: is the spaced width the same as the typed text alone?
- **Reproducible builds.** Rebuilding gave different bytes every time, because fontTools stamps the current time into `head`. The generator now writes a fixed timestamp, and two builds from the same source are byte-identical.

## 8. Review corrections

A separate reviewer read this journal, the decision log, and the git history, and flagged what a casual skim would miss. What changed because of it:

- **Claims beyond what I tested.** I had not opened Safari.app, TextEdit.app, Pages, Keynote, Word, or Figma, or run anything on Android or Windows. Claims now name the engines actually tested: HarfBuzz through `hb-shape`, CoreText and TextKit called directly, and Chromium, Firefox, and WebKit through Playwright.
- **Width checks were weak.** A wrong answer of the right width would have passed. Answer checks are now pixel comparisons against Carry Plain, the same font with GSUB removed, plus a negative control that must fail.
- **Stale sweep data.** One sweep predated the multiplication validation fix, and its d = 1 row recorded the `10*2=20` failure. I re-ran it.
- **An overstated scaling claim.** I had written that sums slow down with the square of the width and products with the cube. Within one sweep, doubling from 8 to 16 digits makes the longest sum about 3× slower and the longest product about 7× slower.
- **Explanation labelled as explanation.** "Every pad walks the whole context nine times" is my reading of HarfBuzz's matching order, not something I instrumented, and the 3× slowdown for short sums was measured at 16 digits in HarfBuzz only.
- **The extension-lookup dead end** cited font files in a temp directory that no longer exists. `probe/probe.py` now builds that case too.

Honesty notes about the trail itself:

- Decision-log rows for the probe, the design, the mutation check, and the first sweep findings were written in one batch after the first two commits, not as they happened.
- Two harness failures at n = 1 and n = 2 (`007+3=` expected to compute with 1- and 2-digit limits) were test bugs. I fixed the test, not the font.

## 9. Two bugs from using it

### Typing drew no answer in Chromium

Clearing a textarea set in Carry and typing `1+1=` drew `1+1=` with no answer until something forced a full reshape, such as switching fonts. The browser test had set the textarea's value in one call, which shapes the line from scratch. It never typed.

- **Reproduced.** `tests/typing_test.mjs` types key by key into a textarea. Chromium drew no answer for every sum. Firefox and WebKit drew all of them.
- **Mechanism.** `hb-shape --show-flags` on `1+1` gave `[one=0#2|plus=1#3|one=2#2]`: the last `1` is unsafe to concat but *safe to break*. HarfBuzz marks a boundary unsafe to break only where a matched rule spans it, and before `=` is typed no rule looks across the digits of B. So HarfBuzz is right that `1+1` can be split before the last `1`. When an edit appends `=`, Chromium keeps the shaping before the last safe-to-break point and reshapes only `1=`, which is not a sum.
- **Confirmed with an experiment.** A copy of the font with one extra pass, replacing each digit, operator, or `=` that follows a digit or operator with itself, marks every boundary in the run (`one=2#3`). With it, Chromium drew every answer.
- **Smallest rule.** The experiment also covered `.` and `,`. A version with only digits, operators, and `=` passed the same edits, including `1.5+2=` (must not compute), typing an answer and deleting it again, and inserting or deleting a digit mid-expression. That version shipped as the `join` pass. I can't fully explain why Chromium also reshapes across the `.` in `1.5`. The test covers that case.
- **A test bug on the way.** My first mid-edit cases failed in every browser. I had put the caret in the wrong place: two left-arrow presses from the end of `12+5=` land before the `5`, not after it. The test now asserts what the textarea holds after each edit as well as what it draws.

### The installed font failed Font Book's validation and could not be used

- **Reproduced** with Apple's own validator, which ships with macOS at `ATS.framework/Support/FontValidator`. It failed the font on "'name' table usability", "'name' table structure", and "'sfnt' required tables".
- **Mechanism.** The name table only had a family and a style name. With no PostScript name, CoreText invented a placeholder (`font00000000308d06b6`), the system's list of PostScript names had no Carry entry, and looking up `Carry-Regular` by name returned Helvetica. Apps find installed fonts by PostScript name.
- **Fix.** A complete name table (unique ID, full name, version, PostScript name), the OS/2 REGULAR bit, and code page ranges. `tests/check_install.py` runs the validator and the by-name lookup on every built font.

## 10. Release preparation

### Letters, so font pickers list it

With the name table fixed, macOS registered the font, but TextEdit's font picker still did not list it. CoreText said the font supported 5 languages (`sd-Khoj`, `mn-Mong`, `cu-Glag`, and two more) and not English, because it had no letters. A copy with placeholder letters reported 58 languages including English. The font now has a 5×7 dot-matrix alphabet and the rest of printable ASCII, and the digit 0 has a centre dot so it differs from O.

### A digit glued to a letter is part of a name

With letters in the font, `x2+3=` and `0x1+1=` drew answers for `2+3` and `1+1`. The first-digit rule and both validation guards now treat letters and `_` like a preceding digit. `x = 2+3=` still computes. Without the rule, the four new harness cases fail.

### Release hygiene

- OFL 1.1 for the font (`OFL.txt`) and MIT for the code (`LICENSE`). The name table carries copyright, designer, and license fields.
- `generate.py` also writes `build/Carry.woff2`.
- fontbakery `check-universal` went from 4 FAIL to 0: U+00A0 added, smart dropout control in `prep`, a `gasp` table, Windows-only name records, and the monospace flags (every glyph a character maps to is 600 units wide). The 2 remaining warnings are the zero-width working glyphs and dot contour counts.
- fontbakery also found 36 glyphs no rule could reach: 27 "undecided sign" columns with a nonzero value, and 9 negative-answer digits carrying +1. The sign and carry families are now derived from the rules that produce them.
- `scripts/release.py` writes `dist/` only after the shaping harness, the install check, the browser and typing tests, and fontbakery all pass.
- `scripts/render.py` draws the README images with `hb-view` and `hb-shape --trace` from text typed into the real font.

| Build | Glyphs | Lookups (passes) | TTF bytes | WOFF2 bytes | Shaping, 3 engines | Browsers | Typing |
| --- | --- | --- | --- | --- | --- | --- | --- |
| n = 16, m = 8 | 560 | 97 (32) | 49,400 | 7,228 | 20038/20038 each | 638/638 each | 9/9 each |

## 11. Choosing the look

The rules don't depend on the outlines, so I built six fonts that differ only in how they draw glyphs and compared them on one page, rendered by Chromium, with a box to type into for each:

| Look | How it was made | TTF size |
| --- | --- | --- |
| Square dots (before) | the 5×7 bitmaps as squares with gaps | 49 KB |
| LED | the same bitmaps as round dots | 92 KB |
| Pixel | the same bitmaps as solid blocks | 49 KB |
| Fine dot matrix | JetBrains Mono sampled onto a 10×18 grid of dots | 185 KB |
| Segment display | 7-segment digits, 14-segment letters | 45 KB |
| Vector | JetBrains Mono's outlines | 42 KB |

A variant with colored answers (a COLR layer on the `res.*` glyphs) worked in Chromium, but I didn't test it anywhere else.

The user picked LED, without color. The specimen drew each dot with 8 on-curve and 8 off-curve points. TrueType allows a closed contour of off-curve points only, with an on-curve point implied midway between each pair, so the shipped font draws each dot as 8 off-curve points on an octagon, and the implied points land on the circle. The TTF is 65,696 bytes, against 92 KB for the specimen, and the WOFF2 is 7,256 bytes, almost unchanged, because WOFF2's glyph transform compresses the dots well. Every release gate passes with the new outlines.

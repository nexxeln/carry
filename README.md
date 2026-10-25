<p align="center">
  <img src="docs/images/hero.svg?v=2" width="720" alt="An LED display typing 128+256= in Carry. When the = is typed, 384 appears.">
</p>

<h1 align="center">Carry</h1>

<p align="center">
  <b>A font that does arithmetic.</b><br>
  Type <code>128+256=</code> and it draws the <code>384</code>.
</p>

<p align="center">
  <a href="dist/Carry.ttf">Download</a> ·
  <a href="docs/how-it-works.md">How it works</a> ·
  <a href="docs/engines.md">Engines</a>
</p>

<br>

Carry has no code inside. Every answer comes from OpenType substitution rules, the machinery other fonts use for ligatures, built by a Python generator. It adds and subtracts integers up to 16 digits and multiplies integers up to 8 digits, exactly, which is past what JavaScript's `Number` can hold. It also supports exact decimals and four-digit integer division with remainders.

## Use it

On a Mac, open `dist/Carry.ttf`, click **Install**, then pick Carry in TextEdit.

On the web, serve `dist/Carry.woff2` and keep the rules switched on:

```css
@font-face { font-family: "Carry"; src: url("Carry.woff2") format("woff2"); font-display: block; }

.carry {
  font-family: "Carry", monospace;
  font-feature-settings: "calt" 1;
  letter-spacing: normal;
  word-break: keep-all;
}
```

[Engines](docs/engines.md) explains each line and lists where Carry is tested. It can't work in Google Docs, which only offers fonts from Google's own library.

## What it does

| Type | Carry draws |
| --- | --- |
| `128+256=` | `128+256=384` |
| `5-7=` | `5-7=-2` |
| `12×34=` | `12×34=408` |
| `128 + 256 =` | `128 + 256 =384` |
| `-5--7=` | `-5--7=2` |
| `5×-7=` | `5×-7=-35` |
| `12.50+3.75=` | `12.50+3.75=16.25` |
| `0.1+0.2=` | `0.1+0.2=0.3` |
| `19.99×3=` | `19.99×3=59.97` |
| `84÷7=` | `84÷7=12` |
| `17/5=` | `17/5=3 r 2` |
| `-17÷5=` | `-17÷5=-3 r -2` |
| `12+3=15` | nothing extra, because the answer is already there |
| `x2+3=` | nothing extra, because `x2` is a name, not a number |

Operands accept one unary `+`, `-`, or `−`. Spaces are allowed around operators, before `=`, and after a unary sign. Spaces between digits do not join them into one number. Carry preserves the spacing you typed.

Use ASCII spaces for portable expressions. Firefox does not support non-breaking spaces reliably. WebKit draws spaced inline text correctly but can measure its width incorrectly. See [Engines](docs/engines.md#spaces-in-browser-text) for supported browser uses and canvas settings.

Decimal operands accept up to two fractional digits, with up to 16 integer digits for addition/subtraction and 8 for multiplication. Results are exact, never rounded. Unneeded trailing fractional zeros disappear, so `1.20+1.30=` draws `2.5`; products can have up to four fractional digits. A decimal point needs digits on both sides. `.5` and `1.` are unsupported.

Division accepts integer operands of up to four digits, including leading zeros. `/` and `÷` are equivalent. The quotient truncates toward zero; a nonzero remainder has the dividend's sign. Division by zero and decimal division draw no answer. Carry never checks an answer you have already typed.

When Carry can't be sure of an answer, it draws nothing rather than a wrong one.

## Playground

The local playground switches between normal text, Carry, and Carry Debug. It shows the underlying text beside the font-drawn output. JavaScript handles the controls, not the arithmetic.

From the repository root, run:

```bash
bun run playground
```

Open <http://127.0.0.1:8000/docs/playground.html>. The font files in `dist/` are ready to use; after changing the generator, rebuild them with `uv run scripts/release.py`.

Answers are visual glyphs, not inserted characters. Copying, saving, and screen readers use the underlying expression without the generated answer. Debug shows internal glyphs, not a step-by-step trace.

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/passes-dark.svg?v=2">
  <img src="docs/images/passes-light.svg?v=2" alt="The glyphs for 128+256= after each pass: typed, answer recognition, restore, pad, slots, read b, read a, sign, carry, and show.">
</picture>

Each row is the line after one substitution pass, taken from a HarfBuzz trace. Carry pads both numbers with invisible zeros until every digit sits a fixed distance from the answer slot that reads it, then a lookup that runs right to left ripples the carries. The display at the top is built the same way: each frame lights the dots HarfBuzz returns for the text typed so far.

[How it works](docs/how-it-works.md) walks through every pass.

## Build

```bash
uv run generate.py          # build/Carry.ttf and its siblings
uv run scripts/release.py   # every check, then dist/
```

The checks run on macOS with HarfBuzz, Node, and Playwright. [Engines](docs/engines.md#checks) lists them.

## License

The font is under the [SIL Open Font License 1.1](OFL.txt), the code under the [MIT License](LICENSE).

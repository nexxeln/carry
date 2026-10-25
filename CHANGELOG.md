# Changelog

## Unreleased

- A local playground with normal, Carry, and Debug modes, an underlying-text display, and packaged Carry Debug WOFF2.
- Four-digit signed integer division with `/` or `÷`, exact quotient/remainder output, and guards for zero divisors and unsupported decimal division.
- Exact decimal addition, subtraction, and multiplication with two fractional input places. Limits apply to the integer part; output trims trailing fractional zeros and never rounds.
- Signed operands and spacing around arithmetic operators and before `=`, with original text outlines and advances preserved.
- Existing signed or spaced answers suppress generated results, including during incremental editing.
- Extended shaping, browser rendering, and editing regression checks. Browser-specific whitespace limitations are documented in [Engines](docs/engines.md#spaces-in-browser-text).

## 1.0.0

The first release.

- Addition and subtraction of numbers up to 16 digits, multiplication up to 8 digits, with exact answers drawn by OpenType GSUB substitutions alone.
- Negative answers, suppressed leading zeros, and guard rules that draw nothing for typed answers, chains, numbers over the limit, decimals, and digits attached to names.
- A 5×7 LED dot-matrix design covering printable ASCII, `×`, `−`, and the no-break space.
- TrueType and WOFF2 builds, licensed under the SIL Open Font License 1.1.
- Tested with HarfBuzz, CoreText, TextKit, and Chromium, Firefox, and WebKit.

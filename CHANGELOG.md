# Changelog

## 1.100 — 2026-11-15

Wider coverage, so Remedy Sans can be an interface font with no fallback behind it. The font's own version string is 1.100. 584 characters per weight (was 96), the same set in Regular and Bold.

Added, all drawn in the stroke file on the same grid and stroke weights:

- Latin-1 Supplement in full: ¡ ¢ £ ¤ ¥ ¦ § ¨ © ª « ¬ soft hyphen ® ¯ ° ± ² ³ ´ µ ¶ · ¸ ¹ º » ¼ ½ ¾ ¿, À to ÿ with Æ Ð × Ø Þ ß æ ð ÷ ø þ
- Latin Extended-A in full (U+0100 to U+017F), including Đ đ Ħ ħ ı Ĳ ĳ ĸ Ŀ ŀ Ł ł ŉ Ŋ ŋ Œ œ Ŧ ŧ ſ
- Ș ș Ț ț (comma below), ƒ, and ȷ (dotless j, the base of ĵ)
- The accents on their own: ˆ ˇ ˘ ˙ ˚ ˛ ˜ ˝
- Greek: Ά Έ Ή Ί Ό Ύ Ώ ΐ, Α to Ω, Ϊ Ϋ ά έ ή ί ΰ, α to ω, ϊ ϋ ό ύ ώ
- Cyrillic U+0400 to U+045F, and Ґ ґ Ғ ғ Қ қ Ң ң Ү ү Ұ ұ Һ һ Ә ә Ө ө
- Punctuation: ‐ ‑ ‒ – — ― ‘ ’ ‚ “ ” „ † ‡ • … ‰ ′ ″ ‹ › ‼ ⁄
- Spaces as empty glyphs: figure (one digit wide), punctuation (one period wide), thin, hair, narrow no-break
- Currency € ₹ ₽ ₺ ₩ ₪ ₫ ₱ ₴ ₸ ₿; ™ №; arrows ← ↑ → ↓ ↔ ↕ ⇧; maths − ∞ √ ≈ ≠ ≤ ≥
- Shapes: ◻ ▲ ▼ ► ◄ ⏴ ⏵ ⏶ ⏷ ✓ ✗ ● ○

Source format:

- `mark <name> <anchor> above|below|attach` draws an accent once; `anchor <name> x,y` says where it sits on a letter; `glyph U+00C1 = U+0041 + acute` composes a letter from a base and marks. Above and below marks are lifted clear of the letter by one stroke weight plus a fixed gap, so the gap looks the same in both weights.
- `use <code> [dx,dy]` reuses another character's strokes; `put <mark> x,y [touch]` places a mark by hand; `F x,y ...` draws a filled polygon with round corners.
- Character codes may be written as `U+00C1` as well as decimal.

Fixes and checks:

- A closed curve whose points all come out off-curve (small circles) was dropped by the build. This removed the counters of `%` in 1.000. They are back.
- `check.py` now checks the full character list in both weights, that every character except the spaces has an outline, space widths, that no accent touches its letter, that no glyph reaches outside the line box, and the counters of the new round letters.
- The line box grows to fit the accents on capitals and the comma below: ascent 1048 to 1312, descent -340 to -416 (both weights). Lines set in Remedy Sans are therefore taller than in 1.000.
- `specimen.html` and `specimen.png` show the new characters and sample text in several languages.

## 1.0.0 — 2026-11-15

First public release. The font's own version string is 1.000.

- Regular and Bold, each as TrueType (`.ttf`) and WOFF2 (`.woff2`)
- 95 characters drawn from the stroke source: Basic Latin, U+0020 through U+007E
- U+00A0 no-break space uses the space glyph
- `check.py` checks advances, closed counters, and that both weights share one set of vertical metrics

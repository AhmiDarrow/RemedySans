# Changelog

## 1.200 — 2026-11-18

Five weights, the same set as Remedy Sans UI. The font's own version string is 1.200.

- New Light (300), Semilight (350) and Semibold (600), built from the same stroke file at stroke weights 2.1, 2.55 and 3.6. The steps between weights follow Remedy Sans UI's, scaled to this font's own Regular (3.0) to Bold (4.3) distance. Each comes as `.ttf` and `.woff2` (ttfautohint) and `.otf` (otfautohint), like Regular and Bold
- Regular and Bold stay one style-linked family. The new weights carry their own legacy family name ("Remedy Sans Light" and so on) for old apps, and the typographic family Remedy Sans (name IDs 16 and 17) for apps that group by weight
- All five weights share one line box, one underline and one glyph set; `check.py` checks every weight against Regular
- The solid circle ● is now a ring with a filled disc inside instead of two rings and a dot, so it stays solid in Light

## 1.110 — 2026-11-16 (release v1.1.0)

Sharper on screen, an OpenType/CFF version, and cleaner joins. The font's own version string is 1.110. Advances, metrics and coverage are unchanged.

- The `.ttf` and `.woff2` are now hinted with ttfautohint (strong stem snapping in grayscale, GDI and DirectWrite modes) and their gasp table allows grid-fitting. Before, they were unhinted, which made small sizes look soft
- New `.otf` files for both weights: the same outlines as CFF, with PostScript hints from otfautohint; alignment zones and standard stems are measured from the font's own ink
- Redrawn where strokes did not meet or crowded each other: 2 and ? (the bowl now runs straight into the diagonal or stem), 5 (upright stem, smooth shoulder, open tail so it cannot read as 6), & (rebuilt: closed loop, leg to the baseline, open bowl), @ (smaller inner a, tail joins the ring), 3 and G (strokes meet exactly), e (the bowl starts at the end of the bar), B (the top bar reaches the bowl), the straight double quote, and ² ³ ½ ¿ which repeat those shapes (marks further apart)
- `build.py` needs `ttfautohint-py` and `afdko` in addition to the previous packages

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
- `check.py` now checks the full character list in both weights, that every character except the spaces has an outline, space widths, that no accent touches its letter, the counters of the new round letters, that the hhea and typo metrics still equal 1.000's, and that the Windows metrics cover every glyph.
- Line spacing is unchanged from 1.000: hhea and typo ascent 1048, descent -340, line gap 0, with USE_TYPO_METRICS set. Accents on capitals may rise above the ascent, as in most fonts. usWinAscent grows from 1048 to 1312 and usWinDescent from 340 to 416, so Windows never clips an accent or a comma below.
- `specimen.html` and `specimen.png` show the new characters and sample text in several languages.

## 1.0.0 — 2026-11-15

First public release. The font's own version string is 1.000.

- Regular and Bold, each as TrueType (`.ttf`) and WOFF2 (`.woff2`)
- 95 characters drawn from the stroke source: Basic Latin, U+0020 through U+007E
- U+00A0 no-break space uses the space glyph
- `check.py` checks advances, closed counters, and that both weights share one set of vertical metrics

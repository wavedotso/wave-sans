# Wave Sans

The typeface of Wave: a variable sans serif for screens, precise at small
sizes, refined at large ones, and unambiguous in every name.

- **Unambiguous.** The capital I has serifs, the lowercase l a tail and the
  zero a dot, by default, so I, l and 1 never look alike, nor do O and 0.
- **Made for screens.** Clear from 11 px. Optical size follows the font
  size: sturdier for text, finer for headlines.
- **Steady in every theme.** Grade changes stroke weight without changing
  width, for dark themes and selected states.
- **Global.** Over 2,100 characters across Latin, Greek and Cyrillic.
- **Light on the web.** Eleven files by character set: a page downloads only
  the ones it uses.

## Installation

```bash
pnpm add @waveso/sans
```

## Usage

Import the stylesheet once, in your app's entry file or root layout, and set
the family:

```js
import '@waveso/sans';
```

```css
body {
  font-family: "Wave Sans", system-ui, sans-serif;
}
```

Lower the grade for light text on dark backgrounds, and raise it for
selected and hovered states; widths never change, so nothing reflows:

```css
.dark { font-variation-settings: "GRAD" -25; }
[aria-selected="true"] { font-variation-settings: "GRAD" 100; }
```

`ss09` gives back the plain I and l, and `ss10` the plain zero:

```css
.plain { font-feature-settings: "ss09", "ss10"; }
```

## Axes

| Axis | Range | Set with |
|---|---|---|
| Weight `wght` | 100 to 900 | `font-weight` |
| Optical size `opsz` | 14 to 32 | automatic: it follows the font size |
| Grade `GRAD` | −50 to +100 | `font-variation-settings` |

## Files

| File | What it is |
|---|---|
| `wave-sans.css`, `WaveSans-*.woff2` | The web fonts in eleven files by character set, and the stylesheet that loads them |
| `WaveSans.woff2` | The whole font in one file |
| `WaveSans[GRAD,opsz,wght].ttf` | The variable font, for apps and design tools |

## License

SIL Open Font License 1.1 (`LICENSE.txt`). “Wave Sans” is a Reserved Font
Name. `FONTLOG.txt` records every change.

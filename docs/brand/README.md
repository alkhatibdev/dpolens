# The DPOLens logo

The mark is a hexagon in two pieces, a stem and a bowl, and the gap between them draws a D. Every
file here is drawn from filled outlines, so none of them needs a font.

| File | For |
| --- | --- |
| `dpolens-logo.svg`, `dpolens-logo.png` | The logo on a light ground: the README, documentation, the dashboard |
| `dpolens-logo-on-dark.svg`, `dpolens-logo-on-dark.png` | The logo on a dark ground |
| `dpolens-logo-black.svg`, `dpolens-logo-white.svg` | The logo in one colour, for print, slides and stamps |
| `dpolens-logo-stacked.svg`, `dpolens-logo-stacked-on-dark.svg`, `dpolens-logo-stacked-black.svg`, `dpolens-logo-stacked-white.svg` | The mark above the name, for square spaces |
| `dpolens-mark.svg`, `dpolens-mark-on-dark.svg`, `dpolens-mark-black.svg`, `dpolens-mark-white.svg`, `dpolens-mark-512.png` | The mark alone |
| `dpolens-mark.inline.svg` | The mark for pasting into a page, coloured by `--dpolens-logo-stem` and `--dpolens-logo-bowl`, with the light colours when they are unset |
| `dpolens-icon.svg`, `icon-192.png`, `icon-512.png` | The app icon: the mark on a white tile, inside the circle a phone may crop the icon to |
| `apple-touch-icon.png` | A phone's home screen, 180 pixels square |
| `favicon.svg`, `favicon.ico` | The browser tab. The SVG follows a light or dark browser, and the ICO is for older ones |
| `social-preview.svg`, `social-preview.png` | The card a link to the repository shows, 1280 by 640 |
| `brand-tokens.css`, `brand-tokens.json` | The logo's colours, as CSS variables and as JSON |

## Colours

| Part | On a light ground | On a dark ground |
| --- | --- | --- |
| Stem, the left piece | `#4CC38A` | `#7FDDB0` |
| Bowl, the right piece | `#12784E` | `#3FAE7A` |
| Name | `#141414` | `#FFFFFF` |

The brand green is the bowl's `#12784E`, and the dark ground is `#0D3B2A`. The stem's green is
for the logo only. The name is set in Figtree ExtraBold, with its letters 2% closer together than
the font sets them.

## Using it

- Keep each piece its own colour and the mark upright: no swapped colours, stretching, outlines
  or effects.
- On a dark ground or a photo, use the `-on-dark` or `-white` files.
- Leave clear space around the mark of at least the stem's width.
- The mark works down to 16 pixels, and the logo down to 24 pixels tall. Below that, use the mark
  alone.
- In one colour, use the `-black` or `-white` files: the gap between the pieces still draws the D.

The repository's licence covers these files. It does not grant the use of the name or the logo
as a trademark (Apache-2.0, section 6).

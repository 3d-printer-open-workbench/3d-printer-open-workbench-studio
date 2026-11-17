# Third-party notices

Open Workbench Studio itself is released under the MIT License (see `LICENSE`). This file lists third-party
material that is **bundled** in this repository and external tools/data it **talks to but does not bundle**.

## 1. Bundled fonts (`workbench-core/fonts/`)

All 36 font files were downloaded unmodified from the Google Fonts repository
(<https://github.com/google/fonts>) by `workbench-kaligraf/scripts/fetch_fonts.sh`. Each font was checked
individually: its `name` table (license / license-URL fields) and the upstream directory (`ofl/` or `apache/`)
both state a license that permits redistribution, including bundling with software. The full license text of every
font is shipped next to it in `workbench-core/fonts/licenses/`.

- **SIL Open Font License 1.1** (34 families): the fonts may be used, bundled and redistributed freely; they may not be
  sold by themselves, and modified versions must not use the Reserved Font Names. Copyright belongs to the
  respective authors as stated in each license file.
- **Apache License 2.0** (2 families: Syncopate, Yellowtail).

One font of the upstream catalogue (Kaushan Script, OFL) is not bundled; `scripts/fetch_fonts.sh` no longer
fetches it. Every bundled font has its license file next to it.

| Font file | License | License text | Upstream |
|---|---|---|---|
| `Tinos-Regular.ttf` | SIL OFL 1.1 | `licenses/tinos-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/tinos |
| `Arimo-Variable.ttf` | SIL OFL 1.1 | `licenses/arimo-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/arimo |
| `StyleScript-Regular.ttf` | SIL OFL 1.1 | `licenses/style-script-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/stylescript |
| `Mansalva-Regular.ttf` | SIL OFL 1.1 | `licenses/mansalva-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/mansalva |
| `AlexBrush-Regular.ttf` | SIL OFL 1.1 | `licenses/alex-brush-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/alexbrush |
| `Marcellus-Regular.ttf` | SIL OFL 1.1 | `licenses/marcellus-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/marcellus |
| `Montserrat-Variable.ttf` | SIL OFL 1.1 | `licenses/montserrat-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/montserrat |
| `CormorantGaramond-Variable.ttf` | SIL OFL 1.1 | `licenses/cormorant-garamond-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/cormorantgaramond |
| `BebasNeue-Regular.ttf` | SIL OFL 1.1 | `licenses/bebas-neue-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/bebasneue |
| `PlayfairDisplay-Variable.ttf` | SIL OFL 1.1 | `licenses/playfair-display-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/playfairdisplay |
| `Inter-Variable.ttf` | SIL OFL 1.1 | `licenses/inter-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/inter |
| `Jost-Variable.ttf` | SIL OFL 1.1 | `licenses/jost-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/jost |
| `EBGaramond-Variable.ttf` | SIL OFL 1.1 | `licenses/eb-garamond-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/ebgaramond |
| `Cinzel-Variable.ttf` | SIL OFL 1.1 | `licenses/cinzel-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/cinzel |
| `BodoniModa-Variable.ttf` | SIL OFL 1.1 | `licenses/bodoni-moda-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/bodonimoda |
| `AbrilFatface-Regular.ttf` | SIL OFL 1.1 | `licenses/abril-fatface-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/abrilfatface |
| `Righteous-Regular.ttf` | SIL OFL 1.1 | `licenses/righteous-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/righteous |
| `Cabin-Variable.ttf` | SIL OFL 1.1 | `licenses/cabin-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/cabin |
| `NunitoSans-Variable.ttf` | SIL OFL 1.1 | `licenses/nunito-sans-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/nunitosans |
| `Syncopate-Regular.ttf` | Apache 2.0 | `licenses/syncopate-LICENSE.txt` | https://github.com/google/fonts/tree/main/apache/syncopate |
| `Cormorant-Variable.ttf` | SIL OFL 1.1 | `licenses/cormorant-OFL.txt
cormorant-garamond-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/cormorant |
| `Fraunces-Variable.ttf` | SIL OFL 1.1 | `licenses/fraunces-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/fraunces |
| `DancingScript-Variable.ttf` | SIL OFL 1.1 | `licenses/dancing-script-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/dancingscript |
| `TheNautigal-Regular.ttf` | SIL OFL 1.1 | `licenses/the-nautigal-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/thenautigal |
| `Parisienne-Regular.ttf` | SIL OFL 1.1 | `licenses/parisienne-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/parisienne |
| `Caramel-Regular.ttf` | SIL OFL 1.1 | `licenses/caramel-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/caramel |
| `Caveat-Variable.ttf` | SIL OFL 1.1 | `licenses/caveat-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/caveat |
| `Pacifico-Regular.ttf` | SIL OFL 1.1 | `licenses/pacifico-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/pacifico |
| `GreatVibes-Regular.ttf` | SIL OFL 1.1 | `licenses/great-vibes-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/greatvibes |
| `Sacramento-Regular.ttf` | SIL OFL 1.1 | `licenses/sacramento-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/sacramento |
| `Cedarville-Cursive.ttf` | SIL OFL 1.1 | `licenses/cedarville-cursive-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/cedarvillecursive |
| `Allison-Regular.ttf` | SIL OFL 1.1 | `licenses/allison-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/allison |
| `ShadowsIntoLight.ttf` | SIL OFL 1.1 | `licenses/shadows-into-light-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/shadowsintolight |
| `MoonDance-Regular.ttf` | SIL OFL 1.1 | `licenses/moon-dance-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/moondance |
| `MsMadi-Regular.ttf` | SIL OFL 1.1 | `licenses/ms-madi-OFL.txt` | https://github.com/google/fonts/tree/main/ofl/msmadi |
| `Yellowtail-Regular.ttf` | Apache 2.0 | `licenses/yellowtail-LICENSE.txt` | https://github.com/google/fonts/tree/main/apache/yellowtail |

## 2. Bundled data

- `workbench-core/templates/ral_classic.json`: approximate sRGB renderings of the public RAL Classic colour
  names/codes, used only to name colours. "RAL" is a trademark of RAL gGmbH; values are approximations, not
  official colour references.
- `workbench-topo/tests/data/*.xml`: a small OpenStreetMap extract used as a test fixture.
  © OpenStreetMap contributors, available under the Open Database License (ODbL 1.0), <https://www.openstreetmap.org/copyright>.
- Named colours in `colorlib` come from matplotlib's XKCD (CC0) and CSS4 tables at run time (not copied).

## 3. Python dependencies (installed by `install.sh`, not bundled)

Pinned in `requirements.lock`; each keeps its own license, e.g. FastAPI (MIT), Uvicorn (BSD-3), Pydantic (MIT),
MCP Python SDK (MIT), trimesh (MIT), manifold3d (Apache-2.0), Shapely (BSD-3), NumPy/SciPy (BSD-3),
fontTools (MIT), uharfbuzz (Apache-2.0; HarfBuzz is "Old MIT"), OpenCV headless (Apache-2.0), potracer (GPL-2.0+,
see note), svgelements (MIT), Pillow (MIT-CMU), matplotlib (PSF-based), ReportLab (BSD), rasterio (BSD-3, uses GDAL
MIT/X), segno (BSD-3), networkx (BSD-3), lxml (BSD-3), rtree (MIT), fast-simplification (MIT), PyYAML (MIT).

Note on **potracer**: it is a pure-Python port of Potrace and is licensed GPL-2.0-or-later. It is an optional
runtime dependency (logo/bitmap tracing) installed from PyPI into your environment; no potracer code is
included in this repository. If you redistribute a bundled build (e.g. a frozen binary) that contains it, the GPL
terms apply to that bundle.

## 4. External tools and services (not bundled, optional)

| Tool / service | Used for | License / terms |
|---|---|---|
| OrcaSlicer | slicing / print-path check (`studio kontrol`, `--slice`, `print_check`) | AGPL-3.0; installed separately, called as an external program |
| Blender | not required by Studio; optional for your own renders | GPL-2.0+ |
| OpenSCAD + BOSL2 | not required by Studio; optional for hand-written parametric models | GPL-2.0 / BSD-2-Clause |
| build123d | not required by Studio; optional CAD alternative | Apache-2.0 |
| OpenStreetMap Nominatim / Overpass API | Topo place search and map data | ODbL data; follow each service's usage policy (identify your client, low request rate) |
| Copernicus DEM GLO-30 / GLO-90 (AWS open data) | Topo terrain elevation | © DLR e.V. 2010-2014 and © Airbus 2014-2018, provided under COPERNICUS by the European Union and ESA |

Maps produced by Topo carry the required attribution text in their job summary; keep it when you publish or sell
a map.

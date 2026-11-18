# 3D Printer Open Workbench — Studio

> 3D Printer Open Workbench: [Bot + agents](https://github.com/3d-printer-open-workbench/3d-printer-open-workbench-bot) · [ERP](https://github.com/3d-printer-open-workbench/3d-printer-open-workbench-erp) · **Studio**

**Open Workbench Studio** is a self-hosted, parametric 3D model generator for FDM printers. One local web app
(FastAPI, port 7870) and one MCP server turn a few form fields into print-ready, multi-colour `model.3mf` files
for OrcaSlicer — plus STL parts, renders, a 1:1 mounting template, cost/time estimates and an AI image prompt.

Türkçe: [README.tr.md](README.tr.md) · Install: [docs/install.md](docs/install.md) · Generators and job format:
[docs/generators.md](docs/generators.md)

> The user interface is currently in **Turkish** (code, comments and docs are English). Translations are welcome.

## What it makes

| Program | What it generates | Typical products |
|---|---|---|
| **Kaligraf** | Lettering and name signs: a flat 2.5D sign (`mode: flat`) or free-standing 3D box letters (`mode: letters`). Real kerning and Turkish/Latin diacritics via HarfBuzz, 36 bundled open fonts, thin-stroke checks, automatic split into printable pieces (with jigsaw locks for script words) when larger than the bed, keyhole / tape / screw mounting, 1:1 wall template PDF. | wall lettering, shop signs, name signs, logo signs |
| **Glow** | LED light boxes: rectangular, round or logo-contour ("neon") boxes with a diffuser face, LED channel, cable path and back cover. Picks LED strip / controller / diffuser from an editable hardware library, checks the USB power budget, writes an assembly guide PDF and a bill of materials. | light-up name signs, logo light boxes, heart lamps |
| **Maker** | 19 parametric generators: keychains (optional hidden NFC slot), QR plaques (Wi-Fi, review link, WhatsApp, social, URL, phone), pet tags, cookie cutters + stamps, letter stamps, grid cutters, pattern rollers, cake toppers, containers / pen holders / boxes, photo frames and stands, snowflake and lithophane ornaments, string-art boards, rattan letters, colouring plaques, bowls / vases (lathe forms), desk name plates, thermoform molds and calibration coupons. | organisers, gifts, kitchen tools, personalised items |
| **Topo** | Terrain and route maps from open data: a route (GPX or OSM relation) raised on real terrain with a distance/elevation profile, city topography with buildings and roads, a "memory" map with a heart marker, or pure terrain. Multi-colour tiles, themes, captions. | hiking route maps, city maps, gift maps |

Every job writes a folder with `model.3mf` (one object per colour, ready for a multi-material unit or manual
filament changes), `parts/*.stl`, renders (`*.png`), `job.json` (sizes, colours with HEX/RAL names, grams, print
time estimate) and program-specific extras.

## Screenshots

_Screenshots coming soon._ Contributions welcome — please add them under `docs/screenshots/`:

- `docs/screenshots/home.png` — product picker
- `docs/screenshots/editor.png` — numbered steps, live 3D preview, filament strip
- `docs/screenshots/outputs.png` — a finished job folder

## Quick start

```sh
git clone <this repository> workbench-studio && cd workbench-studio
./install.sh          # creates .venv, installs everything, adds the `studio` command
studio ui             # http://127.0.0.1:7870  (MCP: http://127.0.0.1:7870/mcp/)
```

Other commands:

```sh
studio open                      # start in the background and open the browser
studio list                      # every product
studio make workbench-maker/examples/kalemlik.yaml        # build any program's job file
studio make job.yaml --slice     # Maker: also slice with OrcaSlicer
studio kontrol <job folder>      # slice a finished job with OrcaSlicer and report print-path quality
studio stop
```

Requirements: Ubuntu 22.04+ (or any Linux with Python 3.11+) and [`uv`](https://docs.astral.sh/uv/). Optional:
OrcaSlicer for slicing / print checks. See [docs/install.md](docs/install.md).

## MCP tools (for Claude and other agents)

The Studio server exposes one Streamable-HTTP MCP endpoint at `http://127.0.0.1:7870/mcp/`. Add it to Claude Code:

```sh
claude mcp add --transport http workbench-studio http://127.0.0.1:7870/mcp/
```

| Tool | What it does |
|---|---|
| `make` | Build any product from a job dict (Maker `generator`, Kaligraf `mode: flat/letters`, Glow `design`, Topo map `mode`) |
| `maker_list_generators` | All generators incl. the Kaligraf and Glow variants (key, label, group, description) |
| `maker_generator_params` | Parameter schema of one generator (types, ranges, defaults, choices) |
| `maker_list_sheets` | Thermoform sheet table |
| `topo_list_modes`, `topo_find_place`, `topo_find_route` | Map modes and themes, place search (Nominatim), route search (OSM) |
| `job_summary` | Describe a finished job: real size, colours (HEX / RAL / name), parts, grams, time, renders |
| `print_check` | Slice with OrcaSlicer and report print-path problems (needs OrcaSlicer) |
| `color_info` | HEX → RGB / CIELAB / nearest RAL / English name |
| `save_prompt` | Save an AI image prompt next to a job |

Typical agent flow: `maker_list_generators` → `maker_generator_params(key)` → `make(job)` → `job_summary(dir)` →
`print_check(dir)`.

## Works with the other Open Workbench projects (optional)

Studio runs fine on its own. It also pairs with:

- **`3d-printer-open-workbench-bot`** — a Telegram bot where you order a model in plain words; a Claude agent
  calls this Studio over MCP (`make`, `job_summary`, `print_check`) and the bot sends back the preview and the 3MF.
  The bot expects Studio at `http://127.0.0.1:7870`.
- **`3d-printer-open-workbench-erp`** — costing, BOM, stock and quotes. If `WORKBENCH_ERP_URL` is set, the colour
  card page (`/kartela`) also pushes calibrated filament colours to the ERP. To share one filament palette with the
  bot, point `WORKBENCH_PALETTE` (or `WORKBENCH_CONFIG`) at the same `renk_paleti.yaml`.
- **Reels calendar (`/reels`)** — the bot's trend Reels ideas (script, shooting instructions, status, notes) in one
  page; "revise" / "new ideas" requests are queued for the bot's Claude agent. It reads the bot's data folder:
  `WORKBENCH_REELS_DIR`, else `$WORKBENCH_DATA/03_Magaza/reels_takvimi`, else
  `$WORKBENCH_ROOT/veri/03_Magaza/reels_takvimi`, else `$STUDIO_HOME/reels_takvimi`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `STUDIO_PORT` | `7870` | web UI / MCP port |
| `STUDIO_HOME` | `~/.local/share/workbench-studio` | state (pid file, log, default palette) |
| `STUDIO_WORK_DIR` | `~/.local/share/workbench-studio/output` | where jobs are written (`<Program>/output/<job>`) |
| `WORKBENCH_ORCA` | `orcaslicer` on `PATH` | OrcaSlicer executable (AppImage, AppRun or a wrapper script) |
| `WORKBENCH_SLICE_DIR` | `~/.cache/workbench-studio/slice` | scratch folder for slicing (inside `$HOME` so a flatpak/snap OrcaSlicer can read it) |
| `WORKBENCH_FONTS_DIR` | bundled `workbench-core/fonts` | font catalogue folder |
| `WORKBENCH_PALETTE` | `$WORKBENCH_CONFIG/renk_paleti.yaml`, else `$STUDIO_HOME/renk_paleti.yaml` | your filament palette (see `examples/palette.example.yaml`) |
| `WORKBENCH_ERP_URL` | unset (no sync) | optional ERP base URL for colour sync |
| `TOPO_CACHE` | `~/.cache/workbench-topo` | map data cache (repeated jobs work offline) |
| `TOPO_USER_AGENT` | generic | User-Agent for OpenStreetMap services — set it to identify your install, as their usage policies ask |
| `MAKER_COSTS`, `MAKER_SHEETS`, `GLOW_HARDWARE` | `~/.config/workbench-*/…` | your prices, thermoform sheets, LED hardware (the bundled values are assumptions) |

Printer defaults (bed 250 × 250 mm, up to 4 filaments, OrcaSlicer project template) live in
`workbench-core/printer.yaml` and `workbench-core/templates/orca_project_settings.json`; edit them for your printer.

## Repository layout

| Folder | Contents |
|---|---|
| `workbench-core/` | shared engine: fonts, text and logo outlines, geometry, 3MF export, renders, PDFs, estimates, colours, slicer bridge |
| `workbench-kaligraf/` | lettering and signs |
| `workbench-glow/` | LED light boxes |
| `workbench-maker/` | parametric generators |
| `workbench-topo/` | 3D maps |
| `src/studio/` | the web UI, CLI and unified MCP server |
| `tests/` | Studio tests (each program also has its own `tests/`) |
| `deploy/` | systemd user unit |

Python import names: `workbench_core`, `kaligraf`, `glow`, `maker`, `topo`, `studio`.

## Tests

```sh
for d in workbench-core workbench-kaligraf workbench-maker workbench-topo; do (cd $d && ../.venv/bin/python -m pytest -q); done
.venv/bin/python -m pytest -q tests
```

Tests that need OrcaSlicer are skipped when it is not installed.

## Safety

Studio only generates files. It never talks to a printer and never starts a print.

## License

MIT — see [LICENSE](LICENSE). Bundled fonts are SIL OFL 1.1 / Apache 2.0; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Roadmap: [ROADMAP.md](ROADMAP.md).

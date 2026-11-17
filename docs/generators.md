# Generators and job format

Every product is built from a **job** — a YAML file (`studio make job.yaml`) or a dict (MCP `make(job)`). The
program is recognised from the job itself:

| Program | Key field | Builds | Extra outputs |
|---|---|---|---|
| Kaligraf | `mode: flat` (or `generator: kaligraf_flat`) | 2.5D wall sign / lettering, one STL per letter | `parts/letter_XX_*.stl`, 1:1 `template.pdf`, renders, `dims.png` |
| Kaligraf | `mode: letters` (or `generator: kaligraf_letters`) | free-standing 3D letters, `depth_mm` 2-250 | as above; jigsaw-locked pieces for joined script |
| Glow | `design: rect` / `round` / `contour` | LED light box | `model.3mf`, `parts/*.stl`, `assembly_tr.pdf`, `bom.csv` |
| Maker | `generator: <key>` + `params: {...}` | parametric products (below) | `model.3mf` / STL, renders, summary |
| Topo | `mode: rota` / `sehir` / `ani` / `arazi` | 3D relief map | multi-colour `model.3mf`, renders, attribution |

Discover parameters at run time with the MCP tools `maker_list_generators` and `maker_generator_params(key)` (they
return types, ranges, defaults, choices and the Turkish UI labels), or open the product in the web UI.

## Kaligraf (signs and letters)

```yaml
mode: flat              # or: letters
text: "Corner Cafe"
font: Montserrat        # any name from workbench-core/fonts/fonts.yaml
width_cm: 40            # letters: letter_height_cm, depth_mm, letter_width_mm
thickness_mm: 5
color_style: two_tone   # single | two_tone | backplate
colors: [siyah, beyaz]  # names or HEX
mounting: [tape]        # tape | keyhole | holes | bar
oversize_policy: split  # split into pinned pieces, or: limit (scale down to fit the bed)
```

Useful extras: `split_letters` (one STL per letter, default on), `stroke_offset_mm` (-1.5..+5, thicker or thinner
strokes), `logo` (SVG / PNG path), `finishes` (render-only surface: matte, glossy, silk, wood, marble, glitter).
Full field list: `workbench-kaligraf/src/kaligraf/job.py`.

## Glow (LED light boxes)

```yaml
design: rect            # rect | round | contour
text: "OPEN"
font: Montserrat
width_mm: 300
depth_mm: 45
mount: wall             # wall | stand
```

LED strip, controller and diffuser are chosen from `workbench-glow/src/glow/hardware.yaml` (override:
`~/.config/workbench-glow/hardware.yaml`). Examples: `workbench-glow/examples/`.

## Maker generators

```yaml
generator: keychain
name: keychain_alex
params:
  style: name
  text: Alex
  font: Righteous
  nfc: true
  count: 4
```

| Key | What it makes | Parameters |
|---|---|---|
| `thermoform` | Thermoform mold (press male + female or vacuum, 1-9 cavities, raised text / logo on the dome, back plate and edge options) | `method`, `formed`, `sheet`, `mesh_halves`, `mesh_pattern`, `mesh_cell`, `mesh_strand`, `mesh_t`, `mesh_color`, `hose_d`, `source`, `shape`, `text`, `font`, `logo`, `width_mm`, `profile`, `depth_mm`, `steps`, `draft_deg`, `relief`, `relief_text`, `relief_font`, `relief_logo`, `relief_pct`, `relief_mm`, `relief_dir`, `closure`, `magnet_d`, `magnet_h`, `flange_mm`, `hanger`, `back_color`, `rim_color`, `back_colors`, `back_color_from_logo`, `back_holes`, `hole_d`, `hole_pitch`, `economy`, `cavities` |
| `thermo_coupon` | Calibration coupon: a small press mold with 2-5 male parts of different clearance, to measure the best fit for your sheet | `sheet`, `clear_min`, `clear_step`, `count`, `draft_deg` |
| `keychain` | Name, shape or logo keychain: coloured top layer, rim, side or top ring, optional hidden NFC slot | `style`, `text`, `font`, `shape`, `logo`, `logo_colors`, `width_mm`, `text_pct`, `border_mm`, `rim`, `base_color`, `text_color`, `base_mm`, `relief_mm`, `ring`, `hole_mm`, `nfc`, `nfc_d`, `nfc_t`, `count` |
| `qr_plaque` | QR plaque for Wi-Fi, review link, WhatsApp, Instagram / TikTok, web, phone; title, caption, icon; screw, magnet or desk stand | `kind`, `ssid`, `password`, `security`, `hidden`, `show_password`, `link`, `phone`, `message`, `user`, `text`, `ecc`, `title`, `caption`, `icon`, `font`, `title_mm`, `caption_mm`, `width_mm`, `corner_mm`, `base_mm`, `relief_mm`, `base_color`, `qr_color`, `text_color`, `mount`, `stand_color`, `magnet_d`, `magnet_t`, `count` |
| `pet_tag` | Pet tag (bone, circle, heart, hexagon, shield): raised name on the front, phone on the front or engraved on the back | `shape`, `width_mm`, `name`, `font`, `phone`, `phone_side`, `back_text`, `phone_font`, `base_color`, `text_color`, `material`, `base_mm`, `relief_mm`, `hole_mm`, `count` |
| `cookie_cutter` | Cookie cutter from a shape, text or logo, with an optional mirrored stamp and handle / pusher | `source`, `shape`, `text`, `font`, `logo`, `width_mm`, `height_mm`, `wall_mm`, `flange_mm`, `stamp`, `stamp_text`, `stamp_font`, `stamp_logo`, `stamp_pct`, `relief_mm`, `handle`, `material`, `cutter_color`, `stamp_color`, `count` |
| `letter_stamp` | Mirrored text stamp for cookies, fondant or clay: 1-2 lines, balloon or rectangle base, handle | `text`, `font`, `letter_mm`, `plate`, `margin_mm`, `plate_mm`, `relief_mm`, `material`, `color`, `count` |
| `grid_cutter` | Grid cutter for many cookies / crackers at once: square, hexagon or round cells | `cell`, `size_mm`, `rows`, `cols`, `height_mm`, `wall_mm`, `flange_mm`, `material`, `color`, `count` |
| `roller` | Pattern roller sleeve for a rolling pin: repeating text, hearts, stars, dots, diamonds, waves or a logo | `pattern`, `text`, `font`, `logo`, `size_mm`, `line_mm`, `relief_mm`, `bore_mm`, `wall_mm`, `length_mm`, `material`, `color`, `count` |
| `cake_topper` | Script cake topper: 1-2 lines, two-colour outline base or plain joined script, heart / star accents, stakes | `text`, `font`, `width_mm`, `accent`, `style`, `border_mm`, `thick_mm`, `relief_mm`, `stake_mm`, `material`, `base_color`, `text_color`, `count` |
| `container` | Pen holder, lidded box or divided sticker box: name around round shapes, engraved or two-colour lid text | `shape`, `width_mm`, `height_mm`, `wall_mm`, `bottom_mm`, `rows`, `cols`, `divider_mm`, `side_text`, `font`, `side_mm`, `side_pos`, `side_relief`, `lid`, `lip_mm`, `clear_mm`, `lid_text`, `lid_text_style`, `material`, `color`, `lid_color`, `text_color`, `count` |
| `photo_stand` | Slide-in photo frame (caption, desk stand) or a photo / card stand with text | `kind`, `size`, `landscape`, `border_mm`, `back`, `caption`, `font`, `caption_mm`, `relief_mm`, `color`, `text_color`, `stand_color`, `count` |
| `ornament` | Snowflake ornament (each seed different, year or name in the middle) or a lithophane ornament from a photo | `kind`, `size_mm`, `seed`, `arm_mm`, `thick_mm`, `text`, `font`, `text_color`, `photo`, `shape`, `t_min`, `t_max`, `gamma`, `color`, `count` |
| `string_art` | String-art board around a heart, star, name or logo, with printed pegs or nail holes | `source`, `shape`, `text`, `font`, `logo`, `width_mm`, `pitch_mm`, `pegs`, `peg_mm`, `nail_mm`, `board`, `margin_mm`, `board_mm`, `hanger`, `board_color`, `peg_color`, `count` |
| `rattan_letters` | Decorative letters with a rattan (woven hexagon) infill and a thick rim; each letter printed separately | `text`, `font`, `height_mm`, `rim_mm`, `cell_mm`, `strand_mm`, `thick_mm`, `rim_h_mm`, `rim_color`, `lattice_color`, `count` |
| `coloring_plaque` | Colouring plaque for kids: raised outline of a shape, name letters or the regions of an uploaded drawing | `picture`, `shape`, `image`, `regions`, `name`, `font`, `width_mm`, `margin_mm`, `line_mm`, `wall_mm`, `plate_mm`, `hanger`, `color`, `count` |
| `vessel` | Bowl / vase lathe forms (chawan, donburi, hira, tsubo, tsutsu): foot ring, fluting, twist, faceted or wave surface | `form`, `diameter_mm`, `height_mm`, `wall_mm`, `base_mm`, `foot`, `foot_h`, `foot_pct`, `surface`, `ribs`, `rib_mm`, `twist_deg`, `color` |
| `nameplate` | Desk name plate: two-colour raised name, optional title line and rim, separately printed sloped stand | `text`, `title`, `font`, `title_font`, `width_mm`, `height_mm`, `corner_mm`, `rim`, `base_color`, `text_color`, `base_mm`, `relief_mm`, `stand`, `stand_color`, `count` |
| `plate` | Shape plate with raised text (a minimal generator for testing the pipeline) | `shape`, `width_mm`, `thickness_mm`, `color`, `text`, `font`, `text_pct`, `relief_mm`, `text_color` |

Examples for most generators: `workbench-maker/examples/*.yaml`.

## Topo (maps)

| Mode | Area source | Themes |
|---|---|---|
| `rota` | GPX file or OSM route (`topo_find_route`) | Likya, Orman, Alpin, Taş, Gece |
| `sehir` | place (`topo_find_place`) | Klasik, Gri, Doğa, Ahşap, Gece, Beyaz |
| `ani` | place | Romantik, Minimal, Altın |
| `arazi` | place | Yeşil dağlar, Kar ve göl, Kum ve deniz |

```yaml
mode: rota
gpx: workbench-topo/examples/ornek_rota.gpx
size_mm: 200
```

Run `topo_list_modes` for layers and options; examples in `workbench-topo/examples/`.

## Helper tools

- `job_summary(job_dir)` — real size, colours (HEX / RAL / name), parts, grams, time, renders of any finished job.
- `print_check(job_dir)` — slices with OrcaSlicer and reports print-path problems (thin walls, tiny islands,
  unsupported areas). Needs OrcaSlicer (`WORKBENCH_ORCA`).
- `color_info(hex)`, `maker_list_sheets()`, `save_prompt(job_dir, prompt_tr, prompt_en)`.

## Adding a generator

1. Create `workbench-maker/src/maker/generators/<key>.py` with a `Generator` subclass (see `plate.py` for the
   smallest one): declare `Param`s (key, label, type, default, range, section, `show_if`) and implement `build()`
   returning plates of parts.
2. Register it in `generators/__init__.py`, add `examples/<key>.yaml` and a test.
3. The web form, `maker_list_generators` and `maker_generator_params` pick it up automatically.

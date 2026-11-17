# workbench-kaligraf

Lettering and signs. Two modes:

- `mode: flat` — a 2.5D wall sign (width in cm), single colour, two-tone or with a backplate;
- `mode: letters` — free-standing 3D letters (cap height in cm, depth in mm), each letter its own part.

Features: HarfBuzz shaping and kerning (Turkish and other Latin diacritics), thin-stroke checks per font with a
recommended minimum size, logos (SVG / PNG traced), oversize policy `split` (pinned pieces, jigsaw locks for joined
script words) or `limit`, mounting (`tape`, hidden `keyhole`, screw `holes`, connecting bar), 1:1 wall template PDF
split into A4 pages, front / 3/4 renders, dimension image, AI image prompt (TR / EN).

Run a job: `studio make examples/sample_flat.yaml` (or `../.venv/bin/python -m kaligraf.cli make job.yaml`). Job
fields: the `Job` class in `src/kaligraf/job.py`. Fonts are shared from `workbench-core/fonts` (symlink);
`scripts/fetch_fonts.sh` re-downloads them from Google Fonts, `scripts/font_report.py` rebuilds `fonts/REPORT.md` and
`fonts/metrics.json`.

`src/kaligraf/<module>.py` files such as `text2d.py` are aliases of `workbench_core.<module>`.

Tests: `../.venv/bin/python -m pytest -q` (the OrcaSlicer integration test is skipped unless OrcaSlicer is found via
`WORKBENCH_ORCA` or on `PATH`).

# workbench-core

Shared engine of Open Workbench Studio: font catalogue (`fonts/`, 36 OFL / Apache-2.0 fonts with their licenses),
HarfBuzz text and logo outlines, geometry and bed splitting with jigsaw joints, OrcaSlicer-ready 3MF export, headless
renders, PDF templates, gram / time estimates, colour naming (HEX / RAL / English), AI prompt helpers and the slicer
bridge (`print_check`).

Used by Kaligraf, Glow, Maker, Topo and the Studio app. Python import name: `workbench_core`.

Printer settings: `printer.yaml` (time model) and `templates/orca_project_settings.json` (OrcaSlicer project template,
bed size, filament slots). Edit them for your printer.

Tests (from this folder, using the repository `.venv`): `../.venv/bin/python -m pytest -q`

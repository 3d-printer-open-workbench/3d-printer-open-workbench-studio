# workbench-maker

Parametric generators. Each generator is one module in `src/maker/generators/` that declares its parameters (form
schema, ranges, defaults) and builds plates of parts; Studio renders the form and the MCP tool
`maker_generator_params(key)` exposes the same schema to agents.

Generators: `keychain`, `qr_plaque`, `pet_tag`, `cookie_cutter`, `letter_stamp`, `grid_cutter`, `roller`,
`cake_topper`, `container`, `photo_stand`, `ornament`, `string_art`, `rattan_letters`, `coloring_plaque`, `vessel`,
`nameplate`, `thermoform`, `thermo_coupon`, `plate`. See `../docs/generators.md`.

Examples: `examples/*.yaml` (`studio make workbench-maker/examples/kalemlik.yaml`, add `--slice` to slice with
OrcaSlicer). Cost table and thermoform sheets are assumptions: override with `~/.config/workbench-maker/costs.yaml`
(`$MAKER_COSTS`) and `~/.config/workbench-maker/sheets.yaml` (`$MAKER_SHEETS`).

Generators import the engine only through `src/maker/core.py`.

Tests: `../.venv/bin/python -m pytest -q`

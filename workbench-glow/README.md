# workbench-glow

LED light boxes: `design: rect`, `round` or `contour` (logo / text outline, "neon" style). Generates the frame,
diffuser face, LED channel with the strip path, controller pocket, cable exit, back cover and mounting (wall or stand),
checks the power budget against the USB supply, and writes an assembly guide PDF and a bill of materials (`bom.csv`).

Hardware library: `src/glow/hardware.yaml` (LED strips, controllers, diffusers). The bundled values are generic
assumptions — measure your own parts and save your version from the Studio "Donanım" page or to
`~/.config/workbench-glow/hardware.yaml` (`$GLOW_HARDWARE`).

Run an example: `studio make workbench-glow/examples/rect_sample.yaml`.

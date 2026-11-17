# Installing Open Workbench Studio (clean Ubuntu)

Tested on Ubuntu 24.04 (x86_64). Ubuntu 22.04+ and Debian 12+ work the same way. No root is needed for Studio itself;
`sudo` is only used for a few system packages.

## 1. System packages

```sh
sudo apt update
sudo apt install -y git curl ca-certificates xdg-utils libgl1 libglib2.0-0 libgomp1
```

- `libgl1`, `libglib2.0-0`, `libgomp1`: runtime libraries used by OpenCV, manifold3d and the mesh tools.
- Renders are pure software (no GPU / EGL needed), so a headless server works too.
- Optional for OrcaSlicer on a headless machine: `sudo apt install -y xvfb`.

## 2. uv (Python manager)

Studio uses [uv](https://docs.astral.sh/uv/) to fetch its own Python 3.13 — the system Python version does not matter.

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env        # or open a new terminal
uv --version
```

## 3. Get the code and install

```sh
git clone <repository URL> ~/workbench-studio
cd ~/workbench-studio
./install.sh
```

`install.sh` is idempotent — run it again after every `git pull`. It:

1. installs Python 3.13 with uv and creates `.venv/` inside the repository;
2. installs the pinned dependencies from `requirements.lock` and the six local packages in editable mode;
3. creates `~/.local/share/workbench-studio/` (state, palette) and `…/output/` (jobs), copies an example filament
   palette if you have none;
4. writes the `~/.local/bin/studio` launcher and an application-menu entry ("Open Workbench Studio");
5. runs the Studio test-suite.

Options: `--no-tests`, `--no-desktop`, `--systemd` (see step 5). Environment overrides: `PYTHON_VERSION`,
`BIN_DIR`, `STUDIO_HOME`, `STUDIO_WORK_DIR`.

If `studio` is "command not found", add `~/.local/bin` to your `PATH` (Ubuntu does this automatically at the next
login once the folder exists).

## 4. Run

```sh
studio ui              # foreground; open http://127.0.0.1:7870
studio open            # background + browser; `studio stop` to quit
studio list            # all products
studio make workbench-maker/examples/kalemlik.yaml
```

The web UI loads three.js and two web fonts from public CDNs (unpkg.com, fonts.googleapis.com) for the 3D preview,
so the browser needs internet access on first load. Everything else runs locally.

Jobs are written to `~/.local/share/workbench-studio/output/<Program>/output/<job>/` unless you set
`STUDIO_WORK_DIR`.

### Connect Claude (MCP)

```sh
claude mcp add --transport http workbench-studio http://127.0.0.1:7870/mcp/
```

Or in a project `.mcp.json`:

```json
{ "mcpServers": { "workbench-studio": { "type": "http", "url": "http://127.0.0.1:7870/mcp/" } } }
```

## 5. Run as a service (systemd user unit)

```sh
./install.sh --systemd --no-tests
# equivalent manual steps:
#   sed -e "s|@REPO@|$PWD|g" -e "s|@STATE@|$HOME/.local/share/workbench-studio|g" \
#       -e "s|@WORK@|$HOME/.local/share/workbench-studio/output|g" deploy/workbench-studio.service \
#       > ~/.config/systemd/user/workbench-studio.service
#   systemctl --user daemon-reload && systemctl --user enable --now workbench-studio.service
systemctl --user status workbench-studio
journalctl --user -u workbench-studio -f
```

To keep it running after you log out: `sudo loginctl enable-linger "$USER"`.
Extra settings (OrcaSlicer path, ERP URL, Topo User-Agent) go into `~/.config/workbench-studio.env`, one
`NAME=value` per line, then `systemctl --user restart workbench-studio`.

Studio listens on `127.0.0.1` only. Do not expose port 7870 to the internet: the API has no authentication. Use an
SSH tunnel (`ssh -L 7870:127.0.0.1:7870 host`) for remote access.

## 6. OrcaSlicer (optional)

Needed only for `studio make … --slice`, `studio kontrol`, the MCP `print_check` tool and the Orca integration
tests. Without it Studio still produces `model.3mf` files that you open in OrcaSlicer yourself.

Install one of:

- **Flatpak** (simplest): `flatpak install flathub com.orcaslicer.OrcaSlicer`, then create a wrapper:
  ```sh
  printf '#!/bin/sh\nexec flatpak run com.orcaslicer.OrcaSlicer "$@"\n' > ~/.local/bin/orcaslicer
  chmod +x ~/.local/bin/orcaslicer
  ```
- **AppImage** from the OrcaSlicer GitHub releases: make it executable and either put it on `PATH` as
  `orcaslicer` or point Studio at it: `export WORKBENCH_ORCA=/opt/OrcaSlicer.AppImage` (for the service: in
  `~/.config/workbench-studio.env`). If AppImages need FUSE on your system: `sudo apt install -y libfuse2t64`
  (22.04: `libfuse2`), or extract it with `--appimage-extract` and use `squashfs-root/AppRun`.

Studio looks for `$WORKBENCH_ORCA`, then `orcaslicer` on `PATH`. Slicing happens in `~/.cache/workbench-studio/slice`
(override: `WORKBENCH_SLICE_DIR`) because flatpak / snap builds can only read files under `$HOME`.

Set your printer: edit `workbench-core/templates/orca_project_settings.json` (printer, process and filament presets,
bed size) and `workbench-core/printer.yaml` (time-estimate calibration). The defaults are for a 250 × 250 mm bed with
up to 4 filaments.

## 7. Update / uninstall

```sh
cd ~/workbench-studio && git pull && ./install.sh
```

Uninstall: `systemctl --user disable --now workbench-studio` (if used), then remove `~/.local/bin/studio`,
`~/.local/share/applications/workbench-studio.desktop`, `~/.local/share/icons/hicolor/scalable/apps/workbench-studio.svg`,
`~/.config/systemd/user/workbench-studio.service` and the repository folder. Your jobs and palette stay in
`~/.local/share/workbench-studio/` until you delete it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `uv was not found` | Install uv (step 2) and open a new terminal. |
| `studio: command not found` | `export PATH="$HOME/.local/bin:$PATH"` (add it to `~/.profile`). |
| `HATA: 7870 numaralı kapı kullanımda` (port in use) | Studio is already running (`studio stop`) or another program uses the port: `STUDIO_PORT=7871 studio ui`. |
| `ImportError: libGL.so.1` / `libgomp.so.1` | `sudo apt install -y libgl1 libglib2.0-0 libgomp1` |
| 3D preview stays empty | The browser could not load three.js from unpkg.com (offline / blocked). Files are still generated; open `model.3mf` in OrcaSlicer. |
| `OrcaSlicer bulunamadı` | Install OrcaSlicer (step 6) or set `WORKBENCH_ORCA`. |
| Orca says `No such file` for a model | A flatpak/snap OrcaSlicer cannot see `/tmp`; keep `WORKBENCH_SLICE_DIR` (and job output) under `$HOME`. |
| Orca crashes on a headless server | Install `xvfb`; the tests and slicer use `xvfb-run` when it is available. |
| Topo: place search / map download fails | Needs internet the first time (Nominatim, Overpass, Copernicus DEM on AWS). Set `TOPO_USER_AGENT` to identify yourself; respect the services' rate limits. Later runs use `~/.cache/workbench-topo`; `TOPO_OFFLINE=1` forces cache-only. |
| Colour pickers show only generic colours | Create your palette: copy `examples/palette.example.yaml` to `~/.local/share/workbench-studio/renk_paleti.yaml` or set `WORKBENCH_PALETTE`. |
| Service does not start | `journalctl --user -u workbench-studio -e`; check the paths in `~/.config/systemd/user/workbench-studio.service`. |
| Tests fail after `git pull` | Re-run `./install.sh` so `.venv` matches `requirements.lock`. |

# Open Workbench Studio kurulumu (temiz Ubuntu)

Ubuntu 24.04 (x86_64) üzerinde denendi; Ubuntu 22.04+ ve Debian 12+ aynı şekilde kurulur. Studio için root gerekmez;
`sudo` yalnızca birkaç sistem paketi için kullanılır.

## 1. Sistem paketleri

```sh
sudo apt update
sudo apt install -y git curl ca-certificates xdg-utils libgl1 libglib2.0-0 libgomp1
```

- `libgl1`, `libglib2.0-0`, `libgomp1`: OpenCV, manifold3d ve ağ (mesh) araçlarının çalışma kütüphaneleri.
- Görseller tamamen yazılımla çizilir (ekran kartı / EGL gerekmez); ekransız sunucuda da çalışır.
- Ekransız makinede OrcaSlicer için isteğe bağlı: `sudo apt install -y xvfb`.

## 2. uv (Python yöneticisi)

Studio kendi Python 3.13'ünü [uv](https://docs.astral.sh/uv/) ile indirir; sistemdeki Python sürümü önemli değildir.

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env        # ya da yeni bir terminal açın
uv --version
```

## 3. Kodu indirip kurun

```sh
git clone <depo adresi> ~/workbench-studio
cd ~/workbench-studio
./install.sh
```

`install.sh` tekrar tekrar çalıştırılabilir; her `git pull` sonrası yeniden çalıştırın. Yaptıkları:

1. uv ile Python 3.13'ü kurar, depo içinde `.venv/` oluşturur;
2. `requirements.lock` sürümlerini ve altı yerel paketi (düzenlenebilir kip) kurar;
3. `~/.local/share/workbench-studio/` (durum, palet) ve `…/output/` (işler) klasörlerini açar; paletiniz yoksa
   örnek filament paletini kopyalar;
4. `~/.local/bin/studio` komutunu ve uygulama menüsü girdisini ("Open Workbench Studio") yazar;
5. Studio testlerini çalıştırır.

Seçenekler: `--no-tests`, `--no-desktop`, `--systemd` (5. adım). Ortam değişkenleri: `PYTHON_VERSION`, `BIN_DIR`,
`STUDIO_HOME`, `STUDIO_WORK_DIR`.

`studio` komutu bulunamıyorsa `~/.local/bin` klasörünü `PATH`'e ekleyin (Ubuntu, klasör varsa bir sonraki oturumda
kendisi ekler).

## 4. Çalıştırma

```sh
studio ui              # ön planda; http://127.0.0.1:7870 adresini açın
studio open            # arka planda başlat + tarayıcı; kapatmak için `studio stop`
studio list            # bütün ürünler
studio make workbench-maker/examples/kalemlik.yaml
```

Web arayüzü 3B önizleme için three.js'i ve iki web yazı tipini herkese açık CDN'lerden (unpkg.com,
fonts.googleapis.com) yükler; tarayıcının ilk açılışta internete erişmesi gerekir. Geri kalan her şey yerelde çalışır.

İşler, `STUDIO_WORK_DIR` verilmezse `~/.local/share/workbench-studio/output/<Program>/output/<iş>/` altına yazılır.

### Claude'a bağlama (MCP)

```sh
claude mcp add --transport http workbench-studio http://127.0.0.1:7870/mcp/
```

## 5. Servis olarak çalıştırma (systemd kullanıcı birimi)

```sh
./install.sh --systemd --no-tests
systemctl --user status workbench-studio
journalctl --user -u workbench-studio -f
```

Oturum kapansa da çalışsın: `sudo loginctl enable-linger "$USER"`. Ek ayarlar (OrcaSlicer yolu, ERP adresi, Topo
kimliği) `~/.config/workbench-studio.env` dosyasına satır satır `AD=değer` olarak yazılır; ardından
`systemctl --user restart workbench-studio`.

Studio yalnızca `127.0.0.1` adresini dinler. 7870 numaralı kapıyı internete açmayın (API'de kimlik doğrulama yok);
uzaktan erişim için SSH tüneli kullanın: `ssh -L 7870:127.0.0.1:7870 sunucu`.

## 6. OrcaSlicer (isteğe bağlı)

Yalnızca `studio make … --slice`, `studio kontrol`, MCP `print_check` aracı ve Orca entegrasyon testleri için
gerekir. Olmadan da Studio `model.3mf` üretir; dosyayı OrcaSlicer'da kendiniz açarsınız.

- **Flatpak** (en kolayı): `flatpak install flathub com.orcaslicer.OrcaSlicer`, ardından bir sarmalayıcı yazın:
  ```sh
  printf '#!/bin/sh\nexec flatpak run com.orcaslicer.OrcaSlicer "$@"\n' > ~/.local/bin/orcaslicer
  chmod +x ~/.local/bin/orcaslicer
  ```
- **AppImage** (OrcaSlicer GitHub sürümleri): çalıştırılabilir yapın; `PATH`'e `orcaslicer` adıyla koyun ya da
  `export WORKBENCH_ORCA=/opt/OrcaSlicer.AppImage` verin (servis için `~/.config/workbench-studio.env`). FUSE
  gerekiyorsa: `sudo apt install -y libfuse2t64` (22.04: `libfuse2`) ya da `--appimage-extract` ile açıp
  `squashfs-root/AppRun` yolunu verin.

Studio önce `$WORKBENCH_ORCA`'ya, sonra `PATH`'teki `orcaslicer`'a bakar. Dilimleme `~/.cache/workbench-studio/slice`
içinde yapılır (`WORKBENCH_SLICE_DIR`), çünkü flatpak / snap sürümleri yalnızca `$HOME` altını görür.

Yazıcınızı tanıtın: `workbench-core/templates/orca_project_settings.json` (yazıcı, işlem ve filament ön ayarları, tabla
ölçüsü) ve `workbench-core/printer.yaml` (süre tahmini kalibrasyonu). Varsayılanlar 250 × 250 mm tabla ve en çok 4
filament içindir.

## 7. Güncelleme / kaldırma

```sh
cd ~/workbench-studio && git pull && ./install.sh
```

Kaldırma: (kullandıysanız) `systemctl --user disable --now workbench-studio`; ardından `~/.local/bin/studio`,
`~/.local/share/applications/workbench-studio.desktop`, `~/.local/share/icons/hicolor/scalable/apps/workbench-studio.svg`,
`~/.config/systemd/user/workbench-studio.service` ve depo klasörünü silin. İşleriniz ve paletiniz
`~/.local/share/workbench-studio/` altında, siz silene kadar kalır.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `uv was not found` | uv'yi kurun (2. adım), yeni terminal açın. |
| `studio: command not found` | `export PATH="$HOME/.local/bin:$PATH"` (kalıcı olması için `~/.profile`'a ekleyin). |
| `HATA: 7870 numaralı kapı kullanımda` | Studio zaten açık (`studio stop`) ya da kapıyı başka program kullanıyor: `STUDIO_PORT=7871 studio ui`. |
| `ImportError: libGL.so.1` / `libgomp.so.1` | `sudo apt install -y libgl1 libglib2.0-0 libgomp1` |
| 3B önizleme boş | Tarayıcı three.js'i unpkg.com'dan yükleyemedi (çevrimdışı / engelli). Dosyalar yine üretilir; `model.3mf`'yi OrcaSlicer'da açın. |
| `OrcaSlicer bulunamadı` | OrcaSlicer'ı kurun (6. adım) ya da `WORKBENCH_ORCA` verin. |
| Orca modeli için `No such file` diyor | flatpak/snap OrcaSlicer `/tmp`'yi göremez; `WORKBENCH_SLICE_DIR` ve iş çıktıları `$HOME` altında kalsın. |
| Ekransız sunucuda Orca çöküyor | `xvfb` kurun; testler ve dilimleyici varsa `xvfb-run` kullanır. |
| Topo: yer arama / harita indirme başarısız | İlk seferde internet gerekir (Nominatim, Overpass, AWS'teki Copernicus DEM). `TOPO_USER_AGENT` ile kendinizi tanıtın, servislerin hız sınırlarına uyun. Sonraki işler `~/.cache/workbench-topo` önbelleğini kullanır; `TOPO_OFFLINE=1` yalnız önbelleği kullanır. |
| Renk seçicilerde yalnız genel renkler var | Paletinizi oluşturun: `examples/palette.example.yaml` dosyasını `~/.local/share/workbench-studio/renk_paleti.yaml` olarak kopyalayın ya da `WORKBENCH_PALETTE` verin. |
| Servis başlamıyor | `journalctl --user -u workbench-studio -e`; `~/.config/systemd/user/workbench-studio.service` içindeki yolları denetleyin. |
| `git pull` sonrası testler kırılıyor | `.venv`'in `requirements.lock` ile eşleşmesi için `./install.sh`'ı yeniden çalıştırın. |

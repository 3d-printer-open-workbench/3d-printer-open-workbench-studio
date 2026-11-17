# 3D Printer Open Workbench — Studio

> 3D Printer Open Workbench ailesi: [Bot + ajanlar](https://github.com/3d-printer-open-workbench/3d-printer-open-workbench-bot) · [ERP](https://github.com/3d-printer-open-workbench/3d-printer-open-workbench-erp) · **Studio**

**Open Workbench Studio**, FDM yazıcılar için kendi bilgisayarınızda çalışan parametrik bir 3B model üretecidir.
Tek bir yerel web uygulaması (FastAPI, 7870 numaralı kapı) ve tek bir MCP sunucusu, birkaç form alanından
OrcaSlicer'a hazır, çok renkli `model.3mf` dosyaları üretir; yanında STL parçalar, görseller, 1:1 montaj şablonu,
maliyet/süre tahmini ve yapay zekâ görsel istemi de çıkar.

English: [README.md](README.md) · Kurulum: [docs/kurulum.md](docs/kurulum.md) · Üreteçler ve iş dosyası biçimi:
[docs/generators.md](docs/generators.md)

## Neler üretir?

| Program | Ne üretir | Örnek ürünler |
|---|---|---|
| **Kaligraf** | Yazı ve isim tabelaları: düz 2.5B tabela (`mode: flat`) ya da bağımsız 3B kutu harfler (`mode: letters`). HarfBuzz ile gerçek harf aralığı ve Türkçe karakterler, 36 açık lisanslı yazı tipi, ince çizgi kontrolü, tablaya sığmayan işlerde otomatik parçalama (el yazısında yapboz kilitli), anahtar deliği / bant / vida montajı, 1:1 duvar şablonu PDF'i. | duvar yazısı, işletme tabelası, isimlik, logo tabela |
| **Glow** | LED ışıklı kutular: dikdörtgen, yuvarlak ya da logo konturlu ("neon") kutu; difüzörlü yüz, LED kanalı, kablo yolu ve arka kapak. Düzenlenebilir donanım kütüphanesinden LED şerit / kontrolcü / difüzör seçer, USB güç bütçesini denetler, montaj kılavuzu PDF'i ve malzeme listesi yazar. | ışıklı isim, ışıklı logo, kalp lamba |
| **Maker** | 19 parametrik üreteç: anahtarlık (gizli NFC yuvası isteğe bağlı), QR plaket (WiFi, yorum bağlantısı, WhatsApp, sosyal medya, web, telefon), evcil hayvan künyesi, kurabiye kesici + damga, harf damgası, ızgara kesici, desenli merdane, pasta süsü, kap / kalemlik / kutu, fotoğraf çerçevesi ve standı, kar tanesi ve litofan süs, ip sanatı panosu, rattan harf, boyama plaketi, kase / vazo (döner form), masaüstü isimlik, termoform kalıbı ve kalibrasyon kuponu. | düzenleyici, hediyelik, mutfak gereci, kişiye özel ürün |
| **Topo** | Açık veriden arazi ve rota haritaları: gerçek arazi üzerinde yükseltilmiş rota (GPX ya da OSM) ve yükseklik profili, binalı ve yollu şehir topoğrafyası, kalp işaretli "anı" haritası ya da yalın arazi. Çok renkli karolar, temalar, alt yazı. | yürüyüş rotası haritası, şehir haritası, hediye harita |

Her iş bir klasör yazar: `model.3mf` (her renk ayrı nesne), `parts/*.stl`, görseller (`*.png`), `job.json`
(ölçüler, HEX/RAL adlı renkler, gram, süre tahmini) ve programa özgü ekler.

## Ekran görüntüleri

_Yakında._ Katkıya açık: `docs/screenshots/` altına `home.png`, `editor.png`, `outputs.png` ekleyebilirsiniz.

## Hızlı başlangıç

```sh
git clone <bu depo> workbench-studio && cd workbench-studio
./install.sh          # .venv oluşturur, her şeyi kurar, `studio` komutunu ekler
studio ui             # http://127.0.0.1:7870  (MCP: http://127.0.0.1:7870/mcp/)
```

Diğer komutlar:

```sh
studio open                      # arka planda başlat, tarayıcıyı aç
studio list                      # bütün ürünler
studio make workbench-maker/examples/kalemlik.yaml        # herhangi bir programın iş dosyasını üret
studio make is.yaml --slice      # Maker: OrcaSlicer ile dilimle
studio kontrol <iş klasörü>      # bitmiş işi OrcaSlicer'da dilimle, baskı yolu raporu çıkar
studio stop
```

Gereksinimler: Ubuntu 22.04+ (ya da Python 3.11+ olan bir Linux) ve [`uv`](https://docs.astral.sh/uv/).
İsteğe bağlı: dilimleme / baskı kontrolü için OrcaSlicer. Ayrıntı: [docs/kurulum.md](docs/kurulum.md).

## MCP araçları (Claude ve diğer ajanlar için)

Sunucu tek bir Streamable-HTTP MCP uç noktası sunar: `http://127.0.0.1:7870/mcp/`. Claude Code'a eklemek için:

```sh
claude mcp add --transport http workbench-studio http://127.0.0.1:7870/mcp/
```

| Araç | Ne yapar |
|---|---|
| `make` | İş sözlüğünden herhangi bir ürünü üretir (Maker `generator`, Kaligraf `mode: flat/letters`, Glow `design`, Topo harita `mode`) |
| `maker_list_generators` | Kaligraf ve Glow dahil bütün üreteçler |
| `maker_generator_params` | Bir üretecin parametre şeması (tür, aralık, varsayılan, seçenekler) |
| `maker_list_sheets` | Termoform levha tablosu |
| `topo_list_modes`, `topo_find_place`, `topo_find_route` | Harita modları ve temaları, yer arama (Nominatim), rota arama (OSM) |
| `job_summary` | Bitmiş işin özeti: gerçek ölçü, renkler (HEX / RAL / ad), parçalar, gram, süre, görseller |
| `print_check` | OrcaSlicer ile dilimleyip baskı yolu sorunlarını raporlar (OrcaSlicer gerekir) |
| `color_info` | HEX → RGB / CIELAB / en yakın RAL / İngilizce ad |
| `save_prompt` | İşin yanına yapay zekâ görsel istemi kaydeder |

## Diğer Open Workbench projeleriyle (isteğe bağlı)

Studio tek başına çalışır. Ayrıca:

- **`3d-printer-open-workbench-bot`** — Telegram botu: modeli düz cümleyle istersiniz, Claude ajanı bu Studio'yu MCP
  üzerinden kullanır (`make`, `job_summary`, `print_check`), bot önizlemeyi ve 3MF'i geri gönderir. Bot Studio'yu
  `http://127.0.0.1:7870` adresinde arar.
- **`3d-printer-open-workbench-erp`** — maliyet, ürün reçetesi, stok ve teklif. `WORKBENCH_ERP_URL` verilirse renk
  kartelası sayfası (`/kartela`) ayarlanan filament rengini ERP'ye de iletir. Botla aynı paleti kullanmak için
  `WORKBENCH_PALETTE` (ya da `WORKBENCH_CONFIG`) değişkenini aynı `renk_paleti.yaml` dosyasına yöneltin.

## Ayarlar

Tüm ortam değişkenleri ve varsayılanları için [README.md → Configuration](README.md#configuration) tablosuna bakın.
Başlıcaları: `STUDIO_PORT` (7870), `STUDIO_WORK_DIR` (iş çıktıları), `WORKBENCH_ORCA` (OrcaSlicer yolu),
`WORKBENCH_PALETTE` (filament paleti), `TOPO_USER_AGENT` (OpenStreetMap servisleri için kimlik).

Yazıcı varsayılanları (250 × 250 mm tabla, en çok 4 filament, OrcaSlicer proje şablonu)
`workbench-core/printer.yaml` ve `workbench-core/templates/orca_project_settings.json` içindedir; kendi yazıcınıza
göre düzenleyin.

## Testler

```sh
for d in workbench-core workbench-kaligraf workbench-maker workbench-topo; do (cd $d && ../.venv/bin/python -m pytest -q); done
.venv/bin/python -m pytest -q tests
```

OrcaSlicer gerektiren testler, OrcaSlicer kurulu değilse atlanır.

## Güvenlik

Studio yalnızca dosya üretir; yazıcıyla konuşmaz, baskı başlatmaz.

## Lisans

MIT — bkz. [LICENSE](LICENSE). Yazı tipleri SIL OFL 1.1 / Apache 2.0 lisanslıdır; bkz.
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Yol haritası: [ROADMAP.md](ROADMAP.md).

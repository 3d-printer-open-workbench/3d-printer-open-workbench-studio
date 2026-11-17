"""``assembly_tr.pdf``: Turkish step-by-step assembly guide (parts, LED cut list and path, jumpers, wiring, controller,
closing, mounting, power notes). Built with reportlab from a finished LightBox + its job.json data."""
from __future__ import annotations

import math
from pathlib import Path

from reportlab.lib import colors as rl
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Flowable, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from shapely.geometry import LineString
from shapely.ops import substring

FONT, FONT_B = "GlowSans", "GlowSans-Bold"
GREEN = rl.HexColor("#1F4D3A")
ORANGE = rl.HexColor("#E8761C")
GREY = rl.HexColor("#555555")
DESIGN_TR = {"rect": "Dikdörtgen kutu", "round": "Yuvarlak kutu", "contour": "Kontur kutu"}
MOUNT_TR = {"desk": "masa üstü (ayaklı)", "stand": "yuvalı stand", "wall": "duvara asma (anahtar deliği)"}
CTRL_MODE_TR = {"normal": "kutu içinde", "relaxed": "kutu içinde (sıkı yerleşim)", "smaller": "kutu içinde (daha küçük kontrolcü)",
                "external": "harici (kablo üzerinde, kutunun dışında)"}


def _fonts() -> None:
    if FONT in pdfmetrics.getRegisteredFontNames():
        return
    import matplotlib

    d = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    pdfmetrics.registerFont(TTFont(FONT, str(d / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_B, str(d / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_B, italic=FONT, boldItalic=FONT_B)


def _styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName=FONT, fontSize=9.5, leading=13.5, textColor=rl.HexColor("#222222"))
    return {
        "body": ParagraphStyle("body", **base),
        "small": ParagraphStyle("small", **{**base, "fontSize": 8, "leading": 10.5, "textColor": GREY}),
        "cell": ParagraphStyle("cell", **{**base, "fontSize": 8.5, "leading": 11}),
        "cellb": ParagraphStyle("cellb", **{**base, "fontSize": 8.5, "leading": 11, "fontName": FONT_B}),
        "h1": ParagraphStyle("h1", **{**base, "fontName": FONT_B, "fontSize": 20, "leading": 24, "textColor": GREEN, "spaceAfter": 4}),
        "h2": ParagraphStyle("h2", **{**base, "fontName": FONT_B, "fontSize": 13, "leading": 17, "textColor": GREEN, "spaceBefore": 10, "spaceAfter": 5}),
        "step": ParagraphStyle("step", **{**base, "leftIndent": 20, "firstLineIndent": -20, "spaceAfter": 5}),
        "warn": ParagraphStyle("warn", **{**base, "fontSize": 8.8, "leading": 12, "leftIndent": 12, "firstLineIndent": -12, "spaceAfter": 3}),
    }


def _p(text: str, st: ParagraphStyle) -> Paragraph:
    return Paragraph(text, st)


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------- #
# LED path drawing
# --------------------------------------------------------------------------- #
def chain_pieces(path) -> list[LineString]:
    """Physical strip pieces: one merged line when the rows are joined by U-turns, else one line per segment."""
    if path.joint == "bend":
        pts: list[tuple[float, float]] = []
        for i, s in enumerate(path.segments):
            pts += [c[:2] for c in s.line.coords]
            for j in path.joints:
                if j.type == "bend" and j.a == i:
                    pts += [c[:2] for c in j.line.coords]
        return [LineString(pts)]
    return [s.line for s in path.segments]


class PlanDrawing(Flowable):
    """Scaled plan of the back cover seen from inside: wall, bosses, controller, LED pieces with numbers, direction
    arrows and cut marks, jumpers (dashed)."""

    def __init__(self, box, width: float, max_height: float):
        super().__init__()
        self.box = box
        meta = box.model.meta
        o = meta["polys"]["outline"]
        self.bounds = o.bounds
        w, h = self.bounds[2] - self.bounds[0], self.bounds[3] - self.bounds[1]
        self.k = min(width / (w + 12), max_height / (h + 14))
        self.width = (w + 12) * self.k
        self.height = (h + 14) * self.k
        self.scale_text = f"Ölçek yaklaşık 1:{2.8346 / self.k:.1f} (arka kapağı içeriden görüyorsunuz)"

    def wrap(self, aw, ah):
        return self.width, self.height

    def _xy(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.bounds[0] + 6) * self.k, (y - self.bounds[1] + 7) * self.k

    def _poly(self, g, fill=None, stroke=None, lw=0.6, dash=None) -> None:
        c = self.canv
        for poly in getattr(g, "geoms", [g]):
            if poly.is_empty or poly.geom_type != "Polygon":
                continue
            p = c.beginPath()
            for ring in [poly.exterior, *poly.interiors]:
                pts = [self._xy(x, y) for x, y in ring.coords]
                p.moveTo(*pts[0])
                for q in pts[1:]:
                    p.lineTo(*q)
                p.close()
            if fill is not None:
                c.setFillColor(fill)
            if stroke is not None:
                c.setStrokeColor(stroke)
            c.setLineWidth(lw)
            c.setDash(*(dash or ([], 0)) if dash else ())
            c.drawPath(p, fill=1 if fill is not None else 0, stroke=1 if stroke is not None else 0, fillMode=0)
            c.setDash()

    def draw(self) -> None:
        c, box = self.canv, self.box
        meta = box.model.meta
        polys = meta["polys"]
        sw = {"ws2812b_5mm": 5.0, "ws2812b_10mm": 10.0, "cob_5mm": 5.0, "cob_8mm": 8.0}.get(meta["led"], 8.0)
        try:
            from .hardware import default_hardware

            sw = default_hardware().led(meta["led"]).width_mm
            pitch = default_hardware().led(meta["led"]).cut_pitch_mm
        except KeyError:
            pitch = 16.67
        self._poly(polys["outline"], fill=rl.HexColor("#F3F5F4"), stroke=GREEN, lw=1.4)
        self._poly(polys["inner"], fill=rl.white, stroke=GREEN, lw=0.6)
        self._poly(polys["boss_zone"], fill=rl.HexColor("#B9CFC1"), stroke=GREEN, lw=0.5)
        self._poly(polys["cradle"], fill=rl.HexColor("#CFE0F5"), stroke=rl.HexColor("#143A66"), lw=0.6)
        from .checks import box_ctrl

        self._poly(box_ctrl(meta), fill=rl.HexColor("#2F6DB5"), stroke=rl.HexColor("#143A66"), lw=0.6)
        pc = meta["controller_pocket"]["center"]
        c.setFillColor(rl.white)
        c.setFont(FONT, 6.5)
        x, y = self._xy(*pc)
        c.drawCentredString(x, y - 2, "kontrolcü" if meta.get("controller_mode") != "external" else "kablo çıkışı")
        for ln in box.path.strip_lines():
            self._poly(ln.buffer(sw / 2, cap_style="flat"), fill=ORANGE, stroke=rl.HexColor("#8A4300"), lw=0.5)
        # cut marks every cut pitch + direction arrows + numbers
        c.setStrokeColor(rl.HexColor("#5A2E00"))
        c.setLineWidth(0.5)
        for idx, ln in enumerate(chain_pieces(box.path)):
            d = 0.0
            while d <= ln.length + 1e-6:
                p0, p1 = ln.interpolate(max(d - 0.3, 0)), ln.interpolate(min(d + 0.3, ln.length))
                tx, ty = p1.x - p0.x, p1.y - p0.y
                n = math.hypot(tx, ty) or 1.0
                nx, ny = -ty / n, tx / n
                p = ln.interpolate(d)
                a, b = self._xy(p.x + nx * sw * 0.5, p.y + ny * sw * 0.5), self._xy(p.x - nx * sw * 0.5, p.y - ny * sw * 0.5)
                c.line(a[0], a[1], b[0], b[1])
                d += pitch
            # arrow at 40 % of the piece
            m = ln.interpolate(0.4 * ln.length)
            m2 = ln.interpolate(min(0.4 * ln.length + 4.0, ln.length))
            tx, ty = m2.x - m.x, m2.y - m.y
            n = math.hypot(tx, ty) or 1.0
            ux, uy = tx / n, ty / n
            tip = self._xy(m.x + ux * 3.5, m.y + uy * 3.5)
            l1 = self._xy(m.x - ux * 1.5 - uy * 2.6, m.y - uy * 1.5 + ux * 2.6)
            l2 = self._xy(m.x - ux * 1.5 + uy * 2.6, m.y - uy * 1.5 - ux * 2.6)
            c.setFillColor(rl.HexColor("#5A2E00"))
            p = c.beginPath()
            p.moveTo(*tip), p.lineTo(*l1), p.lineTo(*l2), p.close()
            c.drawPath(p, fill=1, stroke=0)
            # number at the start
            s0 = ln.interpolate(0)
            x, y = self._xy(s0.x, s0.y)
            c.setFillColor(rl.HexColor("#111111"))
            c.circle(x, y, 3.6, fill=1, stroke=0)
            c.setFillColor(rl.white)
            c.setFont(FONT_B, 6.5)
            c.drawCentredString(x, y - 2.2, str(idx + 1))
        c.setStrokeColor(rl.HexColor("#B35400"))
        c.setLineWidth(1.1)
        c.setDash(2, 2)
        for j in box.path.joints:
            if j.type == "jumper":
                a, b = self._xy(*j.line.coords[0][:2]), self._xy(*j.line.coords[-1][:2])
                c.line(a[0], a[1], b[0], b[1])
        c.setDash()
        csx, csy = meta["cable_slot"]
        x, y = self._xy(csx, csy)
        c.setFillColor(rl.HexColor("#222222"))
        c.rect(x - 3, y - 3, 6, 6, fill=1, stroke=0)
        c.setFont(FONT, 6.5)
        c.drawCentredString(x, y + 7, "USB çıkışı")


# --------------------------------------------------------------------------- #
# Content blocks
# --------------------------------------------------------------------------- #
def _table(rows: list[list], widths: list[float], header: bool = True, zebra: bool = True) -> Table:
    if header:
        rows = [[Paragraph(f'<font color="#FFFFFF">{c.text}</font>', c.style) if isinstance(c, Paragraph) else c for c in rows[0]], *rows[1:]]
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [("FONT", (0, 0), (-1, -1), FONT, 8.5), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("LINEBELOW", (0, 0), (-1, -1), 0.25, rl.HexColor("#CCCCCC")),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), GREEN), ("TEXTCOLOR", (0, 0), (-1, 0), rl.white), ("FONT", (0, 0), (-1, 0), FONT_B, 8.5)]
    if zebra:
        st += [("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [rl.white, rl.HexColor("#F4F7F5")])]
    t.setStyle(TableStyle(st))
    return t


def _swatch(hex_color: str) -> Table:
    t = Table([[""]], colWidths=[9 * mm], rowHeights=[5 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), rl.HexColor(hex_color)), ("BOX", (0, 0), (-1, -1), 0.4, rl.HexColor("#888888"))]))
    return t


def _img(path, width: float) -> Image:
    from PIL import Image as PILImage

    w, h = PILImage.open(path).size
    return Image(str(path), width=width, height=width * h / w)


def _fmt_dur(h: float) -> str:
    hh = int(h)
    mm_ = int(round((h - hh) * 60))
    return f"{hh} sa {mm_:02d} dk" if hh else f"{mm_} dk"


def led_rows(box, hw) -> tuple[list[list], dict]:
    """Cut-list rows (Turkish) and a summary dict."""
    meta = box.model.meta
    led = hw.led(meta["led"])
    path = box.path
    pitch = led.cut_pitch_mm
    per_unit = led.leds_per_m * pitch / 1000.0 if led.addressable else 0.0
    pieces = chain_pieces(path)
    rows = []
    if path.joint == "bend":
        ln = pieces[0]
        units = int(round(ln.length / pitch))
        rows.append([1, f"{ln.length:.0f}", units, f"{round(units * per_unit)}" if led.addressable else "-",
                     f"({ln.coords[0][0]:.0f}; {ln.coords[0][1]:.0f})", f"({ln.coords[-1][0]:.0f}; {ln.coords[-1][1]:.0f})"])
    else:
        for i, s in enumerate(path.segments):
            units = int(round(s.length_mm / pitch))
            rows.append([i + 1, f"{s.length_mm:.0f}", units, f"{round(units * per_unit)}" if led.addressable else "-",
                         f"({s.p0[0]:.0f}; {s.p0[1]:.0f})", f"({s.p1[0]:.0f}; {s.p1[1]:.0f})"])
    return rows, {"pieces": len(pieces), "pitch": pitch, "per_unit": per_unit}


def _steps(box, data: dict, hw, led, summary: dict) -> list[str]:
    meta = box.model.meta
    spec = box.spec
    jumpers = [j for j in box.path.joints if j.type == "jumper"]
    ctrl_mode = meta.get("controller_mode", "normal")
    ctrl = hw.controller(meta.get("controller_used", meta["controller"])) if ctrl_mode != "external" else None
    n_boss = meta["n_bosses"]
    design = meta["design"]
    steps: list[str] = []
    steps.append("<b>Parçaları kontrol edin.</b> Baskıdan çıkan parçaları temizleyin (brim/destek izleri, ip çekmeleri). Yüz, gövde ve arka kapağı "
                 "kuru olarak birbirine takıp oturup oturmadığına bakın: dudaklar 0,25 mm boşlukla girer, zorlamayın; sıkıysa zımpara ile hafifçe alın.")
    steps.append("<b>Ön yüzü gövdeye yerleştirin.</b> Yüzün arkasındaki siyah dudak gövdenin içine geçer ve ışık sızıntısını keser. "
                 "Sıkı geçme yeterli olabilir; kalıcı olsun istiyorsanız dudağın dış kenarına birkaç noktadan bir damla cyanoacrylate (hızlı yapıştırıcı) "
                 "sürün (ışık alanına bulaştırmayın). Kuruyana kadar bekleyin.")
    if meta.get("interior_white"):
        steps.append("<b>Arka kapağın iç yüzeyi beyazdır</b> (0,6 mm beyaz katman): ışığı yansıtır. Bu yüzeye yapışkan, yağ veya parmak izi bulaştırmayın.")
    else:
        steps.append("<b>Arka kapağın iç yüzeyi koyu renk</b> (iç beyaz kapalı/eklenemedi): ışık çıkışı biraz azalır. İsterseniz iç yüzeye beyaz sprey/boya uygulayın.")
    n = summary["pieces"]
    cut_txt = (f"LED şeridi <b>tek parça</b> olarak kesin (toplam {box.path.total_length_mm:.0f} mm, {int(round(box.path.total_length_mm / summary['pitch']))} kesim birimi)"
               if box.path.joint == "bend" else f"LED şeridi <b>{n} parçaya</b> kesin (LED kesim listesi tablosundaki uzunluklar)")
    steps.append(f"<b>LED şeridi kesin.</b> {cut_txt}. Yalnızca şerit üzerindeki <b>kesim işaretlerinden</b> (makas simgesi, bakır pedlerin ortası) "
                 f"kesin; işaretler her {summary['pitch']:g} mm'dedir. Şeridin üretici işaretleri bu aralıkta değilse (bazı satıcılar 25 veya 50 mm) en yakın "
                 "işareti kullanıp uzunluğu plana göre ayarlayın. Kesim yüzeyindeki pedleri temiz bırakın.")
    ch = box.model.meta.get("channel")
    guide = (f"<b>LED kanalları</b> (iç genişlik {ch['inner_w_mm']:g} mm, yükseklik {ch['height_mm']:g} mm)" if ch else "<b>ince kılavuz raylar</b>")
    steps.append("<b>Şeridi arka kapağa yapıştırın.</b> Arka kapaktaki " + guide + " şeridin yolunu belirler. Plan çizimindeki numara sırasına göre "
                 "parçaları " + ("kanalların içine" if ch else "rayların arasına") + ", arkadaki 3M bandıyla (önce yüzeyi izopropil alkolle silin) yapıştırın. "
                 + ("Her parçanın ok yönü (DIN → DOUT) planın okuyla aynı olmalı: şerit üzerindeki ok işareti çizimdeki oku göstersin. " if led.addressable else
                    "Tek renk COB şeritte yön yoktur; + ve − uçlarını kablolama bölümüne göre bağlayın. ")
                 + "Şerit bükülecekse yarıçapı " + f"{led.min_bend_radius_mm:g} mm'nin altına indirmeyin.")
    if box.model.meta.get("channel_cover"):
        steps.append(f"<b>Kanal kapaklarını takın.</b> Ayrı basılan {box.model.meta.get('covered_pieces', 0)} beyaz kapak şeridini, LED'leri test ettikten sonra kanalların "
                     "üstüne bastırın; kapak bacakları kanal duvarlarının dışından geçer (sıkı geçme). Kapaklar LED noktalarını yumuşatır.")
    if jumpers:
        tot = box.path.wire_total_mm
        steps.append(f"<b>Parçaları kablo (jumper) ile bağlayın.</b> {len(jumpers)} bağlantı var (toplam yaklaşık {tot:.0f} mm kablo, payları dahil). "
                     + ("Her bağlantıda <b>5V–5V, GND–GND, DOUT→DIN</b> (3 damar) lehimleyin. " if led.addressable else "Her bağlantıda <b>+ ve −</b> (2 damar) lehimleyin. ")
                     + "Lehimden sonra çıplak uçları ince bir parça izole bant/ısıyla büzüşen makaronla örtün; komşu pedlere değmesin. Kabloları raylara paralel, şeridin kenarından geçirin.")
    if ctrl_mode == "external":
        steps.append("<b>Kontrolcü kutunun dışında.</b> Bu üründe kontrolcü kutuya sığmadı: kontrolcü USB kablosunun üzerine, kutunun dışına gelir. "
                     "LED şeridinin bağlantı kablosunu arka plakadaki küçük kablo deliğinden dışarı alın, kontrolcüye bağlayın ve kontrolcüyü masa/duvar arkasına bantlayın. "
                     "Kablo deliğinin kenarına zip-tie ile gerginlik alma bağı yapın.")
    else:
        pocket = ("yatay" if not meta["controller_pocket"].get("vertical") else "dikey (90° döndürülmüş)")
        steps.append(f"<b>Kontrolcüyü yerleştirin.</b> {ctrl.label} arka kapaktaki mavi yuvaya ({pocket}) oturur; kablo tarafı USB çıkış yarığına bakar. "
                     "Önce şerit kablolarını kontrolcüye lehimleyin/bağlayın, sonra kontrolcüyü yuvaya bastırın (gerekirse bir parça çift taraflı bant). "
                     "USB kablosunu çıkış yarığından geçirip yanındaki iki zip-tie yuvasından bağlayarak kabloya çekme gelmesini önleyin.")
    steps.append("<b>Kapatmadan test edin.</b> USB adaptörü ile 5 V verin: tüm LED'ler yanmalı, renk sırası doğru olmalı (adreslenebilir şeritte renkler yanlışsa "
                 "kontrolcüde renk sırasını GRB/RGB olarak değiştirin). Çalışmayan bir parça varsa DIN yönünü ve lehim noktalarını kontrol edin. "
                 "İlk denemede parlaklığı düşük tutun.")
    steps.append(f"<b>Arka kapağı kapatın.</b> Arka kapağın dudağı gövdeye oturur; kabloları sıkıştırmayın. "
                 + (f"<b>{n_boss} adet M3 × 8 mm kendinden kılavuzlu vida</b> ile gövdedeki dayanaklara sabitleyin (pilot delik 2,5 mm, vidayı aşırı sıkmayın; plastiği çatlatır)."
                    if n_boss >= 1 else "Vida yuvası sığmadı: kapağı çevresinden bant/yapıştırıcı ile sabitleyin."))
    if spec.mount == "wall":
        kh = meta.get("keyholes") or []
        spacing = abs(kh[1][0] - kh[0][0]) if len(kh) >= 2 else None
        tx = (f" Dübel/vida merkezleri arasında <b>{spacing:.0f} mm</b> olsun (arka plakadaki iki anahtar deliği arası). " if spacing else " ")
        steps.append("<b>Duvara asın.</b>" + tx + "Başı en çok Ø 8 mm, gövdesi Ø 4 mm olan iki vida kullanın; vidaları 2–3 mm dışarıda bırakıp kutuyu üstten girişe "
                     "takıp aşağı kaydırın. Kutunun üstü kablo çıkışına göre doğru yönde olmalı (anahtar deliği girişi yukarıda).")
    elif design == "rect":
        steps.append("<b>Masaya koyun.</b> Kutunun altındaki iki ayak düz zemin sağlar" + (f"; ayaklar yüzü yaklaşık {meta.get('tilt_deg', 0):g}° geriye yatırır. " if meta.get("tilt_deg") else ". ")
                     + "USB kablosunu arkadan kaydırarak masanın arkasına yönlendirin.")
    elif design == "round":
        steps.append("<b>Standa oturtun.</b> Ayrı basılan stand bloğunun dairesel oluğuna kutuyu yukarıdan indirin; sıkı geçmiyorsa oluğa bir parça ince bant/keçe ekleyin. "
                     "USB kablosunu standın arka duvarındaki kanaldan geçirin.")
    else:
        steps.append("<b>Standa oturtun.</b> Kutunun altındaki ayak çıkıntısını ayrı basılan taban bloğuna bastırın (sıkı geçme; gerekirse bir damla yapıştırıcı). "
                     "USB kablosunu kutunun arkasından taban boyunca yönlendirin.")
    pw = data["power"]
    steps.append(f"<b>Güç.</b> {pw['supply'].replace('usb_', '').replace('_', ' ').upper()} USB adaptör önerilir. Tam beyaz çekilen akım yaklaşık {pw['total_full_w']:.1f} W "
                 f"({pw['full_white_a'] + pw['controller_w'] / pw['voltage']:.1f} A civarı), tipik kullanımda {pw['total_typical_w']:.1f} W. Ayrıntı için Güç notları bölümüne bakın.")
    return steps


def _wiring_flow(addressable: bool, ext: bool) -> Table:
    wires = ("5V (kırmızı) · DIN (yeşil) · GND (siyah/beyaz)" if addressable else "+ (kırmızı) · − (siyah)")
    cells = [["USB adaptör\n5 V", "USB kablo", "Kontrolcü" + (" (kutu dışı)" if ext else ""), "LED şerit\n" + ("(DIN → DOUT)" if addressable else "(+/−)")]]
    t = Table([cells[0]], colWidths=[34 * mm] * 4, rowHeights=[16 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), FONT, 8.5), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("BOX", (0, 0), (-1, -1), 0.6, GREEN), ("INNERGRID", (0, 0), (-1, -1), 0.6, GREEN),
                           ("BACKGROUND", (0, 0), (0, 0), rl.HexColor("#EEEEEE")), ("BACKGROUND", (1, 0), (1, 0), rl.HexColor("#EEEEEE")),
                           ("BACKGROUND", (2, 0), (2, 0), rl.HexColor("#CFE0F5")), ("BACKGROUND", (3, 0), (3, 0), rl.HexColor("#FBD9B8"))]))
    return t


def build_pdf(box, data: dict, files: dict, out_path: str | Path, hw=None) -> Path:
    """Write the guide. ``files``: render paths (lit, unlit, dims) from renders.write_renders."""
    from .hardware import default_hardware

    hw = hw or default_hardware()
    _fonts()
    st = _styles()
    meta = box.model.meta
    spec = box.spec
    led = hw.led(meta["led"])
    ctrl_lbl = hw.controller(meta["controller"]).label
    W, H, D = (box.model.width_mm, box.model.height_mm, box.model.depth_mm)
    story: list = []
    ctrl_mode = meta.get("controller_mode", "normal")
    title = (spec.text or Path(spec.logo or "logo").stem)

    # ---- cover ---------------------------------------------------------------------
    story += [_p("Workbench - Glow · Montaj Kılavuzu", st["h1"]),
              _p(f"{DESIGN_TR[meta['design']]} · “{_esc(title)}” · {data['job_id']}", st["body"]), Spacer(1, 4 * mm)]
    imgs = Table([[_img(files["lit"], 86 * mm), _img(files["unlit"], 86 * mm)],
                  [_p("Yanık (karanlık oda)", st["small"]), _p("Sönük (gün ışığı)", st["small"])]], colWidths=[88 * mm, 88 * mm])
    imgs.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [imgs, Spacer(1, 3 * mm), _img(files["dims"], 120 * mm), Spacer(1, 4 * mm)]
    prt = data["print"]
    summ = [["Boyut (G × Y × D)", f"{W / 10:.1f} × {H / 10:.1f} × {D / 10:.1f} cm"],
            ["LED", f"{led.label} — {box.path.total_length_mm / 1000:.2f} m kullanılır, {data['power']['strip_to_buy_m']:g} m satın alın"],
            ["Kontrolcü", f"{ctrl_lbl} — {CTRL_MODE_TR.get(ctrl_mode, ctrl_mode)}"],
            ["Difüzör", f"{hw.diffuser(spec.diffuser).label} ({meta['diffuser_thickness_mm']:g} mm)"],
            ["Montaj", MOUNT_TR.get(spec.mount, spec.mount)],
            ["Işık", "yazı/logo yanar" if spec.lit == "text" else "arka zemin yanar"],
            ["Baskı", f"{prt['grams_total']:.0f} g filament, yaklaşık {_fmt_dur(prt['time_h'])}, {data['plates']} tabla"],
            ["Tahmini maliyet", f"{data['bom']['total_try']:.0f} TL (filament {data['bom']['filament_try']:.0f} TL)"]]
    story.append(_table([[_p(a, st["cellb"]), _p(_esc(b), st["cell"])] for a, b in summ], [38 * mm, 138 * mm], header=False))
    story.append(PageBreak())

    # ---- 1. parts ------------------------------------------------------------------
    story.append(_p("1. Parça listesi", st["h2"]))
    story.append(_p("<b>Basılan parçalar</b>", st["body"]))
    rows = [[_p("Parça", st["cellb"]), "Renk", _p("Filament", st["cellb"]), _p("Boyut (mm)", st["cellb"]), _p("Not", st["cellb"])]]
    notes = {"face": "Ön yüz: " + ("yüzü aşağı basılır" if meta.get("face_down") else "yüzü yukarı (kabartmalı) basılır"), "body": "Gövde: arka tarafı tablaya gelecek şekilde", "back": "Arka kapak: LED rayları ve kontrolcü yuvası burada",
             "back_white": "Arka kapağın beyaz iç yüzeyi (ayrı renk)", "stand": "Stand/taban", "face_lip": "Işık sızdırmaz dudak"}
    for p in data["parts"]:
        key = p["name"].split("_")[0] if not p["name"].startswith(("back_white", "face_lip")) else p["name"]
        rows.append([_p(p["name"], st["cell"]), _swatch(p["color"]), _p(f"{p['extruder']} ({p['color']})", st["cell"]),
                     _p(" × ".join(f"{v:.0f}" if v >= 10 else f"{v:.1f}" for v in p["size_mm"]), st["cell"]), _p(notes.get(key, ""), st["cell"])])
    story.append(_table(rows, [34 * mm, 12 * mm, 30 * mm, 38 * mm, 62 * mm]))
    story.append(Spacer(1, 4 * mm))
    story.append(_p("<b>Satın alınacak / hazır parçalar ve maliyet (TL)</b>", st["body"]))
    rows = [[_p("Kalem", st["cellb"]), _p("Miktar", st["cellb"]), _p("Birim fiyat", st["cellb"]), _p("Toplam", st["cellb"]), _p("Not", st["cellb"])]]
    unit_tr = {"g": "g", "m": "m", "pcs": "adet"}
    for r in data["bom"]["rows"]:
        rows.append([_p(_esc(r.get("item_tr", r["item"])), st["cell"]), _p(f"{r['qty']:g} {unit_tr.get(r['unit'], r['unit'])}", st["cell"]),
                     _p(f"{r['unit_price_try']:.2f}", st["cell"]), _p(f"{r['total_try']:.2f}", st["cell"]), _p(_esc(r.get("note_tr", r.get("note", ""))), st["cell"])])
    rows.append([_p("TOPLAM", st["cellb"]), "", "", _p(f"{data['bom']['total_try']:.2f}", st["cellb"]), ""])
    story.append(_table(rows, [58 * mm, 24 * mm, 24 * mm, 22 * mm, 48 * mm]))
    story.append(_p("Fiyatlar hardware.yaml'daki varsayımlardır (Donanım sekmesinden güncelleyin). Ayrıca: lehim teli, ısıyla büzüşen makaron, kablo bağı (zip-tie), "
                    "izopropil alkol, ince hızlı yapıştırıcı.", st["small"]))

    # ---- 2. LED cut list -------------------------------------------------------------
    story.append(PageBreak())
    story.append(_p("2. LED kesim listesi ve yol planı", st["h2"]))
    rws, summary = led_rows(box, hw)
    if box.path.joint == "bend":
        story.append(_p("Şerit <b>tek parça</b>dır; satırlar bir önceki satıra U dönüşüyle bağlanır (yarıçap en az "
                        f"{led.min_bend_radius_mm:g} mm). Aşağıdaki çizimde turuncu şerit, kesim işaretleri küçük çizgilerdir.", st["body"]))
    else:
        story.append(_p(f"Şerit <b>{summary['pieces']} parçaya</b> kesilir; parçalar numara sırasıyla bağlanır (kesikli çizgi = jumper kablo). "
                        "Her parçanın başlangıcı numaralı yuvarlak, yönü ok ile gösterilir.", st["body"]))
    story.append(Spacer(1, 2 * mm))
    story.append(PlanDrawing(box, 170 * mm, 120 * mm))
    story.append(_p(f"{PlanDrawing(box, 170 * mm, 120 * mm).scale_text}. Küçük dik çizgiler: her {summary['pitch']:g} mm'de bir kesim işareti. "
                    "Siyah kare: USB kablo çıkışı. Mavi: kontrolcü yuvası.", st["small"]))
    story.append(Spacer(1, 3 * mm))
    head = [_p("Parça", st["cellb"]), _p("Uzunluk (mm)", st["cellb"]), _p("Kesim birimi", st["cellb"]),
            _p("LED adedi", st["cellb"]), _p("Başlangıç (x; y mm)", st["cellb"]), _p("Bitiş (x; y mm)", st["cellb"])]
    story.append(_table([head, *[[_p(str(c), st["cell"]) for c in r] for r in rws]], [16 * mm, 28 * mm, 26 * mm, 24 * mm, 41 * mm, 41 * mm]))
    story.append(_p("Koordinatlar kutunun merkezine göre, arka kapağı içeriden bakarken x sağa, y yukarıdır. "
                    f"Toplam: {box.path.total_length_mm:.0f} mm" + (f", {data['power']['n_leds']} LED." if led.addressable else "."), st["small"]))
    jumpers = [j for j in box.path.joints if j.type == "jumper"]
    story.append(_p("3. Jumper (kablo) bağlantıları", st["h2"]))
    if jumpers:
        jr = [[_p("Bağlantı", st["cellb"]), _p("Kablo boyu (mm)", st["cellb"]), _p("Bağlanacak uçlar", st["cellb"])]]
        pins = "5V–5V, GND–GND, DOUT→DIN" if led.addressable else "+ → +, − → −"
        for j in jumpers:
            jr.append([_p(f"{j.a + 1} → {j.b + 1}", st["cell"]), _p(f"{j.wire_mm:.0f}", st["cell"]), _p(pins, st["cell"])])
        story.append(_table(jr, [30 * mm, 40 * mm, 100 * mm]))
        story.append(_p(f"Toplam kablo yaklaşık {box.path.wire_total_mm:.0f} mm (her bağlantıda şerit uçları için 30 mm pay dahil). "
                        + ("3 damarlı ince (26–28 AWG) kablo kullanın." if led.addressable else "2 damarlı ince kablo kullanın."), st["small"]))
    else:
        story.append(_p("Jumper gerekmez: şerit tek parça ve U dönüşlerle yönlendirilmiştir.", st["body"]))

    # ---- 4. wiring + controller ---------------------------------------------------------
    story.append(_p("4. Kablolama", st["h2"]))
    story.append(_wiring_flow(led.addressable, ctrl_mode == "external"))
    story.append(Spacer(1, 2 * mm))
    if led.addressable:
        story.append(_p("Şerit giriş ucundan (DIN) kontrolcünün veri çıkışına; 5V ve GND kontrolcünün 5 V/GND çıkışlarına bağlanır. "
                        "Kontrolcü modeline göre pin adları değişebilir (genelde +5V / DATA / GND). Veri yönü: plandaki ok yönü. "
                        "Parça 1'in başlangıcı kontrolcüye en yakın uçtur.", st["body"]))
    else:
        story.append(_p("Tek renk COB şerit: + ve − uçları kontrolcüdeki (dimmer) çıkışa bağlanır. Dimmer USB 5 V girişinden beslenir.", st["body"]))
    story.append(_p("5. Kontrolcü", st["h2"]))
    cp = meta["controller_pocket"]
    if ctrl_mode == "external":
        story.append(_p("Kontrolcü kutuya sığmadığı için <b>harici</b> kullanılır: kutuda yalnızca kablo çıkış deliği vardır; kontrolcü kablo üzerinde, kutunun dışında durur. "
                        "Önerilen kontrolcü: " + _esc(ctrl_lbl) + ".", st["body"]))
    else:
        used = hw.controller(meta.get("controller_used", meta["controller"])).label
        story.append(_p(f"Kontrolcü: <b>{_esc(used)}</b>, yuva {cp['size'][0]:.0f} × {cp['size'][1]:.0f} mm "
                        f"({'dikey' if cp['vertical'] else 'yatay'}), konum merkezden ({cp['center'][0] + 0.0:.0f}; {cp['center'][1] + 0.0:.0f}) mm. "
                        f"Yerleşim: {CTRL_MODE_TR.get(ctrl_mode, ctrl_mode)}.", st["body"]))

    # ---- 6. steps --------------------------------------------------------------------
    story.append(_p("6. Montaj adımları", st["h2"]))
    for i, s in enumerate(_steps(box, data, hw, led, summary), start=1):
        story.append(_p(f"<b>{i}.</b> {s}", st["step"]))

    # ---- 7. power -------------------------------------------------------------------
    pw = data["power"]
    story.append(_p("7. Güç notları", st["h2"]))
    prow = [[_p("Tam beyaz/tam parlaklık", st["cell"]), _p(f"{pw['total_full_w']:.1f} W ({pw['full_white_a'] + pw['controller_w'] / pw['voltage']:.2f} A)", st["cell"])],
            [_p("Tipik kullanım", st["cell"]), _p(f"{pw['total_typical_w']:.1f} W ({pw['total_typical_w'] / pw['voltage']:.2f} A)", st["cell"])],
            [_p("Önerilen adaptör", st["cell"]), _p(pw["supply"].replace("usb_", "").replace("_", " ").upper(), st["cell"])]]
    story.append(_table(prow, [60 * mm, 100 * mm], header=False))
    power_w = [w for w in data["warnings"] if w.startswith(("Full ", "Even the typical", "Strip longer"))]
    if "wled_abl_ma" in pw:
        story.append(_p(f"ESP32/WLED kullanıyorsanız <b>Maksimum Akım (ABL) ≈ {pw['wled_abl_ma']} mA</b> ayarlayın; Bluetooth kontrolcüde uygulama parlaklığını "
                        "düşük tutun. Adaptör üzerinde değil, tam beyaz parlak sahnede ısınma/çökme görürseniz parlaklığı azaltın.", st["body"]))
    if "max_brightness_pct" in pw:
        story.append(_p(f"Dimmer'i en çok %{pw['max_brightness_pct']} parlaklıkta kullanın.", st["body"]))
    for w in power_w:
        story.append(_p("• " + _esc(w), st["warn"]))

    # ---- 8. warnings ------------------------------------------------------------------
    story.append(_p("8. Uyarılar", st["h2"]))
    other = [w for w in data["warnings"] if w not in power_w]
    if other:
        for w in other:
            story.append(_p("• " + _esc(w), st["warn"]))
    else:
        story.append(_p("Uyarı yok.", st["body"]))
    for note in meta.get("notes", []):
        story.append(_p("• Bilgi: " + _esc(note), st["warn"]))

    def page(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(15 * mm, 9 * mm, f"Workbench - Glow · {data['job_id']}")
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Sayfa {doc.page}")
        canvas.restoreState()

    out = Path(out_path)
    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                      title=f"Workbench - Glow montaj kılavuzu - {data['job_id']}", author="Workbench - Glow").build(story, onFirstPage=page, onLaterPages=page)
    return out

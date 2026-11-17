"""QR payloads (WiFi, Google review, WhatsApp, social, ...) and the QR module pattern as a polygon in mm (segno)."""
from __future__ import annotations

import re
from urllib.parse import quote

import segno
from shapely import affinity
from shapely.geometry import box
from shapely.ops import unary_union

MIN_MODULE_MM = 1.2  # 3 lines of a 0.4 mm nozzle; smaller modules scan badly from a print
QUIET_MODULES = 2  # light border around the code (spec says 4; 2 reads fine on a plaque and saves room)

KINDS = {
    "wifi": "WiFi", "review": "Google yorum", "whatsapp": "WhatsApp", "instagram": "Instagram", "tiktok": "TikTok",
    "url": "Web adresi", "phone": "Telefon", "text": "Düz yazı",
}


def _wifi_escape(s: str) -> str:
    return re.sub(r'([\\;,:"])', r"\\\1", s)


def phone_digits(s: str) -> str:
    """International digits for wa.me / tel: (a leading 0 becomes Turkey's 90)."""
    d = re.sub(r"\D", "", s)
    if d.startswith("00"):
        d = d[2:]
    elif d.startswith("0"):
        d = "90" + d[1:]
    elif len(d) == 10 and d.startswith("5"):
        d = "90" + d
    return d


def payload(kind: str, v: dict) -> str:
    """QR text for a plaque type. ``v`` keys: ssid, password, security, hidden, link, phone, message, user, text."""
    if kind == "wifi":
        if not v.get("ssid"):
            raise ValueError("WiFi için ağ adı (SSID) girin.")
        sec = v.get("security", "WPA")
        pw = "" if sec == "nopass" else f"P:{_wifi_escape(v.get('password', ''))};"
        hidden = "H:true;" if v.get("hidden") else ""
        return f"WIFI:T:{sec};S:{_wifi_escape(v['ssid'])};{pw}{hidden};"
    if kind == "review":
        link = (v.get("link") or "").strip()
        if not link:
            raise ValueError("Google yorum için işletmenizin yorum bağlantısını ya da Place ID'sini girin.")
        if link.startswith("http"):
            return link
        return f"https://search.google.com/local/writereview?placeid={quote(link)}"
    if kind == "whatsapp":
        d = phone_digits(v.get("phone", ""))
        if len(d) < 10:
            raise ValueError("WhatsApp için telefon numarası girin (ör. 0532 123 45 67).")
        msg = (v.get("message") or "").strip()
        return f"https://wa.me/{d}" + (f"?text={quote(msg)}" if msg else "")
    if kind in ("instagram", "tiktok"):
        user = (v.get("user") or "").strip().lstrip("@")
        if not user:
            raise ValueError("Kullanıcı adını girin.")
        return f"https://instagram.com/{user}" if kind == "instagram" else f"https://www.tiktok.com/@{user}"
    if kind == "url":
        link = (v.get("link") or "").strip()
        if not link:
            raise ValueError("Web adresini girin.")
        return link if re.match(r"^[a-z]+:", link) else "https://" + link
    if kind == "phone":
        d = phone_digits(v.get("phone", ""))
        if len(d) < 10:
            raise ValueError("Telefon numarası girin.")
        return f"tel:+{d}"
    if kind == "text":
        if not (v.get("text") or "").strip():
            raise ValueError("QR'a yazılacak metni girin.")
        return v["text"]
    raise ValueError(f"bilinmeyen QR türü: {kind}")


def matrix(data: str, ecc: str = "m") -> list[list[bool]]:
    """Dark modules (row 0 = top), no quiet zone."""
    q = segno.make(data, error=ecc, boost_error=False, micro=False)
    return [[bool(c) for c in row] for row in q.matrix]


def modules_polygon(data: str, size_mm: float, ecc: str = "m"):
    """Dark modules as one polygon, ``size_mm`` wide (no quiet zone), centred on the origin; (geometry, n modules).

    Rows are merged into runs first; modules touching only at a corner are separated by 0.02 mm so the result is a
    clean polygon set for extrusion (the slicer closes the gap)."""
    m = matrix(data, ecc)
    n = len(m)
    runs = []
    for r, row in enumerate(m):
        c = 0
        while c < n:
            if row[c]:
                c0 = c
                while c < n and row[c]:
                    c += 1
                runs.append(box(c0, n - r - 1, c, n - r))
            else:
                c += 1
    g = unary_union(runs).buffer(-0.02 * n / size_mm, join_style=2)
    g = affinity.scale(affinity.translate(g, -n / 2, -n / 2), size_mm / n, size_mm / n, origin=(0, 0))
    return g, n

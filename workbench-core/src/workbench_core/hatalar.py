"""Turkish wording for the validation errors the Studio UI can surface.

Core/kaligraf raise English ``ValueError`` messages (they are also used by the CLI, MCP and tests); the web job
runner passes them through :func:`turkce` so the person sees Turkish. Unknown messages are returned unchanged.
"""
from __future__ import annotations

import re

_KURALLAR: list[tuple[str, str]] = [
    (r"At most (\d+) colors are supported, got (\d+)",
     r"En fazla \1 renk kullanılabilir (yazıcıda \1 filament yuvası var); seçimde \2 renk var. Harf renklerinden ya da ön yüz renginden birini azaltın."),
    (r"at most (\d+) letter colours.*", r"En fazla \1 harf rengi seçilebilir."),
    (r"style '(\w+)' needs (\d+) colors", r"Bu renk stili \2 renk istiyor; Renkler bölümünden \2 renk seçin."),
    (r"(?:depth must be|depth_mm must be) between 2 and (\d+).*", r"Harf derinliği 2 ile \1 mm arasında olmalı."),
    (r"thickness(?:_mm)? must be between 1 and (\d+).*", r"Harf kalınlığı 1 ile \1 mm arasında olmalı."),
    (r"letter(?:_| )width(?:_mm)? must be between 5 and (\d+).*", r"Harf genişliği 0 (otomatik) ya da 5–\1 mm olmalı."),
    (r"letter height must be between.*|letters mode needs letter_height_cm.*", "Harf yüksekliği 20–250 mm arasında olmalı."),
    (r"stroke_offset_mm must be between.*", "Harf et kalınlığı −1,5 ile +5 mm arasında olmalı."),
    (r"letters mode needs text|text is empty|no drawable glyphs in text", "Metin boş ya da bu yazı tipinde çizilebilir harf yok."),
    (r"Letters mode supports at most (\d+) characters", r"3B harflerde en fazla \1 karakter yazılabilir; metni kısaltın ya da düz tabela kullanın."),
    (r"letters mode does not take a logo", "3B harfler logo almaz; logo için Düz tabela'yı seçin."),
    (r"flat mode needs text and/or logo", "Metin ya da logo girin."),
    (r"flat mode needs width_cm > 0|flat mode requires width_mm", "Genişlik girin."),
    (r"keyhole_boss is for color_style 'backplate'", "Anahtar deliği kabartması yalnız 'Arka plakalı' renk stilinde kullanılır."),
    (r"logo jobs use one body per color.*", "Logolu tabelada renk stili 'Tek renk' olmalı (logo kendi renklerini kullanır)."),
    (r"width too small for backplate offset", "Genişlik plaka payına göre çok küçük; genişliği artırın ya da plaka payını azaltın."),
    (r"width too small for logo_left layout", "Logo solda düzeni için genişlik çok küçük."),
    (r"logo_share must be between.*", "Logo payı 0,1 ile 1 arasında olmalı."),
    (r"unknown color '([^']*)'.*", r"Tanınmayan renk: \1 — #RRGGBB biçiminde seçin."),
    (r"invalid HEX colour '([^']*)'", r"Geçersiz renk kodu: \1"),
    (r"unknown finish '([^']*)'.*", r"Tanınmayan yüzey: \1"),
    (r"unknown mounting option '([^']*)'.*", r"Tanınmayan montaj seçeneği: \1"),
    (r"unsupported logo format '([^']*)'.*", r"Bu logo biçimi desteklenmiyor (\1); SVG, PNG ya da JPG yükleyin."),
    (r"cannot read image .*", "Görsel okunamadı; dosya bozuk ya da desteklenmeyen biçimde."),
    (r"image has no foreground.*|logo has no filled regions|SVG contains no filled shapes",
     "Logoda basılacak dolu şekil bulunamadı; arka planı şeffaf ya da düz renkli, net bir logo yükleyin."),
    (r"unit (\S+) \((\d+)x(\d+)\) does not fit the bed.*",
     r"Bir parça (\2×\3 mm) tablaya sığmıyor; 'Tablaya sığmayan parça' ayarını 'Pimli parçalara böl' yapın ya da boyutu küçültün."),
    (r"text \+ logo needs a font", "Logo ile metin için yazı tipi seçin."),
]
_DERLI = [(re.compile(k, re.I), v) for k, v in _KURALLAR]


def turkce(mesaj: str) -> str:
    for desen, yeni in _DERLI:
        m = desen.fullmatch(mesaj.strip())
        if m:
            return m.expand(yeni)
    return mesaj

#!/usr/bin/env python3
"""Generate a personal digital card from index.html and a small JSON file.

Usage:  python3 make_card.py card.json [output_dir]

Only data the card owner gave for this purpose belongs in the JSON. `consent` must be
true: do not build cards for people from public catalogs without their agreement.
The output is a folder with index.html and mascot.webp; nothing is uploaded anywhere.
"""
import html
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
LANGS = ("ru", "pl", "uk", "be", "en")
LIMITS = {"name": 80, "tagline": 90, "description": 240}
QR_ALT = {"ru": "QR-код визитки", "pl": "Kod QR wizytówki", "uk": "QR-код візитки",
          "be": "QR-код візітоўкі", "en": "Card QR code"}


class CardError(ValueError):
    pass


def https_url(value, field):
    if not isinstance(value, str) or len(value) > 2048:
        raise CardError(f"{field}: нужна ссылка https")
    parts = urlsplit(value.strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise CardError(f"{field}: допускается только https-ссылка без логина и пароля")
    return value.strip()


def texts(data, field):
    raw = data.get(field)
    if not isinstance(raw, dict) or not raw:
        raise CardError(f"{field}: нужен объект с текстами по языкам ({', '.join(LANGS)})")
    out = {}
    for lang, value in raw.items():
        if lang not in LANGS:
            raise CardError(f"{field}: неизвестный язык {lang!r}")
        if not isinstance(value, str) or not value.strip():
            raise CardError(f"{field}.{lang}: пустой текст")
        value = " ".join(value.split())
        if len(value) > LIMITS[field]:
            raise CardError(f"{field}.{lang}: длиннее {LIMITS[field]} символов")
        out[lang] = value
    fallback = out.get("ru") or next(iter(out.values()))
    return {lang: out.get(lang, fallback) for lang in LANGS}


def validate(data):
    if data.get("consent") is not True:
        raise CardError("consent: нужно true — владелец визитки согласился на её создание")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > LIMITS["name"]:
        raise CardError("name: обязательное поле, до 80 символов")
    qr = https_url(data.get("qr_url"), "qr_url")
    link = https_url(data["name_link"], "name_link") if data.get("name_link") else qr
    slug = data.get("slug", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", slug):
        raise CardError("slug: латиница, цифры и дефис, например anna-kowalska")
    return {"name": " ".join(name.split()), "qr": qr, "link": link, "slug": slug,
            "tagline": texts(data, "tagline"), "description": texts(data, "description")}


def js_json(value):
    """JSON safe to embed inside a <script> block."""
    return (json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def sub_once(source, pattern, make):
    """Replace exactly one match; make(match) returns the new text."""
    found = list(re.finditer(pattern, source, flags=re.S))
    if len(found) != 1:
        raise CardError(f"шаблон index.html изменился, не найден фрагмент: {pattern[:50]!r}")
    m = found[0]
    return source[:m.start()] + make(m) + source[m.end():]


def render(template, card):
    esc = lambda value: html.escape(value, quote=True)
    ru_tag, ru_desc = card["tagline"]["ru"], card["description"]["ru"]
    title = f"{card['name']} — цифровая визитка"
    out = sub_once(template, r"<title>.*?</title>", lambda m: f"<title>{esc(title)}</title>")
    out = sub_once(out, r'<meta name="description" content="[^"]*">',
                   lambda m: f'<meta name="description" content="{esc(ru_desc)}">')
    out = sub_once(out, r'<meta property="og:title" content="[^"]*">',
                   lambda m: f'<meta property="og:title" content="{esc(title)}">')
    out = sub_once(out, r'<meta property="og:description" content="[^"]*">',
                   lambda m: f'<meta property="og:description" content="{esc(ru_tag)}. {esc(ru_desc)}">')
    out = sub_once(out, r'<a class="name" href="[^"]*">[^<]*</a>',
                   lambda m: f'<a class="name" href="{esc(card["link"])}" rel="noopener noreferrer">{esc(card["name"])}</a>')
    out = sub_once(out, r'(<div class="sub" data-i18n="tagline">)[^<]*(</div>)',
                   lambda m: m.group(1) + html.escape(ru_tag) + m.group(2))
    out = sub_once(out, r'(<p class="description" data-i18n="description">)[^<]*(</p>)',
                   lambda m: m.group(1) + html.escape(ru_desc) + m.group(2))
    out = sub_once(out, r"encodeURIComponent\('https://t\.me/atlas_smart_library_bot\?profile'\)",
                   lambda m: f"encodeURIComponent({js_json(card['qr'])})")
    overrides = {lang: {"tagline": card["tagline"][lang], "description": card["description"][lang],
                        "qrAlt": QR_ALT[lang]} for lang in LANGS}
    inject = f"const overrides={js_json(overrides)};for(const l in translations)Object.assign(translations[l],overrides[l]);"
    out = sub_once(out, r'const wrap=document\.getElementById\("lang-wrap"\)',
                   lambda m: inject + m.group(0))
    out = sub_once(out, r'<img src="\./mascot\.webp\?v=7"([^>]*?) alt="[^"]*">',
                   lambda m: f'<img src="./mascot.webp?v=7"{m.group(1)} alt="">')
    return out


def build(data, out_dir):
    card = validate(data)
    page = render((HERE / "index.html").read_text(encoding="utf-8"), card)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    shutil.copyfile(HERE / "mascot.webp", out_dir / "mascot.webp")
    return out_dir / "index.html"


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    try:
        data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        slug = data.get("slug", "card") if isinstance(data, dict) else "card"
        target = build(data, argv[2] if len(argv) == 3 else HERE / "out" / str(slug))
    except (OSError, json.JSONDecodeError, CardError, AttributeError) as error:
        print("Ошибка:", error)
        return 1
    print("Готово:", target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

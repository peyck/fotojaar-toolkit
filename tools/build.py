"""Fotojaar – bouwscript.

Selecteert gedateerde foto's (jaartal uit lijst, metadata of map-/bestandsnaam) uit een fotocollectie,
houdt alleen beeldzijdes over, maakt webversies zonder metadata en schrijft
de weekplanning naar site/data/photos.json.

Eerste keer:
    python build.py setup     # vragen stellen en config.json schrijven
    python build.py check     # installatie en collectie controleren
    python build.py demo      # kleine demo-instantie in demo/ bouwen
(Met --config pad/naar/config.json werk je met een andere instantie; de gegevens staan naast dat bestand.)

Stappen:
    python build.py scan      # exiftool over de collectie -> cache/meta.json
    python build.py analyze   # kandidaten + achterzijde-detectie -> cache/candidates.json + review.html
    python build.py review    # review.html opnieuw openen (met "Toon in Verkenner"); analyze doet dit ook
    python build.py build     # webafbeeldingen + site/data/photos.json
    python build.py init-csv  # photos.csv met alle foto's om de jaartallen in in te vullen (zonder exiftool)
    python build.py verhalen  # verhalen.html: per foto een verhaal schrijven -> verhalen.json
    python build.py publish   # commit + push van site/ naar GitHub Pages

Handmatige correcties gaan in tools/overrides.json:
    {"exclude": ["relatief/pad.jpg", ...], "include": [...]}
(review.html kan dit bestand voor je aanmaken.)
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import platform
import secrets
import shutil
import threading
import webbrowser
import random
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import urlparse
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

# --- instellingen -------------------------------------------------------------

HERE = Path(__file__).resolve().parent          # de code (build.py, templates)


def _config_path() -> Path:
    """--config pad/naar/config.json of FOTOJAAR_CONFIG; standaard tools/config.json."""
    if "--config" in sys.argv:
        i = sys.argv.index("--config")
        if i + 1 >= len(sys.argv):
            sys.exit("--config heeft een pad nodig")
        path = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return Path(path).resolve()
    return Path(os.environ.get("FOTOJAAR_CONFIG") or HERE / "config.json").resolve()


CONFIG_PATH = _config_path()
DATA = CONFIG_PATH.parent                        # de gegevens van deze instantie staan naast config.json


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")) if CONFIG_PATH.exists() else {}


CFG = _load_config()


def _re(key: str):
    """Optioneel, hoofdletterongevoelig patroon uit de config (leeg = uitgeschakeld)."""
    return re.compile(CFG[key], re.I) if CFG.get(key) else None


# Niets hardgecodeerd: alles komt uit tools/config.json (zie config.example.json).
COLLECTION = Path(CFG["collection"]) if CFG.get("collection") else None
_fl_db = CFG.get("fotolineage_db")                   # optioneel; relatief t.o.v. de collectie
FL_DB = (COLLECTION / _fl_db) if (_fl_db and COLLECTION) else None
FL_CONFIG = Path(CFG["fotolineage_config"]) if CFG.get("fotolineage_config") else None
EXIFTOOL_CANDIDATES = CFG.get("exiftool_paths") or ["exiftool"]

CACHE = DATA / "cache"
SITE = (DATA / CFG.get("site_dir", "../dist")).resolve()     # hier komt de website terecht
TEMPLATE = HERE.parent / "site_template"                      # bronbestanden van de website
IMG_DIR = SITE / "img"
SCHEDULE = DATA / "schedule.json"
OVERRIDES = DATA / "overrides.json"
STORIES = DATA / "verhalen.json"          # {"verhalen": {relpad: tekst}}
SEEN = CACHE / "seen.json"                # {relpad: datum}: kandidaten die al gepubliceerd zijn
SITE_URL = CFG.get("site_url", "")
SITE_CFG = CFG.get("site", {})               # titel, collectienaam, verwijzingen, statistiek (zie config.example.json)
TITLE = SITE_CFG.get("title", "Fotojaar")
LANG = CFG.get("lang", "nl")                 # taal van de website: nl of en (bestanden in site_template/lang/)
RENDER_SITE = CFG.get("render_site", True)   # false: site_dir zelf onderhouden, build raakt de pagina's niet aan
PUBLISH_MODE = CFG.get("publish", "zip")     # zip | folder | git

PER_WEEK = CFG.get("per_week", 5)
MAX_SIDE = CFG.get("max_side", 1600)
JPEG_QUALITY = CFG.get("jpeg_quality", 82)
MAX_RANGE = CFG.get("max_range", 10)         # jaartallen die verder uiteen liggen -> foto overslaan
YEAR_RE = re.compile(r"^(1[6-9]\d\d|20[0-2]\d)$")
CIRCA = CFG.get("circa", 2)                  # CircaDate 1910~ / 1910? -> 1908–1912
DATE_MAX_YEAR = CFG.get("date_max_year", 2000)   # DateCreated hierna = meestal scandatum -> negeren
SKIP_DIRS = set(CFG.get("skip_dirs", []))
SKIP_NAME_RE = _re("skip_name_regex")        # bestandsnamen die uitgesloten worden
SKIP_REF_RE = _re("skip_ref_regex")          # verwijzingen (pad, keywords, maker, …) die uitgesloten worden
# Mappen waar het jaartal met de hand op de voorzijde staat (verklapt het antwoord).
FRONT_DATED_DIRS = set(CFG.get("front_dated_dirs", []))
OG_PHOTOS = CFG.get("og_photos", [])         # foto's voor het linkvoorbeeld; nooit spelfoto's
# Bronnen voor het jaartal, in volgorde van voorrang (overrides.json → jaar gaat altijd voor):
#   csv = tabel met foto's en jaartallen, metadata = keywords/CircaDate/DateCreated (exiftool),
#   path = jaartal in map- of bestandsnaam.
YEAR_SOURCES = CFG.get("year_sources", ["csv", "metadata", "path"])
CSV_FILE = DATA / CFG.get("csv", "photos.csv")          # .csv of .xlsx
PATH_YEAR_FROM = CFG.get("path_year_from", ["filename", "folder"])
DETECT_BACKS = CFG.get("detect_backs", True)  # achterzijdes (kartons, blanco papier) automatisch herkennen
IMAGE_EXTS = {".jpg", ".jpeg", ".tif", ".tiff"}
OBF_KEY = CFG.get("obf_key", "fotojaar")
SALT = CFG.get("salt", "fotojaar")

# --- hulpfuncties -------------------------------------------------------------


def exiftool() -> str:
    for c in EXIFTOOL_CANDIDATES:
        if (shutil.which(c) if "/" not in c and "\\" not in c else Path(c).exists()):
            return c
    sys.exit("exiftool niet gevonden (https://exiftool.org). Zet het pad in 'exiftool_paths' in config.json, "
             "of gebruik enkel de jaartalbronnen 'csv' en 'path' (zie 'year_sources').")


def as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [s.strip() for s in str(v).split(",")] if "," in str(v) else [str(v)]


def rel(path: str) -> str:
    return Path(path).resolve().relative_to(COLLECTION.resolve()).as_posix()


def load_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def write_json(p: Path, obj, **kw):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, **kw), encoding="utf-8")


# --- stap 1: scan -------------------------------------------------------------


def exiftool_args(targets: list[str]) -> list[str]:
    args = [exiftool()]
    if FL_CONFIG and FL_CONFIG.exists():
        args += ["-config", str(FL_CONFIG)]
    return args + [
        "-r", "-fast", "-json", "-G1", "-charset", "filename=utf8",
        "-ext", "jpg", "-ext", "jpeg", "-ext", "tif", "-ext", "tiff",
        "-XMP-dc:Subject", "-IPTC:Keywords", "-XMP-lr:HierarchicalSubject",
        "-XMP-fotolineage:all", "-XMP-photoshop:City", "-XMP-dc:Creator",
        "-XMP-photoshop:DateCreated", "-IPTC:DateCreated", "-ExifIFD:DateTimeOriginal",
        "-File:ImageWidth", "-File:ImageHeight",
        *targets,
    ]


def cmd_scan(targets: list[str] | None = None):
    """Zonder argumenten: hele collectie (± 25 min). Met bestandsnamen, paden of mappen:
    alleen die opnieuw inlezen en in cache/meta.json bijwerken (enkele seconden)."""
    CACHE.mkdir(exist_ok=True)
    meta_out = CACHE / "meta.json"
    if "metadata" not in YEAR_SOURCES:
        print("'metadata' staat niet in year_sources (config.json): scan is niet nodig, ga naar 'analyze'.")
        return
    if not targets:
        print("exiftool loopt over de hele collectie, dit duurt even…")
        with open(meta_out, "wb") as fh:
            subprocess.run(exiftool_args([str(COLLECTION)]), stdout=fh, check=False)
        print(f"klaar -> {meta_out}")
        return

    meta = json.loads(meta_out.read_text(encoding="utf-8-sig")) if meta_out.exists() else []
    paths = []
    for t in targets:
        p = Path(t)
        if not p.is_absolute():
            p = COLLECTION / t
        if p.exists():
            paths.append(str(p))
            continue
        # losse bestandsnaam: opzoeken in de cache
        hits = [r["SourceFile"] for r in meta if r["SourceFile"].rsplit("/", 1)[-1].casefold() == t.casefold()]
        if not hits:
            hits = [str(q) for q in COLLECTION.rglob(t)]
        if not hits:
            print(f"niet gevonden: {t}")
        paths += hits
    if not paths:
        return
    res = subprocess.run(exiftool_args(paths), capture_output=True, check=False)
    fresh = json.loads(res.stdout.decode("utf-8") or "[]")
    by_rel = {rel(r["SourceFile"]): r for r in meta}
    for r in fresh:
        by_rel[rel(r["SourceFile"])] = r
        print(f"bijgewerkt: {rel(r['SourceFile'])}")
    write_json(meta_out, list(by_rel.values()))
    print(f"{len(fresh)} bestand(en) bijgewerkt in {meta_out}")


# --- stap 2: analyse ----------------------------------------------------------


def read_db() -> dict[str, dict]:
    if not (FL_DB and FL_DB.exists()):
        return {}
    con = sqlite3.connect(f"file:{FL_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select id, filepath, side, pair_uuid, kind, ignored, photographer, city, location_name, scene_date_edtf, "
        "title, description, headline, credit, rights, source from photos"
    ).fetchall()
    return {r["filepath"].replace("\\", "/"): dict(r) for r in rows}


def years_from_keywords(rec: dict) -> list[int]:
    kws = set()
    for k in ("XMP-dc:Subject", "IPTC:Keywords"):
        kws.update(x.strip() for x in as_list(rec.get(k)))
    for h in as_list(rec.get("XMP-lr:HierarchicalSubject")):
        kws.add(h.split("|")[-1].strip())
    return sorted({int(k) for k in kws if YEAR_RE.match(k)})


EDTF_Y = r"(\d{4})(?:-\d{2}(?:-\d{2})?)?"


def years_from_edtf(s: str) -> list[int]:
    """FotoLineage CircaDate (EDTF-subset) -> [van, tot]; open grenzen -> []."""
    s = (s or "").strip()
    m = re.fullmatch(EDTF_Y + r"([~?%]?)", s)
    if m:
        y = int(m.group(1))
        return [y - CIRCA, y + CIRCA] if m.group(2) else [y, y]
    m = re.fullmatch(EDTF_Y + r"[~?]?/" + EDTF_Y + r"[~?]?", s)
    if m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        return [a, b]
    return []                      # ../1913, 1913/.. of onbekend: te vaag


def years_from_datecreated(rec: dict) -> list[int]:
    """DateCreated (XMP/IPTC/EXIF), alleen t.e.m. DATE_MAX_YEAR: latere datums zijn
    meestal de scandatum van de reproductie, niet de datum van de foto."""
    for k in ("XMP-photoshop:DateCreated", "IPTC:DateCreated", "ExifIFD:DateTimeOriginal"):
        m = re.match(r"(\d{4})", str(rec.get(k) or ""))
        if m and 1650 <= int(m.group(1)) <= DATE_MAX_YEAR:
            return [int(m.group(1))] * 2
    return []


def resolve_datecreated(rec: dict, fl_edtf: str | None) -> tuple[list[int], str, str]:
    """DateCreated nader bekijken -> (jaren, bron, probleem).

    - XMP wijkt af maar IPTC en EXIF zijn het eens: IPTC/EXIF wint (recentste aanpassing,
      sommige programma's werken XMP-photoshop:DateCreated niet bij);
    - jaartal = midden van het FotoLineage-bereik: dat bereik gebruiken (max. MAX_RANGE jaar),
      want FotoLineage schrijft het midden van een bereik naar DateCreated;
    - andere tegenstrijdigheden: foto uitsluiten tot het jaartal rechtgezet is."""
    def y(k):
        m = re.match(r"(\d{4})", str(rec.get(k) or ""))
        return int(m.group(1)) if m else None
    xmp, iptc, exif = y("XMP-photoshop:DateCreated"), y("IPTC:DateCreated"), y("ExifIFD:DateTimeOriginal")
    vals = [v for v in (xmp, iptc, exif) if v]
    if len(set(vals)) > 1:
        if iptc and exif and iptc == exif:
            year = iptc
        else:
            return [], "DateCreated", ("DateCreated-velden tegenstrijdig (" + " / ".join(map(str, sorted(set(vals))))
                                       + ") – zet het juiste jaar in FotoLineage of in overrides.json → jaar")
    else:
        year = vals[0]
    if not (1650 <= year <= DATE_MAX_YEAR):
        return [], "DateCreated", ""
    if fl_edtf:
        rng = years_from_edtf(fl_edtf)
        mid = (rng[0] + rng[1]) // 2 if rng else None
        open_bound = not rng and ".." in fl_edtf
        if (rng and year == mid) or (open_bound and str(year) in fl_edtf):
            if rng and rng[1] - rng[0] <= MAX_RANGE:
                return rng, "FotoLineage-bereik", ""
            return [], "DateCreated", f"DateCreated is het midden van het FotoLineage-bereik {fl_edtf} (te breed)"
    return [year, year], "DateCreated", ""


def photo_years(rec: dict) -> tuple[list[int], str]:
    """Jaartal(len) van de foto + bron, in volgorde van betrouwbaarheid."""
    ys = years_from_keywords(rec)
    if ys:
        return [ys[0], ys[-1]], "keyword"
    ys = years_from_edtf(rec.get("XMP-fotolineage:CircaDate"))
    if ys:
        return ys, "CircaDate"
    ys = years_from_datecreated(rec)
    if ys:
        return ys, "DateCreated"
    return [], ""


def image_features(path: Path) -> dict:
    """Eenvoudige kenmerken om achterzijdes te herkennen: die zijn licht,
    weinig contrastrijk en weinig verzadigd (papier met wat drukwerk/inkt)."""
    with Image.open(path) as im:
        im.draft("RGB", (256, 256))
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((256, 256))
        w, h = im.size
        # rand wegsnijden (scannerbed/kader)
        im = im.crop((int(w * .08), int(h * .08), int(w * .92), int(h * .92)))
        g = im.convert("L")
        hist = g.histogram()
        n = sum(hist)
        dark = sum(hist[:90]) / n
        mid = sum(hist[90:170]) / n
        std = ImageStat.Stat(g).stddev[0]
        mean = ImageStat.Stat(g).mean[0]
        sat = ImageStat.Stat(im.convert("HSV")).mean[1]
    # score > 0 => lijkt op een beeldzijde
    score = 3.0 * dark + 1.2 * mid + std / 60 - 0.6
    return {"dark": round(dark, 3), "mid": round(mid, 3), "std": round(std, 1),
            "mean": round(mean, 1), "sat": round(sat, 1), "score": round(score, 3)}


def num_key(p: str):
    """Map + basisnaam zonder volgnummer + volgnummer, voor opeenvolgende scans."""
    d, name = p.rsplit("/", 1) if "/" in p else ("", p)
    stem = name.rsplit(".", 1)[0]
    m = re.match(r"^(.*?)(\d+)$", stem)
    if not m:
        return None
    return d, m.group(1), int(m.group(2))


# --- jaartal uit csv en pad ---------------------------------------------------

CSV_ALIASES = {
    "pad": "path", "path": "path", "bestand": "path", "file": "path", "filename": "path",
    "jaar": "year", "year": "year", "jaar_tot": "year_to", "year_to": "year_to", "tot": "year_to",
    "titel": "title", "title": "title",
    "beschrijving": "description", "description": "description",
    "fotograaf": "photographer", "photographer": "photographer",
    "plaats": "place", "place": "place",
    "verhaal": "story", "story": "story",
    "keywords": "keywords", "trefwoorden": "keywords",
}
CSV_HEADER = ["pad", "jaar", "jaar_tot", "titel", "beschrijving", "fotograaf", "plaats", "verhaal", "keywords"]
_csv_cache: dict | None = None


def _read_table(path: Path) -> list[list]:
    if path.suffix.lower() == ".xlsx":
        try:
            import openpyxl
        except ImportError:
            sys.exit("Voor .xlsx is 'openpyxl' nodig (pip install openpyxl), of bewaar de lijst als .csv.")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        return [list(r) for r in wb.active.iter_rows(values_only=True)]
    import csv
    text = path.read_text(encoding="utf-8-sig")
    head = text.splitlines()[0] if text.strip() else ""
    delim = max(";,\t", key=head.count)           # Excel (NL) bewaart met ';', anders ',' of tab
    return list(csv.reader(text.splitlines(), delimiter=delim))


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)                      # Excel: 1952.0 -> 1952
    return str(v).strip()


def csv_rows() -> dict[str, dict]:
    """De foto-lijst (CSV/XLSX) als {pad of bestandsnaam in kleine letters: rij}."""
    global _csv_cache
    if _csv_cache is not None:
        return _csv_cache
    _csv_cache = {}
    if "csv" in YEAR_SOURCES and CSV_FILE.exists():
        table = _read_table(CSV_FILE)
        if table:
            cols = [CSV_ALIASES.get(_cell(h).casefold()) for h in table[0]]
            if "path" not in cols:
                sys.exit(f"{CSV_FILE.name}: kolom 'pad' ontbreekt (kolommen: {', '.join(CSV_HEADER)})")
            for raw in table[1:]:
                row = {c: _cell(v) for c, v in zip(cols, raw) if c}
                key = row.get("path", "").replace("\\", "/").removeprefix("./").strip("/").casefold()
                if key:
                    _csv_cache[key] = row
    return _csv_cache


def csv_row(rp: str) -> dict:
    rows = csv_rows()
    if not rows:
        return {}
    return rows.get(rp.casefold()) or rows.get(rp.rsplit("/", 1)[-1].casefold()) or {}


def parse_year_cell(text: str) -> list[int]:
    """'1952', '1950-1955', '1950/1955', '1950~' -> [van, tot]; onleesbaar -> []."""
    t = _cell(text)
    m = re.fullmatch(r"(\d{4})\s*[-–/]\s*(\d{4})", t)
    if m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        return [a, b]
    return years_from_edtf(t)


def csv_years(row: dict) -> list[int]:
    ys = parse_year_cell(row.get("year", "")) if row else []
    if ys and row.get("year_to", "").isdigit() and ys[0] == ys[1]:
        ys = sorted((ys[0], int(row["year_to"])))
    return ys if ys and all(1600 <= y <= 2029 for y in ys) else []


PATH_YEAR = r"(1[6-9]\d\d|20[0-2]\d)"
PATH_YEAR_RE = re.compile(rf"(?<!\d){PATH_YEAR}(?!\d)")
PATH_RANGE_RE = re.compile(rf"(?<!\d){PATH_YEAR}\s*[-–_]\s*{PATH_YEAR}(?!\d)")


def path_years(rp: str) -> list[int]:
    """Jaartal in de bestandsnaam en/of de mapnamen (diepste map eerst), volgens path_year_from."""
    parts = rp.split("/")
    texts = []
    for where in PATH_YEAR_FROM:
        if where == "filename":
            texts.append(parts[-1].rsplit(".", 1)[0])
        elif where == "folder":
            texts += reversed(parts[:-1])
    for t in texts:
        m = PATH_RANGE_RE.search(t)
        if m:
            return sorted((int(m.group(1)), int(m.group(2))))
        ys = sorted({int(y) for y in PATH_YEAR_RE.findall(t)})
        if ys:
            return [ys[0], ys[-1]]
    return []


def resolve_years(rec: dict, rp: str, db: dict, manual_years: dict) -> tuple[list[int], str, str]:
    """Jaartal van één foto -> (jaren, bron, probleem). overrides.json gaat voor alles; daarna
    de bronnen uit YEAR_SOURCES in volgorde."""
    if rp in manual_years:
        return [int(manual_years[rp])] * 2, "handmatig (overrides.json)", ""
    for source in YEAR_SOURCES:
        if source == "csv":
            ys = csv_years(csv_row(rp))
            if ys:
                return ys, "csv", ""
        elif source == "metadata":
            years, src = photo_years(rec)
            if not years:
                continue
            if src == "DateCreated":
                ys, src, problem = resolve_datecreated(rec, db.get(rp, {}).get("scene_date_edtf"))
                return ys or years, src, problem
            return years, src, ""
        elif source == "path":
            ys = path_years(rp)
            if ys:
                return ys, "map/bestandsnaam", ""
    return [], "", ""


def walk_images() -> list[str]:
    """Alle afbeeldingen in de collectie (relatieve paden), zonder exiftool."""
    return sorted(p.relative_to(COLLECTION).as_posix() for p in COLLECTION.rglob("*")
                  if p.suffix.lower() in IMAGE_EXTS and p.is_file())


def load_records(meta_in: Path) -> list[dict]:
    """exiftool-records (na 'scan') aangevuld met bestanden zonder metadata als csv/path een bron zijn."""
    meta = json.loads(meta_in.read_text(encoding="utf-8-sig")) if meta_in.exists() else []
    if {"csv", "path"} & set(YEAR_SOURCES):
        known = {rel(r["SourceFile"]) for r in meta}
        meta += [{"SourceFile": str(COLLECTION / rp)} for rp in walk_images() if rp not in known]
    if not meta:
        sys.exit("Geen bestanden gevonden: voer eerst 'python build.py scan' uit (bron 'metadata'), "
                 "of controleer 'collection' in config.json.")
    return meta


def cmd_init_csv():
    """Maakt tools/photos.csv met alle foto's van de collectie, jaartal ingevuld waar het uit de map- of
    bestandsnaam volgt. Een bestaande lijst wordt niet overschreven."""
    import csv
    if CSV_FILE.exists():
        sys.exit(f"{CSV_FILE} bestaat al; hernoem of verwijder het eerst.")
    rows = 0
    with open(CSV_FILE, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(CSV_HEADER)
        for rp in walk_images():
            ys = path_years(rp)
            year = "" if not ys else str(ys[0]) if ys[0] == ys[1] else f"{ys[0]}-{ys[1]}"
            w.writerow([rp, year] + [""] * (len(CSV_HEADER) - 2))
            rows += 1
    print(f"{rows} foto's -> {CSV_FILE}")
    print("Vul de kolom 'jaar' aan (ook 'beschrijving', 'verhaal', … mogen) en voer daarna 'analyze' uit.")


def cmd_analyze(meta_in: Path = CACHE / "meta.json"):
    meta = load_records(meta_in)
    db = read_db()
    print(f"{len(meta)} bestanden, {len(db)} in FotoLineage-db, {len(csv_rows())} in de fotolijst")

    cands = []
    skipped = defaultdict(int)
    found = defaultdict(int)
    manual_years = load_json(OVERRIDES, {}).get("jaar", {})
    for rec in meta:
        rp = rel(rec["SourceFile"])
        years, src, problem = resolve_years(rec, rp, db, manual_years)
        if not years:
            continue
        found[src] += 1
        top = rp.split("/", 1)[0]
        if top in SKIP_DIRS:
            skipped["map uitgesloten"] += 1
            continue
        if SKIP_NAME_RE and SKIP_NAME_RE.match(rp.rsplit("/", 1)[-1]):
            skipped["bestandsnaam (skip_name_regex)"] += 1
            continue
        d0 = db.get(rp, {})
        ref_texts = [rp, *as_list(rec.get("XMP-dc:Subject")), *as_list(rec.get("IPTC:Keywords")),
                     *as_list(rec.get("XMP-dc:Creator")),
                     *(str(d0.get(k) or "") for k in ("title", "description", "headline", "credit", "rights", "source"))]
        if SKIP_REF_RE and any(SKIP_REF_RE.search(x) for x in ref_texts):
            skipped["verwijzing (skip_ref_regex)"] += 1
            continue
        if years[-1] - years[0] > MAX_RANGE:
            skipped["jaartallen te ver uiteen"] += 1
            continue
        d = db.get(rp, {})
        role = (rec.get("XMP-fotolineage:PairPartnerRole") or "").lower()
        side = d.get("side") or ("back" if role == "back" else "front" if role == "front" else None)
        if d.get("kind") == "document":
            skipped["document"] += 1
            continue
        if d.get("ignored"):
            skipped["genegeerd in FotoLineage"] += 1
            continue
        cands.append({
            "path": rp, "years": [years[0], years[-1]], "side": side, "src": src, "problem": problem,
            "caption": " · ".join(x for x in (d.get("photographer") or csv_row(rp).get("photographer"),
                                              d.get("location_name") or d.get("city") or csv_row(rp).get("place")) if x),
        })

    # Dubbels (zelfde bestand op meerdere plaatsen) wegfilteren
    # sha1 en beeldkenmerken per bestand onthouden (sleutel: pad + grootte + wijzigingstijd)
    fcache_path = CACHE / "features.json"
    fcache = load_json(fcache_path, {})

    def fkey(c):
        st = (COLLECTION / c["path"]).stat()
        return f'{c["path"]}|{st.st_size}|{int(st.st_mtime)}'

    seen, uniq = {}, []
    for c in cands:
        p = COLLECTION / c["path"]
        c["_k"] = fkey(c)
        h = fcache.get(c["_k"], {}).get("sha1") or hashlib.sha1(p.read_bytes()).hexdigest()
        if h in seen:
            skipped["dubbel"] += 1
            continue
        seen[h] = c["path"]
        c["sha1"] = h
        uniq.append(c)
    cands = uniq

    print("beeldkenmerken berekenen…")
    new_cache, computed = {}, 0
    for i, c in enumerate(cands):
        k = c.pop("_k")
        hit = fcache.get(k)
        if hit and "feat" in hit:
            c["feat"] = hit["feat"]
        else:
            computed += 1
            try:
                c["feat"] = image_features(COLLECTION / c["path"])
            except Exception as e:  # noqa: BLE001
                c["feat"] = None
                c["error"] = str(e)
        new_cache[k] = {"sha1": c["sha1"], "feat": c["feat"]}
        if computed and computed % 100 == 0:
            print(f"  {i}/{len(cands)}")
    write_json(fcache_path, new_cache)
    print(f"  {computed} nieuw berekend, {len(cands) - computed} uit de cache")

    # Ongekoppelde opeenvolgende scans met hetzelfde jaartal: de zwakste is
    # vermoedelijk de achterzijde.
    groups = defaultdict(list)
    for c in cands:
        k = num_key(c["path"])
        if k:
            groups[(k[0], k[1], tuple(c["years"]))].append((k[2], c))
    for lst in groups.values():
        lst.sort(key=lambda t: t[0])
        for (n1, a), (n2, b) in zip(lst, lst[1:]):
            if n2 - n1 != 1 or a["side"] or b["side"] or not a["feat"] or not b["feat"]:
                continue
            front, back = (a, b) if a["feat"]["score"] >= b["feat"]["score"] else (b, a)
            if front["feat"]["score"] - back["feat"]["score"] > 0.15:
                back["auto"] = f"achterzijde van {front['path'].rsplit('/', 1)[-1]}"
                front.setdefault("auto_front", True)

    for c in cands:
        if c.get("problem"):
            c["verdict"], c["why"] = "exclude", c["problem"]
        elif c["path"].rsplit("/", 1)[0] in FRONT_DATED_DIRS:
            c["verdict"], c["why"] = "exclude", "jaartal op voorzijde geschreven"
        elif c["side"] in ("back", "extra"):
            c["verdict"], c["why"] = "exclude", f"FotoLineage: {c['side']}"
        elif c["side"] == "front":
            c["verdict"], c["why"] = "include", "FotoLineage: voorzijde"
        elif not c.get("feat"):
            c["verdict"], c["why"] = "exclude", "onleesbaar"
        elif not DETECT_BACKS:
            c["verdict"], c["why"] = "include", "beeldzijde (achterzijde-detectie uit)"
        elif c.get("auto"):
            c["verdict"], c["why"] = "exclude", c["auto"]
        elif c["feat"]["score"] < 0:
            c["verdict"], c["why"] = "exclude", "lijkt achterzijde (licht, weinig contrast)"
        else:
            c["verdict"], c["why"] = "include", "lijkt beeldzijde"

    seen = load_json(SEEN, None)
    for c in cands:
        c["new"] = seen is not None and c["path"] not in seen
    n_new = sum(c["new"] for c in cands)
    make_review(cands)
    write_json(CACHE / "candidates.json", cands, indent=1)
    if seen is not None:
        print(f"  {n_new} nieuw sinds de laatste publicatie (filter 'Nieuw' in review.html)")
    inc = sum(c["verdict"] == "include" for c in cands)
    print(f"{len(cands)} kandidaten: {inc} beeldzijdes, {len(cands) - inc} uitgesloten")
    for k, v in found.items():
        print(f"  jaartal uit {k}: {v}")
    for k, v in skipped.items():
        print(f"  overgeslagen – {k}: {v}")


def make_review(cands: list[dict]):
    thumbs = CACHE / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    for c in cands:
        t = thumbs / (c["sha1"][:16] + ".jpg")
        c["thumb"] = "cache/thumbs/" + t.name
        if not t.exists():
            try:
                with Image.open(COLLECTION / c["path"]) as im:
                    im.draft("RGB", (320, 320))
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    im.thumbnail((240, 240))
                    im.save(t, quality=80)
            except Exception:  # noqa: BLE001
                pass
    ov = load_json(OVERRIDES, {"exclude": [], "include": []})
    rows = [{"p": c["path"], "t": c["thumb"], "y": c["years"], "v": c["verdict"],
             "why": f"{c['why']} · jaar uit {c.get('src', 'keyword')}", "n": bool(c.get("new"))} for c in cands]
    html = (HERE / "review_template.html").read_text(encoding="utf-8")
    html = html.replace("/*DATA*/", json.dumps({"rows": rows, "ov": ov, "fm": file_manager_name()}, ensure_ascii=False))
    (DATA / "review.html").write_text(html, encoding="utf-8")
    print(f"controlepagina: {DATA / 'review.html'}")


# --- eerste gebruik: setup, check, demo ---------------------------------------


def ask(question: str, default: str = "") -> str:
    answer = input(f"{question}" + (f" [{default}]" if default else "") + ": ").strip()
    return answer or default


def cmd_setup():
    """Stelt de vragen die nodig zijn en schrijft config.json (naast build.py, of op --config)."""
    if CONFIG_PATH.exists() and ask(f"{CONFIG_PATH.name} bestaat al. Overschrijven? (j/n)", "n").lower() not in ("j", "ja", "y"):
        return
    print("Fotojaar instellen. Enter = de voorgestelde waarde.\n")
    coll = ""
    while not coll or not Path(coll).is_dir():
        coll = ask("Map met je foto's").strip('"')
        if coll and not Path(coll).is_dir():
            print("  die map bestaat niet")
    print("\nWaar staat het jaartal van je foto's?\n"
          "  1 = in de map- of bestandsnaam (bv. '1952 Processie/foto.jpg' of 'Kermis_1968.jpg')\n"
          "  2 = in een lijst (Excel/CSV) die ik samen met jou invul\n"
          "  3 = in de foto's zelf (keywords/datum in de metadata; vereist exiftool)")
    choice = ask("Kies 1, 2, 3 of een combinatie zoals 12", "1")
    sources = [name for digit, name in (("1", "path"), ("2", "csv"), ("3", "metadata")) if digit in choice] or ["path"]
    code = ""
    while code not in ("nl", "en"):
        code = ask("Taal van de website / website language (nl of en)", "nl").lower()
    title = ask("Titel van de website", "Fotojaar")
    name = ask("Naam van de collectie (voor 'Foto's uit …', mag leeg)")
    url = ask("Adres waar de website komt te staan (mag leeg, bv. https://naam.github.io/fotojaar/)")
    cfg = {"collection": coll.replace("\\", "/"), "lang": code, "year_sources": sources, "site_url": url,
           "publish": "zip", "site": {"title": title, "collection_name": name},
           "obf_key": secrets.token_hex(8), "salt": secrets.token_hex(8)}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nOpgeslagen in {CONFIG_PATH}. Volgende stappen:")
    if "csv" in sources:
        print("  python build.py init-csv     (vul photos.csv aan met de jaartallen)")
    if "metadata" in sources:
        print("  python build.py scan")
    print("  python build.py analyze\n  python build.py build\n  python build.py publish")
    print("Controle van de installatie:  python build.py check")


def cmd_check():
    """Controleert de installatie en toont hoeveel foto's een jaartal hebben."""
    ok = True

    def line(good: bool, text: str):
        nonlocal ok
        ok &= good
        print(("  ok  " if good else "  !!  ") + text)

    line(sys.version_info >= (3, 9), f"Python {sys.version.split()[0]}")
    line(True, f"Pillow {Image.__version__}")
    line(CONFIG_PATH.exists(), f"config: {CONFIG_PATH}" + ("" if CONFIG_PATH.exists() else " (maak het met: python build.py setup)"))
    if COLLECTION is None:
        line(False, "'collection' ontbreekt in config.json")
        return
    line(COLLECTION.is_dir(), f"collectiemap: {COLLECTION}")
    if not COLLECTION.is_dir():
        return
    line(TEMPLATE.is_dir(), f"sitebronnen: {TEMPLATE}")
    if "metadata" in YEAR_SOURCES:
        try:
            line(True, f"exiftool: {exiftool()}")
        except SystemExit as e:
            line(False, str(e))
    if "csv" in YEAR_SOURCES:
        line(CSV_FILE.exists(), f"fotolijst: {CSV_FILE.name}" + ("" if CSV_FILE.exists() else " (maak het met: python build.py init-csv)"))
        if CSV_FILE.suffix.lower() == ".xlsx":
            try:
                import openpyxl  # noqa: F401
                line(True, "openpyxl (voor .xlsx)")
            except ImportError:
                line(False, "openpyxl ontbreekt: pip install openpyxl")
    images = walk_images()
    line(bool(images), f"{len(images)} afbeeldingen in de collectie")
    if not images:
        return
    meta_path = CACHE / "meta.json"
    meta = {rel(r["SourceFile"]): r for r in json.loads(meta_path.read_text(encoding="utf-8-sig"))} if meta_path.exists() else {}
    if "metadata" in YEAR_SOURCES and not meta:
        line(False, "nog geen metadata ingelezen: python build.py scan")
    db, manual = read_db(), load_json(OVERRIDES, {}).get("jaar", {})
    with_year = 0
    for rp in images:
        with_year += bool(resolve_years(meta.get(rp, {}), rp, db, manual)[0])
    line(with_year > 0, f"{with_year} van {len(images)} foto's hebben een jaartal (bronnen: {', '.join(YEAR_SOURCES)})")
    if with_year and with_year < 2 * PER_WEEK:
        line(False, f"minstens {2 * PER_WEEK} foto's nodig voor een aantal weken")
    print("\nAlles in orde." if ok else "\nLos de punten met !! op en voer 'check' opnieuw uit.")


def cmd_demo():
    """Maakt een kleine demo-instantie in demo/ (eigen config, planning en cache) met gegenereerde
    afbeeldingen, en bouwt de site in demo/dist. Raakt je eigen instantie niet aan."""
    demo = HERE.parent / "demo"
    if demo.exists():
        sys.exit(f"{demo} bestaat al: verwijder de map om opnieuw te beginnen.")
    rng = random.Random(7)
    plan = {"1935 Dorpsplein": 4, "1952 Processie": 5, "1968 Kermis": 5, "1981 Schoolfeest": 5, "1994 Sportdag": 5}
    for folder, n in plan.items():
        for i in range(n):
            base = [rng.randrange(70, 200) for _ in range(3)]
            im = Image.new("RGB", (800, 600))
            px = im.load()
            for y in range(600):
                for x in range(0, 800):
                    f = (x + y) / 1400
                    px[x, y] = tuple(int(c * (0.6 + 0.4 * f)) for c in base)
            (demo / "fotos" / folder).mkdir(parents=True, exist_ok=True)
            im.save(demo / "fotos" / folder / f"foto{i + 1}.jpg", quality=85)
    cfg = {"collection": (demo / "fotos").as_posix(), "year_sources": ["path"], "site_dir": "dist",
           "publish": "zip", "detect_backs": False, "site": {"title": "Demo-fotojaar", "collection_name": "de demo"}}
    (demo / "config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print(f"demo-instantie in {demo}. Nu bouwen…")
    for step in (["analyze", "--no-serve"], ["build"]):
        subprocess.run([sys.executable, str(HERE / "build.py"), "--config", str(demo / "config.json"), *step], check=True)
    print(f"\nKlaar: open {demo / 'dist' / 'index.html'} via een webserver, bv.\n"
          f"  python -m http.server 8000 --directory \"{demo / 'dist'}\"   en ga naar http://localhost:8000")


# --- stap 3: build ------------------------------------------------------------


def obfuscate(obj) -> str:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    key = OBF_KEY.encode()
    # app.js decodeert per byte (latin-1) en daarna UTF-8, dus XOR op bytes
    x = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return base64.b64encode(x).decode()


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def adopt_download(stem: str, target: Path, keys: set[str]):
    """review.html en verhalen.html bewaren hun JSON via de browser in Downloads;
    neem de nieuwste versie over als die recenter is dan het bestand in tools/."""
    dl = sorted((Path.home() / "Downloads").glob(f"{stem}*.json"), key=lambda p: p.stat().st_mtime)
    if not dl:
        return
    newest = dl[-1]
    if target.exists() and newest.stat().st_mtime <= target.stat().st_mtime:
        return
    data = json.loads(newest.read_text(encoding="utf-8"))
    if not keys <= data.keys():
        return
    write_json(target, data, indent=1)
    for p in dl:
        p.unlink()
    print(f"{target.name} overgenomen uit {newest}")


KEYWORDS_CFG = DATA / "keywords.json"
CODE_RE = re.compile(r"^\d{4}[A-Z]{1,5}\d*$")      # aankoopcodes zoals 2012WH1, 2016X2
INV_RE = re.compile(r"^[A-Z]{1,3}\d{2,}$")           # inventarisnummers zoals A043


def load_meta(paths: set[str]) -> dict[str, dict]:
    """Metadata uit cache/meta.json voor de gevraagde relatieve paden."""
    meta_path = CACHE / "meta.json"
    out = {rp: {} for rp in paths}
    if meta_path.exists():
        for r in json.loads(meta_path.read_text(encoding="utf-8-sig")):
            try:
                rp = rel(r["SourceFile"])
            except ValueError:
                continue
            if rp in paths:
                out[rp] = r
    return out


def read_descriptions(paths=()) -> dict[str, str]:
    """Beschrijving per relatief pad: FotoLineage (photos.description), anders 'beschrijving' of
    'titel' uit de fotolijst."""
    out = {}
    if FL_DB and FL_DB.exists():
        con = sqlite3.connect(f"file:{FL_DB}?mode=ro", uri=True)
        out = {fp.replace("\\", "/"): d.strip()
               for fp, d in con.execute("select filepath, description from photos where description is not null")
               if d and d.strip()}
    for p in paths:
        row = csv_row(p)
        text = row.get("description") or row.get("title")
        if text and p not in out:
            out[p] = text
    return out


def read_stories(paths=()) -> dict[str, str]:
    """Verhalen per pad: verhalen.json, aangevuld met de kolom 'verhaal' uit de fotolijst."""
    stories = dict(load_json(STORIES, {"verhalen": {}})["verhalen"])
    for p in paths:
        text = csv_row(p).get("story")
        if text and not stories.get(p, "").strip():
            stories[p] = text
    return stories


def already_in(desc: str, story: str, threshold: float = .8) -> bool:
    """Staat de beschrijving al (grotendeels) in het verhaal? Tolereert kleine
    correcties, zoals 'Edèle' -> 'Adèle' of een toegevoegd woord."""
    if not story:
        return False
    d, s = desc.casefold(), story.casefold()
    if d in s:
        return True
    import difflib
    sm = difflib.SequenceMatcher(None, d, s, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(d) >= threshold


def fix_mojibake(s: str) -> str:
    """IPTC-keywords zonder UTF-8-vlag: 'CitroÃ«n' -> 'Citroën'."""
    if any(ch in s for ch in "ÃÂ"):
        try:
            return s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return s


def keyword_labels(meta_by_path: dict) -> dict[str, list]:
    """Per foto de publieke keywords als [label, url|None], zonder interne of verklappende."""
    cfg = load_json(KEYWORDS_CFG, {"verberg": [], "links": {}})
    hide = {k.casefold() for k in cfg.get("verberg", [])}
    links = {k.casefold(): v for k, v in cfg.get("links", {}).items()}

    def raw(path: str) -> list[str]:
        rec = meta_by_path.get(path, {})
        folders = {part.casefold() for part in path.split("/")[:-1]}
        out = []
        items = [rec.get(k) for k in ("XMP-dc:Subject", "IPTC:Keywords")]
        items.append([x.strip() for x in re.split(r"[,;|]", csv_row(path).get("keywords", "")) if x.strip()])
        for value in items:
            for item in as_list(value):
                for kw in re.split(r",(?! )", item):          # "Loos,vrouw" -> 2, "Lippens, Paul" blijft
                    kw = fix_mojibake(kw.strip())
                    f = kw.casefold()
                    if (not kw or "�" in kw or f in hide or f in folders or kw.isdigit()
                            or CODE_RE.match(kw) or INV_RE.match(kw)
                            or f.startswith(("collectie", "collecti "))):
                        continue
                    out.append(kw)
        return out

    per_photo = {p: raw(p) for p in meta_by_path}

    # één schrijfwijze voor de hele collectie: de meest gebruikte, bij gelijkstand
    # die met een hoofdletter (Brussel boven brussel, Brugge boven BRugge)
    from collections import Counter
    variants: dict[str, Counter] = defaultdict(Counter)
    for kws in per_photo.values():
        for kw in kws:
            variants[kw.casefold()][kw] += 1
    canon = {f: max(c, key=lambda v: (c[v], v[:1].isupper() and not v[1:2].isupper(), v)) for f, c in variants.items()}

    result = {}
    for p, kws in per_photo.items():
        seen, out = set(), []
        for kw in kws:
            f = kw.casefold()
            if f in seen:
                continue
            seen.add(f)
            out.append(links.get(f, [canon[f], None]))
        result[p] = out
    return result


def adopt_downloaded_overrides():
    # review.html kent alleen exclude/include: handmatige jaartallen bewaren
    jaar = load_json(OVERRIDES, {}).get("jaar", {})
    adopt_download("overrides", OVERRIDES, {"exclude", "include"})
    ov = load_json(OVERRIDES, {})
    if jaar and "jaar" not in ov:
        ov["jaar"] = jaar
        write_json(OVERRIDES, ov, indent=1)


def mix_weeks(paths: list[str], cands: dict) -> list[str]:
    """Verdeel foto's over weken van PER_WEEK zodat elke week een spreiding in jaartallen heeft:
    sorteer op jaartal, maak PER_WEEK even grote groepen (oud -> recent) en geef elke week
    één foto uit elke groep. Bijna-dubbels (zelfde map + zelfde jaartal) niet in dezelfde week.
    Deterministisch: dezelfde invoer geeft dezelfde verdeling."""
    rng = random.Random("fotojaar-mix")
    mid = lambda p: sum(cands[p]["years"]) / 2
    srt = sorted(paths, key=lambda p: (mid(p), p))
    extra_n = len(srt) % PER_WEEK
    # de rest (onvolledige laatste week) verspreid over alle jaartallen kiezen
    idx = {int((i + .5) * len(srt) / extra_n) for i in range(extra_n)} if extra_n else set()
    extra = [p for i, p in enumerate(srt) if i in idx]
    rng.shuffle(extra)
    srt = [p for i, p in enumerate(srt) if i not in idx]
    n = len(srt) // PER_WEEK
    groups = [srt[k * n:(k + 1) * n] for k in range(PER_WEEK)]
    for g in groups:
        rng.shuffle(g)
    weeks = [[groups[k][w] for k in range(PER_WEEK)] for w in range(n)]

    def sig(p):
        return (p.rsplit("/", 1)[0], tuple(cands[p]["years"]))

    def conflicts(week):
        s = [sig(p) for p in week]
        return len(s) - len(set(s))

    # bijna-dubbels wegwisselen met een foto uit dezelfde groep in een andere week
    for _ in range(3):
        for w in range(n):
            for k in range(PER_WEEK):
                if conflicts(weeks[w]) == 0:
                    break
                others = [x for x in weeks[w] if x is not weeks[w][k]]
                if sig(weeks[w][k]) not in {sig(x) for x in others}:
                    continue
                for v in rng.sample(range(n), n):
                    if v == w:
                        continue
                    a, b = weeks[w][k], weeks[v][k]
                    weeks[w][k], weeks[v][k] = b, a
                    if conflicts(weeks[w]) == 0 and conflicts(weeks[v]) == 0:
                        break
                    weeks[w][k], weeks[v][k] = a, b
    out = []
    for week in weeks:
        week = week[:]
        rng.shuffle(week)            # oudste staat niet altijd eerst
        out += week
    return out + extra


def cmd_build():
    cands = load_json(CACHE / "candidates.json", None)
    if cands is None:
        sys.exit("eerst 'analyze' draaien")
    adopt_downloaded_overrides()
    adopt_download("verhalen", STORIES, {"verhalen"})
    ov = load_json(OVERRIDES, {"exclude": [], "include": []})
    exc, inc = set(ov.get("exclude", [])), set(ov.get("include", []))
    eligible = {c["path"]: c for c in cands
                if (c["verdict"] == "include" or c["path"] in inc) and c["path"] not in exc}
    for p, y in ov.get("jaar", {}).items():      # handmatig jaartal gaat altijd voor
        if p in eligible:
            eligible[p]["years"] = [int(y), int(y)]

    sched = load_json(SCHEDULE, {"start": monday(date.today()).isoformat(), "order": []})
    order: list[str] = sched["order"]
    rng = random.Random()
    pool = [p for p in eligible if p not in set(order)]
    rng.shuffle(pool)
    # posities met een foto die niet meer in aanmerking komt: ter plaatse vervangen
    new_order = []
    for p in order:
        if p in eligible:
            new_order.append(p)
        elif pool:
            new_order.append(pool.pop())
    new_order += pool
    # Vanaf week (huidige + 2) de weken opnieuw verdelen voor een mooie mix van jaartallen.
    # De lopende en de volgende week blijven vast.
    current = max(0, (date.today() - date.fromisoformat(sched["start"])).days // 7)
    locked = min(len(new_order), (current + 2) * PER_WEEK)
    new_order = new_order[:locked] + mix_weeks(new_order[locked:], eligible)
    sched["order"] = new_order
    write_json(SCHEDULE, sched, indent=1)

    stories = read_stories(new_order)
    kw_labels = keyword_labels(load_meta(set(eligible)))
    descriptions = read_descriptions(new_order)

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    items, used = [], set()
    for i, p in enumerate(new_order):
        c = eligible[p]
        name = hashlib.sha1((SALT + p).encode()).hexdigest()[:14] + ".jpg"
        used.add(name)
        out = IMG_DIR / name
        if not out.exists():
            with Image.open(COLLECTION / p) as im:
                im = ImageOps.exif_transpose(im)
                icc = im.info.get("icc_profile")
                im = im.convert("RGB")
                im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
                # geen exif/xmp/iptc: die bevatten het jaartal
                im.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True,
                        **({"icc_profile": icc} if icc else {}))
        with Image.open(out) as im:
            w, h = im.size
        secret = {"y": c["years"], "c": c.get("caption", "")}
        story = stories.get(p, "").strip()
        desc = descriptions.get(p, "")
        if desc and not already_in(desc, story):
            story = f"{desc}\n{story}" if story else desc
        if story:
            secret["v"] = story
        # keywords als labels; een link die al in het verhaal staat niet herhalen
        kws = [kl for kl in kw_labels.get(p, []) if not (kl[1] and kl[1] in story)]
        if kws:
            secret["k"] = kws
        items.append({"f": "img/" + name, "w": w, "h": h, "s": obfuscate(secret)})
        if i % 50 == 0:
            print(f"  {i}/{len(new_order)}")

    for f in IMG_DIR.glob("*.jpg"):  # verweesde afbeeldingen opruimen
        if f.name not in used:
            f.unlink()

    ys = [c["years"] for c in eligible.values()]
    lo = min(y[0] for y in ys) // 10 * 10
    hi = -(-max(y[1] for y in ys) // 10) * 10
    write_json(SITE / "data" / "photos.json", {
        "start": sched["start"], "perWeek": PER_WEEK, "minYear": lo, "maxYear": hi,
        "key": OBF_KEY, "items": items,
    })
    if RENDER_SITE:
        render_site()
    make_og()
    make_icons()
    make_ics(sched["start"])
    n_st = sum(1 for p in new_order if stories.get(p, "").strip())
    print(f"verhalen: {n_st} van {len(new_order)} foto's")
    weeks = len(items) // PER_WEEK
    print(f"{len(items)} foto's -> {weeks} weken ({weeks // 52} jaar en {weeks % 52} weken), "
          f"bereik {lo}–{hi}, start {sched['start']}")


_lang_cache: dict | None = None


def lang() -> dict:
    """Teksten van de website: site_template/lang/<lang>.json, aangevuld/overschreven door 'texts' in config.json."""
    global _lang_cache
    if _lang_cache is None:
        f = TEMPLATE / "lang" / f"{LANG}.json"
        if not f.exists():
            sys.exit(f"Taal '{LANG}' bestaat niet: kies uit " + ", ".join(sorted(x.stem for x in (TEMPLATE / "lang").glob("*.json"))))
        _lang_cache = {k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items() if not k.startswith("_")}
        _lang_cache.update(CFG.get("texts", {}))
    return _lang_cache


def t(key: str, **kw) -> str:
    """Tekst uit het taalbestand; {naam} wordt ingevuld, key_one wordt gebruikt bij n = 1."""
    d = lang()
    text = d.get(key + "_one") if kw.get("n") == 1 and key + "_one" in d else d[key]
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def number_word(n: int, capital: bool = False) -> str:
    words = lang()["number_words"]
    w = words[n] if 0 < n < len(words) else str(n)
    return w[:1].upper() + w[1:] if capital else w


def site_values() -> tuple[dict, dict]:
    """Waarden en aan/uit-blokken voor de sjablonen in site_template/."""
    import html as _html
    esc = lambda v: _html.escape(str(v), quote=True)
    coll = SITE_CFG.get("collection_name", "")
    learn = SITE_CFG.get("learn") or {}
    analytics = SITE_CFG.get("goatcounter", "")
    word = number_word(PER_WEEK)
    credit = SITE_CFG.get("credit_html") or (t("credit_default", name=esc(coll)) if coll else "")
    fill = dict(title=esc(TITLE), n=word, name=esc(coll), learn_name=esc(learn.get("name", "")),
                **{"from": t("from_collection", name=esc(coll)) if coll else ""})
    values = {
        "lang": lang()["lang"], "og_locale": SITE_CFG.get("og_locale") or lang()["og_locale"],
        "title": esc(TITLE),
        "og_title_json": json.dumps(t("og_title", title=TITLE), ensure_ascii=False)[1:-1],
        "title_json": json.dumps(TITLE, ensure_ascii=False)[1:-1],
        "manifest_description_json": json.dumps(t("manifest_description", n=word), ensure_ascii=False)[1:-1],
        "site_url": SITE_URL,
        "credit": credit + " · " if credit else "",
        "learn_url": esc(learn.get("url", "")), "learn_name": esc(learn.get("name", "")),
        "goatcounter": esc(analytics),
    }
    values.update({"t." + k: t(k, **fill) for k, v in lang().items() if isinstance(v, str)})
    flags = {"LEARN": bool(learn.get("url")), "ANALYTICS": bool(analytics)}
    return values, flags


def lang_js() -> bytes:
    """lang.js: de teksten voor app.js (window.I18N), met de titel erbij."""
    d = dict(lang(), title=TITLE, per_week=PER_WEEK, count_word=number_word(PER_WEEK, True),
             per_week_word=number_word(PER_WEEK))
    return ("window.I18N = " + json.dumps(d, ensure_ascii=False, indent=1) + ";\n").encode("utf-8")


def render_template(text: str, values: dict, flags: dict) -> str:
    for name, on in flags.items():
        text = re.sub(rf"<!--\?{name}-->(.*?)<!--/{name}-->", lambda m: m.group(1) if on else "", text, flags=re.S)
    if not values["site_url"]:                       # zonder adres: geen canonical/og:url/og:image
        text = "".join(l for l in text.splitlines(True) if "{{site_url}}" not in l)
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def render_site(dest: Path | None = None):
    """Schrijft de website-bestanden (pagina, manifest, script, stijl, lettertypen) uit site_template/
    naar site_dir. Bestanden die ongewijzigd zijn blijven onaangeroerd."""
    dest = dest or SITE
    if not TEMPLATE.is_dir():
        sys.exit(f"Map {TEMPLATE} ontbreekt.")
    values, flags = site_values()
    dest.mkdir(parents=True, exist_ok=True)
    for src in sorted(TEMPLATE.rglob("*")):
        if not src.is_file() or (src.name == "count.js" and not values["goatcounter"]) \
                or src.relative_to(TEMPLATE).parts[0] == "lang":
            continue
        out = dest / src.relative_to(TEMPLATE)
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in (".html", ".webmanifest"):
            data = render_template(src.read_bytes().decode("utf-8"), values, flags).encode("utf-8")
        else:
            data = src.read_bytes()
        if not out.exists() or out.read_bytes() != data:
            out.write_bytes(data)
    out = dest / "lang.js"
    if not out.exists() or out.read_bytes() != lang_js():
        out.write_bytes(lang_js())


def find_font(names: list[str], size: int):
    """Eerste bestaande lettertype; anders het ingebouwde lettertype van Pillow."""
    from PIL import ImageFont
    dirs = [Path(r"C:\Windows\Fonts"), Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),
            Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/dejavu"), Path.home() / ".fonts"]
    for n in names:
        for d in dirs:
            if (d / n).exists():
                return ImageFont.truetype(str(d / n), size)
    return ImageFont.load_default(size)


def make_og(force: bool = False):
    """Linkvoorbeeld voor Facebook/WhatsApp/…: 1200×630, site/og.jpg."""
    from PIL import ImageDraw, ImageFont, ImageFilter
    out = SITE / "og.jpg"
    if out.exists() and not force:
        return
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), "#f4efe6")
    title = find_font(["georgiab.ttf", "Georgia Bold.ttf", "DejaVuSerif-Bold.ttf"], 104)
    sub = find_font(["segoeui.ttf", "Arial.ttf", "DejaVuSans.ttf"], 36)
    url = find_font(["segoeuib.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"], 30)
    title_size = 104
    while title.getlength(TITLE) > 600 and title_size > 40:        # lange titels verkleinen
        title_size -= 8
        title = find_font(["georgiab.ttf", "Georgia Bold.ttf", "DejaVuSerif-Bold.ttf"], title_size)
    # drie foto's als losse afdrukken, licht gedraaid
    spots = [(700, 70, -7), (880, 120, 5), (760, 300, -2)]
    for rp, (x, y, ang) in zip(OG_PHOTOS, spots):
        with Image.open(COLLECTION / rp) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            w, h = im.size
            im = im.crop((0, 0, w, int(h * .78)))  # potloodjaartal onderaan wegsnijden
            im.thumbnail((300, 300))
        card = Image.new("RGB", (im.width + 24, im.height + 24), "#fbf8f2")
        card.paste(im, (12, 12))
        card = card.convert("RGBA").rotate(ang, expand=True, resample=Image.BICUBIC)
        shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
        shadow.paste((60, 40, 20, 90), mask=card.split()[3])
        shadow = shadow.filter(ImageFilter.GaussianBlur(10))
        img.paste(shadow, (x + 8, y + 12), shadow)
        img.paste(card, (x, y), card)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((70, 150, 118, 190), 5, fill="#8a5a2b")
    d.rectangle((76, 156, 112, 184), fill="#f4efe6")
    d.ellipse((85, 161, 103, 179), fill="#8a5a2b")
    d.text((70, 200), TITLE, font=title, fill="#2b2420")
    d.text((72, 330), t("og_line1", n=number_word(PER_WEEK)), font=sub, fill="#5a4d42")
    d.text((72, 376), t("og_line2"), font=sub, fill="#5a4d42")
    d.text((72, 470), re.sub(r"^https?://|/$", "", SITE_URL), font=url, fill="#8a5a2b")
    img.save(out, quality=88, optimize=True)
    print(f"linkvoorbeeld -> {out}")


def make_icons():
    """App-icoontjes (PWA / beginscherm) in site/icons/."""
    from PIL import ImageDraw
    d_out = SITE / "icons"
    d_out.mkdir(exist_ok=True)

    def draw(size: int, safe: float) -> Image.Image:
        S = 1024
        im = Image.new("RGB", (S, S), "#f4efe6")
        d = ImageDraw.Draw(im)
        m = S * (1 - safe) / 2           # marge rond het merkteken
        w = S - 2 * m
        x0, y0, x1, y1 = m, m + w * .1, S - m, S - m - w * .1
        d.rounded_rectangle((x0, y0, x1, y1), radius=w * .08, fill="#8a5a2b")
        b = w * .1
        d.rectangle((x0 + b, y0 + b, x1 - b, y1 - b), fill="#f4efe6")
        r = w * .2
        cx, cy = S / 2, S / 2
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill="#8a5a2b")
        return im.resize((size, size), Image.LANCZOS)

    draw(192, .78).save(d_out / "icon-192.png", optimize=True)
    draw(512, .78).save(d_out / "icon-512.png", optimize=True)
    draw(512, .56).save(d_out / "maskable-512.png", optimize=True)   # veilige zone voor Android
    draw(180, .70).save(d_out / "apple-touch-icon.png", optimize=True)


def make_ics(start: str):
    """Wekelijkse agendaherinnering (elke maandag 9u) als site/fotojaar.ics."""
    d = start.replace("-", "")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{TITLE}//{LANG.upper()}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{TITLE}",
        "BEGIN:VTIMEZONE", "TZID:Europe/Brussels",
        "BEGIN:DAYLIGHT", "TZOFFSETFROM:+0100", "TZOFFSETTO:+0200", "TZNAME:CEST",
        "DTSTART:19700329T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU", "END:DAYLIGHT",
        "BEGIN:STANDARD", "TZOFFSETFROM:+0200", "TZOFFSETTO:+0100", "TZNAME:CET",
        "DTSTART:19701025T030000", "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU", "END:STANDARD",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        f"UID:fotojaar-wekelijks@{urlparse(SITE_URL).netloc or 'fotojaar.local'}",
        f"DTSTAMP:{d}T000000Z",
        f"DTSTART;TZID=Europe/Brussels:{d}T090000",
        f"DTEND;TZID=Europe/Brussels:{d}T091500",
        "RRULE:FREQ=WEEKLY;BYDAY=MO",
        "SUMMARY:" + t("ics_summary", title=TITLE),
        "DESCRIPTION:" + t("ics_description", count=number_word(PER_WEEK, True)) + (f"\\n{SITE_URL}" if SITE_URL else ""),
        *([f"URL:{SITE_URL}"] if SITE_URL else []),
        "TRANSP:TRANSPARENT",
        "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + t("ics_summary", title=TITLE), "TRIGGER:PT0M", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR",
    ]
    (SITE / "fotojaar.ics").write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


def file_manager_name() -> str:
    return {"Windows": "Verkenner", "Darwin": "Finder"}.get(platform.system(), "bestandsbeheer")


def reveal_in_file_manager(path: Path):
    """Toon het bestand in Verkenner (Windows), Finder (macOS) of open de map (Linux)."""
    system = platform.system()
    if system == "Windows":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif system == "Darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def serve_page(page: Path, port: int = 8787):
    """Serveer de pagina alleen op 127.0.0.1, met /open om een foto in het bestandsbeheer te tonen.
    Veiligheid: alleen localhost, geheime token per sessie, controle op Host-header en op het pad
    (moet een bestaand bestand binnen de collectie zijn)."""
    token = secrets.token_urlsafe(16)
    root = DATA.resolve()
    coll = COLLECTION.resolve()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def host_ok(self):
            return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

        def send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.host_ok():
                return self.send(403)
            path = self.path.split("?")[0]
            served = {"/": page, "/review.html": DATA / "review.html", "/verhalen.html": DATA / "verhalen.html"}
            if path in served and served[path].is_file():
                html = served[path].read_text(encoding="utf-8").replace("__TOKEN__", token)
                return self.send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            f = (root / path.lstrip("/").replace("%20", " ")).resolve()
            if f.is_file() and root in f.parents and f.parent.name == "thumbs":
                return self.send(200, f.read_bytes(), "image/jpeg")
            self.send(404)

        def do_POST(self):
            if not self.host_ok() or self.path != "/open" or self.headers.get("X-Token") != token:
                return self.send(403)
            try:
                rp = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))["p"]
                f = (COLLECTION / rp).resolve()
                if coll not in f.parents or not f.is_file():
                    return self.send(404, b"niet gevonden")
                reveal_in_file_manager(f)
                self.send(200, b"ok")
            except Exception as e:  # noqa: BLE001
                self.send(400, str(e).encode("utf-8"))

    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:                       # poort bezet: een vrije poort nemen
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}/{page.name}"
    print(f"Pagina staat op {url}")
    bezig, klaar = (("nakijkt", "Klik eerst op 'Bewaar overrides.json'.") if page.name == "review.html"
                    else ("verhalen schrijft", "Klik eerst op 'Bewaar verhalen.json'."))
    print(f"Blijf dit venster open zolang je {bezig}. {klaar}")
    print("Ben je klaar? Druk hier op Ctrl+C om te stoppen en ga verder met: python build.py build")
    threading.Timer(.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("gestopt")


def cmd_verhalen(serve: bool = True):
    """Maakt tools/verhalen.html: per foto (in weekvolgorde) een verhaal schrijven.
    Standaard wordt de pagina ook geserveerd (127.0.0.1) zodat foto's in Verkenner/Finder te openen zijn."""
    sched = load_json(SCHEDULE, None)
    cands = {c["path"]: c for c in load_json(CACHE / "candidates.json", [])}
    if not sched or not cands:
        sys.exit("eerst 'analyze' en 'build' draaien")
    adopt_download("verhalen", STORIES, {"verhalen"})
    stories = read_stories(sched["order"])
    db = read_descriptions(sched["order"])
    kw_labels = keyword_labels(load_meta(set(sched["order"])))
    start = date.fromisoformat(sched["start"])
    rows = []
    for i, p in enumerate(sched["order"]):
        c = cands.get(p, {})
        wk = i // PER_WEEK
        rows.append({
            "p": p, "wk": wk + 1, "d": (start + timedelta(weeks=wk)).isoformat(),
            "t": f"cache/thumbs/{c.get('sha1', '')[:16]}.jpg", "y": c.get("years", []),
            # zonder verhaal: volledige FotoLineage-beschrijving als vertrekpunt
            "c": c.get("caption", ""), "o": db.get(p, ""), "v": stories.get(p) or db.get(p, ""),
            "k": kw_labels.get(p, []),
        })
    html = (HERE / "verhalen_template.html").read_text(encoding="utf-8")
    html = html.replace("/*DATA*/", json.dumps({"rows": rows, "today": date.today().isoformat(),
                                                    "fm": file_manager_name()}, ensure_ascii=False))
    (DATA / "verhalen.html").write_text(html, encoding="utf-8")
    print(f"verhalenpagina: {DATA / 'verhalen.html'}")
    if serve:
        serve_page(DATA / "verhalen.html")


def cmd_publish(message: str = "Foto's bijgewerkt"):
    """Publiceer site_dir volgens 'publish' in config.json:
    git    = commit + push van site_dir (moet zelf een git-repo zijn, bv. voor GitHub Pages);
    folder = kopie naar 'publish_folder' (bv. een gedeelde map of FTP-map);
    zip    = maakt <site_dir>.zip om zelf te uploaden (standaard, en terugval als git niet kan)."""
    mode = PUBLISH_MODE
    if mode == "git" and not (SITE / ".git").exists():
        print(f"{SITE} is geen git-repo: ik maak een zip.")
        mode = "zip"
    if not (SITE / "data" / "photos.json").exists():
        sys.exit("Nog niets te publiceren: voer eerst 'python build.py build' uit.")
    if mode == "git":
        git = ["git", "-C", str(SITE)]
        subprocess.run(git + ["add", "-A"], check=True)
        if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode == 0:
            print("niets gewijzigd, niets te publiceren")
            return
        subprocess.run(git + ["commit", "-m", message], check=True)
        subprocess.run(git + ["push"], check=True)
        print("gepubliceerd – GitHub Pages is binnen een minuut of twee bijgewerkt")
    elif mode == "folder":
        target = CFG.get("publish_folder")
        if not target:
            sys.exit("Zet 'publish_folder' in config.json.")
        target = Path(target)
        shutil.copytree(SITE, target, dirs_exist_ok=True)
        keep = {p.relative_to(SITE).as_posix() for p in SITE.rglob("*") if p.is_file()}
        for old in target.rglob("*.jpg"):                       # verwijderde foto's ook daar opruimen
            if old.relative_to(target).as_posix() not in keep and old.relative_to(target).parts[0] == "img":
                old.unlink()
        print(f"gekopieerd naar {target}")
    else:
        out = shutil.make_archive(str(SITE), "zip", root_dir=SITE)
        print(f"{out}\nUpload de inhoud van dit zipbestand naar je website (zie README, 'Online zetten').")
    mark_seen()


def mark_seen():
    """Alle huidige kandidaten gelden na een publicatie als gecontroleerd (niet meer 'nieuw')."""
    cands = load_json(CACHE / "candidates.json", [])
    if not cands:
        return
    seen = load_json(SEEN, {})
    today = date.today().isoformat()
    for c in cands:
        seen.setdefault(c["path"], today)
    write_json(SEEN, seen, indent=0)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd not in ("help", "setup", "check", "demo") and COLLECTION is None:
        sys.exit(f"Geen collectiemap ingesteld: zet 'collection' in {CONFIG_PATH.name}")
    flags = {a for a in sys.argv[2:] if a.startswith("--")}
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    arg = Path(args[0]) if args else None
    if cmd == "scan":
        cmd_scan(args)
    elif cmd == "analyze":
        cmd_analyze(*( [arg] if arg else []))
        if "--no-serve" not in flags:
            serve_page(DATA / "review.html")
    elif cmd == "review":
        cands = load_json(CACHE / "candidates.json", None)
        if cands is None:
            sys.exit("eerst 'analyze' draaien")
        make_review(cands)
        if "--no-serve" not in flags:
            serve_page(DATA / "review.html")
    elif cmd == "build":
        cmd_build()
    elif cmd == "verhalen":
        cmd_verhalen(serve="--no-serve" not in flags)
    elif cmd == "init-csv":
        cmd_init_csv()
    elif cmd == "setup":
        cmd_setup()
    elif cmd == "check":
        cmd_check()
    elif cmd == "demo":
        cmd_demo()
    elif cmd == "publish":
        cmd_publish(*sys.argv[2:3])
    else:
        print(__doc__)

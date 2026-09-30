# Fotojaar

*Nederlandstalige versie: [README.md](README.md)*

A weekly guessing game for your own old photos: every week five photos, guess the year each was taken. Made for
societies (local history groups, photo clubs, archives) and private collectors. The result is a plain website
(HTML/CSS/JS, no server needed) that you can host anywhere, for example for free on GitHub Pages. Players need no
account; their scores stay in their own browser.

Example: https://peyck.github.io/fotojaar/

> The command-line messages of `build.py` and the review and stories pages are currently in Dutch only. The website
> itself is available in Dutch and English. This guide lists the commands and what they do.

## What you need

- [Python](https://www.python.org/downloads/) 3.9 or newer
- photos (JPEG or TIFF) in a folder, with the year somewhere: in the folder or file name, in a spreadsheet (Excel/CSV),
  or in the photos' metadata (for that you also need [exiftool](https://exiftool.org))

## Quick start

**Windows, no terminal:** unzip the download (see step 1) and double-click `Fotojaar.cmd`. The first time it installs what is
needed (Python via `winget` if missing, plus Pillow and openpyxl) and shows a menu: demo, set up, check, choose photos,
stories, build the website and publish. The commands below are for those who prefer a terminal (and for macOS and Linux).
Note that the menu itself is in Dutch.

1. Download the code: [ZIP file](https://github.com/peyck/fotojaar-toolkit/archive/refs/heads/main.zip) (or on the GitHub page: *Code → Download ZIP*) and unzip it.
2. Open a terminal in the unzipped folder and install the requirements (Pillow):

```
pip install -r requirements.txt
```

   *macOS and Linux:* type `python3` and `pip3` if `python` and `pip` do not exist. On Ubuntu/Debian `pip` refuses to install into
   the system Python and the `venv` module is often missing. Use a virtual environment instead:

   ```
   sudo apt install python3-venv
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   ```

   exiftool (only for the `metadata` source): `brew install exiftool` (macOS) or `sudo apt install libimage-exiftool-perl` (Ubuntu/Debian).

3. Go to the `tools` folder and run:

```
cd tools
python build.py demo       # optional: a small sample site in ../demo, to see what you get
python build.py setup      # asks a few questions and writes config.json
python build.py check      # checks your installation and how many photos have a year
python build.py analyze    # selects the photos and opens a review page in your browser (Ctrl+C to stop)
python build.py build      # creates the website in ../dist
python build.py publish    # creates dist.zip to put online (see below)
```

`setup` asks for the language of the website (`nl` or `en`).

Adding photos later? Add them to the folder and run `analyze`, `build` and `publish` again. Weeks already played and
the coming week stay fixed (see *Weekly schedule*).

**Review page (`analyze`).** You see every selected photo with the year that was found. Green is in the game, red is
not: click to toggle. Mainly exclude back sides of photos and photos where the year is visible. Then click
*Bewaar overrides.json* (save overrides). The *Verkenner/Finder* button shows the file in your file manager; it uses a
small server that only listens on your own computer (`127.0.0.1`) and refuses requests without a secret session token
or for files outside your collection.

**Stories (`verhalen`).** `python build.py verhalen` opens a page to write a short story per photo, shown after the
guess. Click *Bewaar verhalen.json* and run `build` again. Links in a story: paste an address (`https://…`) or write
`[link text](https://…)`.

## Where does the year come from? (`year_sources`)

Set `year_sources` in `config.json`. The sources are tried in the given order (the first one that yields something wins);
`overrides.json → jaar` always wins. Default: `["csv", "metadata", "path"]`.

| Source | What | Needs |
|---|---|---|
| `csv` | a list `tools/photos.csv` (or `.xlsx`, with `"csv": "list.xlsx"`) with columns `pad;jaar;titel;beschrijving;fotograaf;plaats;verhaal;keywords` (path, year, title, description, photographer, place, story, keywords). `pad` is relative to the collection (or just the file name). `jaar` is `1952`, `1950-1955` or `1910~` (±2 years). See *Columns of the list* below. | nothing (`.xlsx` is read by `openpyxl`, installed with `requirements.txt`) |
| `metadata` | keyword year, FotoLineage `CircaDate`, `DateCreated` in the photos' exiftool fields (details in [docs/metadata.md](docs/metadata.md), in Dutch) | exiftool and `python build.py scan` |
| `path` | year in the file name (`Fair_1968.jpg`) or a folder name (`1952 Procession`, `1950-1955`); `path_year_from` decides whether file name, folder or both count | nothing |

**Columns of the list.** The first row holds the column names (case does not matter); only `pad` and `jaar` are required.
The delimiter (`;`, `,` or tab) is detected automatically. The Dutch names are the primary ones; the English names in the last line work too.

| Column | Meaning |
|---|---|
| `pad` (path) | the file, relative to the collection folder (`1952 Procession/photo1.jpg`) or just the file name. If a path appears twice, the last row wins |
| `jaar` (year) | the year: `1952`, a **range** `1950-1955` (every guess from 1950 through 1955 is then correct; a range wider than `max_range`, default 10 years, is skipped) or `1910~` (±2 years) |
| `titel` (title) | shown as the description if `beschrijving` is empty |
| `beschrijving` (description) | text under the photo after guessing |
| `fotograaf`, `plaats` (photographer, place) | caption under the photo (`photographer · place`) |
| `verhaal` (story) | story under the photo; a story in `verhalen.json` takes precedence |
| `keywords` | labels under the photo, separated by a comma or semicolon |

English column names also work: `path`, `year`, `title`, `description`, `photographer`, `place`, `story`, `keywords`.

Without exiftool: `python build.py init-csv` creates `photos.csv` with all photos (year prefilled where it follows from
the path or file name); fill in the rest and run `python build.py analyze` (no `scan` needed).

## Generating and publishing the website

`python build.py build` writes the complete website to `site_dir` (default `dist`, next to `tools`). The source files are
in `site_template/`. Title, collection name, credit line, an optional link to your own website (`site.learn`) and optional
GoatCounter statistics (`site.goatcounter`) are set in the `site` block of `config.json`.

`python build.py publish` does, depending on `publish` in `config.json`:

| Value | What |
|---|---|
| `zip` (default) | creates `dist.zip`; unzip it on your hosting (FTP, Netlify Drop, or GitHub: create a repo, *Add file → Upload files*, drag the contents of `dist` in and enable the branch under *Settings → Pages*) |
| `folder` | copies to `publish_folder` |
| `git` | commit + push of `site_dir`, which must itself be a git repository |

The link preview `og.jpg` is made once with the title, the address and (optionally) photos from `og_photos`. Choose
photos that are **not** in the game, because they are public in the link preview. Delete `og.jpg` to have it recreated.

## Settings (`config.json`)

Only `collection` is required; `config.example.json` shows all keys: `collection`, `lang`, `texts`, `site_dir`,
`render_site`, `publish`, `publish_folder`, `site`, `site_url`, `year_sources`, `csv`, `path_year_from`, `detect_backs`,
`per_week`, `max_side`, `jpeg_quality`, `max_range`, `skip_dirs`, `skip_name_regex`, `skip_ref_regex`, `front_dated_dirs`,
`og_photos`, `exiftool_paths`, `obf_key`, `salt`. **Do not change `obf_key` and `salt` in a running instance**: all image
names would change.

### Language and texts

The website exists in Dutch (`"lang": "nl"`, default) and English (`"lang": "en"`). All texts are in
`site_template/lang/nl.json` and `en.json`. For your own translation, copy one to e.g. `fr.json`, translate the values and
set `"lang": "fr"`. To change a single text without editing the files, use `texts` in `config.json`:

```json
"texts": { "help_li3": "Right year: 1000 points. Every year off costs points." }
```

## Files

- `tools/` – the code: `build.py` (all steps), `review_template.html`, `verhalen_template.html`, `config.example.json`, `tests/`
- `site_template/` – source files of the website (page, script, style, fonts, `lang/`)
- your data, next to `config.json` (by default in `tools/`; with `--config other/config.json` you can run several
  instances, each with its own schedule and cache): `config.json`, `photos.csv`, `schedule.json` (**do not delete or
  reorder by hand**: it decides which photos appear in which week; keep a backup), `overrides.json`, `verhalen.json`
  (stories), `keywords.json` (optional), `cache/`
- `dist/` – the generated website

## Weekly schedule

Week *n* shows photos `5n … 5n+4` from `schedule.json` (or `per_week` photos).

- **The current and the next week are fixed**: what players already saw and what you may already be writing stories for
  does not change.
- **All later weeks** are redistributed at every `build` for a **mix of years**: photos are sorted by year and split
  into equal groups (oldest → newest); every week gets one photo from each group, in random order. Near-duplicates (same
  folder and year) never share a week.
- Once the whole list has been played, the series starts again.

## Points

`1000 × e^(−difference/10)`: exactly right 1000, 2 years off 819, 5 years 607, 10 years 368, 20 years 135.

## Keeping your data private

Your schedule, stories, settings and cache live next to your `config.json`, not next to the code. To track the code with
git but keep your data private, use two folders: this code folder and a separate one (e.g. a private repo) with your
`config.json`, `schedule.json`, `overrides.json`, `verhalen.json` and `photos.csv`. Then start `build.py` with
`python path\to\code\tools\build.py --config path\to\config.json build`. This repo's `.gitignore` excludes those files so
you don't publish them by accident.

## Privacy and rights

- The web images (max. 1600 px) contain **no** EXIF/XMP/IPTC metadata, the file names are hashed and the years in
  `photos.json` are lightly obfuscated. That stops the casual curious, not a determined player: it is not security.
- Only put photos online that you have the rights to, and whose subjects would accept it.
- Choose your own `obf_key` and `salt` in `config.json` and do not change them afterwards.
- Statistics are optional (`site.goatcounter`, [GoatCounter](https://www.goatcounter.com), no cookies).

## License

MIT, see [LICENSE](LICENSE). The fonts Fraunces and Inter have their own licenses (`site_template/fonts/`). Photos remain the property of their rights holders.

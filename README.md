# Fotojaar

*English version: [README.en.md](README.en.md)*

Een wekelijks raadspel voor je eigen oude foto's: elke week vijf foto's, raad in welk jaar ze genomen zijn. Bedoeld voor
verenigingen (heemkringen, fotoclubs, archieven) en privépersonen met een fotocollectie. Het resultaat is een gewone
website (HTML/CSS/JS, geen server nodig) die je overal kunt hosten, bv. gratis op GitHub Pages. Spelers hebben geen
account nodig; hun scores blijven in hun eigen browser.

Voorbeeld: https://peyck.github.io/fotojaar/

## Wat heb je nodig?

- [Python](https://www.python.org/downloads/) 3.9 of nieuwer
- foto's (JPEG, TIFF, PNG of WebP; andere extensies via `image_exts`) in een map, met het jaartal ergens: in de map- of bestandsnaam, in een lijst (Excel/CSV) of in de
  metadata van de foto's (dan heb je ook [exiftool](https://exiftool.org) nodig)

## Snelstart

**Windows, zonder terminal:** pak de ZIP uit (zie stap 1) en dubbelklik op `Fotojaar.cmd`. Dat installeert bij de eerste keer
wat nodig is (Python via `winget` als het ontbreekt, plus Pillow en openpyxl) en toont een menu: demo, instellen, controleren,
foto's kiezen, verhalen, website maken en publiceren. Meer heb je niet nodig; de commando's hieronder zijn voor wie liever
een terminal gebruikt (en voor macOS en Linux).

1. Download de code: [ZIP-bestand](https://github.com/peyck/fotojaar-toolkit/archive/refs/heads/main.zip) (of op de GitHub-pagina: *Code → Download ZIP*) en pak het uit.
2. Open een terminal in de uitgepakte map en installeer de vereisten (Pillow):

```
pip install -r requirements.txt
```

   *macOS en Linux:* typ `python3` en `pip3` als `python` en `pip` niet bestaan. Op Ubuntu/Debian weigert `pip` pakketten in de
   systeem-Python te zetten en ontbreekt vaak de module `venv`. Gebruik dan een virtuele omgeving:

   ```
   sudo apt install python3-venv
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   ```

   exiftool (alleen voor de bron `metadata`): `brew install exiftool` (macOS) of `sudo apt install libimage-exiftool-perl` (Ubuntu/Debian).

3. Ga naar de map `tools` en voer uit:

```
cd tools
python build.py demo       # optioneel: een kleine voorbeeldsite in ../demo, om te zien wat je krijgt
python build.py setup      # stelt een paar vragen en schrijft config.json
python build.py check      # controleert je installatie en hoeveel foto's een jaartal hebben
python build.py analyze    # kiest de foto's en opent een controlepagina in je browser (Ctrl+C om te stoppen)
python build.py build      # maakt de website in ../dist
python build.py publish    # maakt dist.zip om online te zetten (zie hieronder)
```

Nieuwe foto's later? Voeg ze toe aan de map en voer `analyze`, `build` en `publish` opnieuw uit. Wat al gespeeld is en de
volgende week blijven vast (zie *Weekplanning*).

**Controlepagina (`analyze`).** Je ziet elke geselecteerde foto met het gevonden jaartal. Groen komt in het spel, rood
niet: klik om te wisselen. Vooral achterzijdes van foto's en foto's waarop het jaartal zichtbaar staat wil je hier
uitsluiten. Klik daarna *Bewaar overrides.json*. Met de knop *📂 Verkenner* (macOS: *Finder*) open je het bestand. Dat werkt
via een klein servertje dat enkel op jouw computer luistert (`127.0.0.1`) en verzoeken zonder geheime sessietoken of naar
bestanden buiten je collectie weigert.

**Verhalen (`verhalen`).** `python build.py verhalen` opent een pagina om per foto een verhaal te schrijven, dat na het raden
verschijnt. Klik *Bewaar verhalen.json* en voer `build` opnieuw uit. Links in een verhaal: plak een adres (`https://…`) of
schrijf `[linktekst](https://…)`.

## Jaartalbronnen (`year_sources`)

Waar het jaartal van een foto vandaan komt, stel je in met `year_sources` in `config.json`. De bronnen worden in de
opgegeven volgorde geprobeerd (de eerste die iets oplevert telt); `overrides.json → jaar` gaat altijd voor.
Standaard: `["csv", "metadata", "path"]`. Deze instantie gebruikt enkel `["metadata"]`.

| Bron | Wat | Nodig |
|---|---|---|
| `csv` | lijst `tools/photos.csv` (of `.xlsx`, met `"csv": "lijst.xlsx"`) met kolommen `pad;jaar;titel;beschrijving;fotograaf;plaats;verhaal;keywords`. `pad` is relatief t.o.v. de collectie (of enkel de bestandsnaam). `jaar` is `1952`, `1950-1955` of `1910~` (±2 jaar). Zie *Kolommen van de lijst* hieronder. | niets (`.xlsx` leest `openpyxl`, dat met `requirements.txt` is geïnstalleerd) |
| `metadata` | keyword-jaartal, FotoLineage-`CircaDate`, `DateCreated`, in exiftool-velden van je foto's; uitleg in [docs/metadata.md](docs/metadata.md) | exiftool en `python build.py scan` |
| `path` | jaartal in de bestandsnaam (`Kermis_1968.jpg`) of een mapnaam (`1952 Processie`, `1950-1955`); `path_year_from` bepaalt of bestandsnaam, map of beide telt | niets |

**Kolommen van de lijst.** De eerste rij bevat de kolomnamen (hoofdletters maken niet uit); alleen `pad` en `jaar` zijn nodig.
Het scheidingsteken (`;`, `,` of tab) wordt automatisch herkend.

| Kolom | Betekenis |
|---|---|
| `pad` | het bestand, relatief t.o.v. de collectiemap (`1952 Processie/foto1.jpg`) of enkel de bestandsnaam. Staat een pad twee keer in de lijst, dan wint de laatste rij |
| `jaar` | het jaartal: `1952`, een **bereik** `1950-1955` (elke gok van 1950 t.e.m. 1955 is dan juist; een bereik groter dan `max_range`, standaard 10 jaar, wordt overgeslagen) of `1910~` (±2 jaar) |
| `titel` | wordt als beschrijving getoond als `beschrijving` leeg is |
| `beschrijving` | tekst onder de foto na het raden |
| `fotograaf`, `plaats` | onderschrift onder de foto (`fotograaf · plaats`) |
| `verhaal` | verhaal onder de foto; een verhaal in `verhalen.json` gaat voor |
| `keywords` | labels onder de foto, gescheiden door een komma of puntkomma |

De kolomnamen mogen ook Engels zijn: `path`, `year`, `title`, `description`, `photographer`, `place`, `story`, `keywords`.

Zonder exiftool: `python build.py init-csv` maakt `photos.csv` met alle foto's (jaartal vooraf ingevuld waar het uit
pad of bestandsnaam volgt); vul de rest aan en voer `python build.py analyze` uit (`scan` is dan niet nodig).
`beschrijving`, `titel`, `verhaal`, `fotograaf`, `plaats` en `keywords` uit de lijst verschijnen na het raden, net als
de metadata; `verhalen.json` gaat voor op `verhaal` uit de lijst.

Tests: `python -m unittest discover tools/tests`.

## Website genereren en online zetten (`site_dir`, `publish`)

`python build.py build` schrijft de complete website naar `site_dir` (standaard `dist`, naast `tools`): de pagina,
het script, de stijl, lettertypen, de foto's en de planning. De bronbestanden van de website staan in `site_template/`;
titel, collectienaam, bronvermelding, een optionele verwijzing naar een eigen website (`site.learn`) en optionele
GoatCounter-statistiek (`site.goatcounter`) stel je in via het blok `site` in `config.json`. Zonder `site_url`
laat de pagina de linkvoorbeeld-tags weg.

`python build.py publish` doet, afhankelijk van `publish` in `config.json`:

| Waarde | Wat |
|---|---|
| `zip` (standaard) | maakt `dist.zip`: pak dat uit op je hosting (FTP, Netlify Drop, of GitHub: maak een repo, kies *Add file → Upload files*, sleep de inhoud van `dist` erin en zet onder *Settings → Pages* de branch aan) |
| `folder` | kopieert naar `publish_folder` (bv. een gedeelde map of een gesynchroniseerde FTP-map) |
| `git` | commit + push van `site_dir`, dat dan zelf een git-repo moet zijn (deze instantie: `../site` → GitHub Pages) |

Is `site_dir` geen git-repo terwijl `publish` op `git` staat, dan maakt het script een zip. Wil je de pagina zelf
aanpassen? Zet `"render_site": false` en onderhoud `site_dir` dan zelf; `build` raakt de bestanden dan niet aan
(deze instantie doet dat voorlopig).

Het linkvoorbeeld `og.jpg` wordt eenmalig gemaakt met de titel, het adres en (optioneel) foto's uit `og_photos`;
kies daarvoor foto's die **niet** in het spel zitten, want ze staan openbaar in het linkvoorbeeld. Verwijder `og.jpg`
om het opnieuw te laten maken.

## Instellingen (`config.json`)

Alle instellingen die bij een collectie horen staan in `tools/config.json`; `config.example.json` toont een
minimale versie. Enkel `collection` is verplicht. Sleutels: `collection`, `fotolineage_db` (optioneel, relatief
t.o.v. de collectie), `fotolineage_config`, `exiftool_paths`, `site_url`, `per_week`, `max_side`, `jpeg_quality`,
`site_dir`, `render_site`, `publish`, `publish_folder`, `site`, `lang`, `texts`, `year_sources`, `csv`, `path_year_from`, `image_exts`, `max_range`, `circa`, `date_max_year`, `skip_dirs`, `skip_name_regex`, `skip_ref_regex`, `front_dated_dirs`,
`og_photos`, `obf_key`, `salt`. **Wijzig `obf_key` en `salt` niet in een lopende instantie**: alle afbeeldingsnamen
veranderen dan.

### Taal en teksten

De website is beschikbaar in het Nederlands (`"lang": "nl"`, standaard) en het Engels (`"lang": "en"`). Alle teksten staan
in `site_template/lang/nl.json` en `en.json`. Een eigen vertaling? Kopieer een van beide naar bv. `fr.json`, vertaal de
waarden en zet `"lang": "fr"`. Een enkele tekst aanpassen kan zonder de bestanden te wijzigen, via `texts` in `config.json`:

```json
"texts": { "help_li3": "Juist jaar: 1000 punten. Elk jaar ernaast kost punten." }
```

De commando's en meldingen van `build.py` en de controle- en verhalenpagina zijn voorlopig alleen in het Nederlands.

## Bestanden

- `tools/` (de code)
  - `build.py` – alle stappen; `review_template.html` en `verhalen_template.html` zijn de bijhorende pagina's
  - `config.example.json` – voorbeeld van alle instellingen; `tests/` – tests
- `site_template/` – bronbestanden van de website (pagina, script, stijl, lettertypen)
- jouw gegevens, naast `config.json` (standaard in `tools/`; met `--config andere/config.json` heb je meerdere
  instanties, elk met eigen planning en cache)
  - `config.json` – jouw instellingen
  - `photos.csv` – optionele fotolijst
  - `schedule.json` – startmaandag en vaste volgorde van de foto's. **Niet wissen of met de hand herschikken**: dit
    bepaalt welke week welke foto's toont. Bewaar dit bestand veilig (bv. in een privé-repo of back-up)
  - `overrides.json` – handmatige in-/uitsluitingen en jaartallen (via de controlepagina)
  - `verhalen.json` – verhalen per foto
  - `keywords.json` – (optioneel) keywords die verborgen worden en keywords die een link krijgen
  - `cache/` – metadata, miniaturen en `seen.json` (welke kandidaten al gepubliceerd zijn)
- `dist/` – de gegenereerde website (`site_dir`)

Bestanden die de controlepagina en de verhalenpagina in je map Downloads bewaren, worden door `build` automatisch
overgenomen als ze nieuwer zijn.

## Wat verschijnt er na het raden

1. het juiste jaar, de punten en een tijdlijn;
2. onderschrift: fotograaf · plaats (uit FotoLineage of de fotolijst);
3. kader *Achter de foto*:
   - de **beschrijving** (uit FotoLineage of de kolom `beschrijving`/`titel` van de fotolijst; automatisch; niet dubbel als ze – eventueel licht aangepast – al in het verhaal staat);
   - het **verhaal** uit `verhalen.json`;
   - de **keywords** als labels. Verborgen worden: jaartallen, getallen, codes (`2012WH1`, `A043`), `collectie …`,
     mapnamen en alles in `keywords.json` → `verberg`. Keywords in `keywords.json` → `links` worden links;
     staat die link al in het verhaal, dan wordt het label weggelaten.

## Selectie (technisch)

1. Jaartal uit (in volgorde) een keyword (`XMP-dc:Subject`, `IPTC:Keywords`, `lr:HierarchicalSubject`),
   `XMP-fotolineage:CircaDate`, of DateCreated t.e.m. 2000 – zie [docs/metadata.md](docs/metadata.md).
2. Achterzijdes weg (alleen als `detect_backs` aan staat in `config.json`; `setup` vraagt ernaar):
   - FotoLineage-db (`photos.side` = `back`/`extra`) of `XMP-fotolineage:PairPartner` Role=back;
   - ongekoppelde opeenvolgende scans (`Foto_01_225` / `Foto_01_226`) met hetzelfde jaartal:
     de scan met het minste beeld (licht, weinig contrast) is de achterzijde;
   - losse foto's die sterk op blanco karton lijken.
3. Documenten (`kind = document`), genegeerde foto's en dubbele bestanden worden overgeslagen.

## Weekplanning

Week *n* toont foto's `5n … 5n+4` uit `schedule.json`.

- De **lopende week en de volgende week liggen vast**: wat spelers al zagen en de week waarvoor je
  misschien al verhalen schrijft, veranderen niet.
- **Alle latere weken** worden bij elke `build` opnieuw verdeeld voor een **mix van jaartallen**: de foto's worden
  op jaartal gesorteerd en in 5 even grote groepen verdeeld (oudste → recentste); elke week krijgt één foto uit
  elke groep, in willekeurige volgorde. Zo zit er elke week een oude en een recente foto in.
  Bijna-dubbels (zelfde map + zelfde jaartal) komen niet in dezelfde week.
- De verdeling is vast voor dezelfde set foto's; voeg je foto's toe of sluit je er uit, dan verschuiven alleen
  de latere weken.
- Is de hele lijst gespeeld, dan begint de reeks opnieuw vooraan.

## Punten

`1000 × e^(−verschil/10)`: exact 1000, 2 jaar ernaast 819, 5 jaar 607, 10 jaar 368, 20 jaar 135.

## Je gegevens privé houden

Je planning, verhalen, instellingen en cache staan naast je `config.json`, niet bij de code. Wil je de code via git
bijhouden maar je gegevens niet publiek zetten, gebruik dan twee mappen: deze code-map en een aparte map (bv. een privé-repo)
met je `config.json`, `schedule.json`, `overrides.json`, `verhalen.json` en `photos.csv`. Start `build.py` dan met
`python pad\naar\code\tools\build.py --config pad\naar\config.json build`. De `.gitignore` van deze repo sluit die bestanden uit,
zodat je ze niet per ongeluk publiek zet.

## Privacy en rechten

- De webafbeeldingen (max. 1600 px) bevatten **geen** EXIF/XMP/IPTC-metadata, de bestandsnamen zijn gehasht en de
  jaartallen in `photos.json` zijn licht versluierd. Dat houdt toevallige nieuwsgierigen tegen, geen doorgewinterde
  speler: het is geen beveiliging.
- Zet enkel foto's online waarvoor je de rechten hebt en waarvan de afgebeelde personen dat aanvaarden.
- Kies een eigen `obf_key` en `salt` in `config.json` en wijzig ze niet meer in een lopende instantie, want dan
  veranderen alle afbeeldingsnamen.
- Statistieken zijn optioneel (`site.goatcounter`, [GoatCounter](https://www.goatcounter.com), zonder cookies).


## Licentie

MIT, zie [LICENSE](LICENSE). De lettertypen Fraunces en Inter hebben hun eigen licentie (`site_template/fonts/`). Foto's blijven eigendom van hun rechthebbenden.

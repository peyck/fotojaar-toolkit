# Jaartal en foto's uit metadata (exiftool)

Deze pagina hoort bij de jaartalbron `metadata` (zie de [README](../README.md)). Je hebt [exiftool](https://exiftool.org)
nodig en voert `python build.py scan` uit. Wil je geen exiftool gebruiken, kies dan de bronnen `csv` of `path`.

## Wanneer komt een foto in het spel?

| Voorwaarde | Hoe |
|---|---|
| Er is een **jaartal** | keyword, `CircaDate` of `DateCreated` (zie hieronder) |
| Het is de **beeldzijde** | koppel voor- en achterzijde in je beheerprogramma, of laat de automatische herkenning (`detect_backs`) het doen en controleer de resultaten in de controlepagina |
| Het jaartal staat **niet op de voorzijde** | anders is het te makkelijk; zet zulke mappen in `front_dated_dirs` of sluit de foto uit in de controlepagina |
| De foto staat niet in een uitgesloten map | `skip_dirs`, `skip_name_regex` (bestandsnamen) en `skip_ref_regex` (verwijzingen in pad, keywords, maker, titel, beschrijving) in `config.json` |

## Waar staat het jaartal?

De eerste bron die iets oplevert, telt:

1. **een keyword dat exact een jaartal is**, bv. `1905` (`XMP-dc:Subject`, `IPTC:Keywords`, `lr:HierarchicalSubject`). Twee
   jaartallen (max. `max_range` jaar uiteen, standaard 10) vormen een bereik; een gok daarbinnen telt als juist;
2. **`XMP-fotolineage:CircaDate`** (EDTF): `1910` exact, `1905/1915` bereik, `1910~` of `1910?` = 1908–1912. Open grenzen
   (`../1913`, `1913/..`) zijn te vaag en tellen niet;
3. **DateCreated** (`XMP-photoshop:DateCreated`, `IPTC:DateCreated`, `EXIF:DateTimeOriginal`), maar alleen t.e.m. het
   jaar `date_max_year` (standaard 2000): latere datums zijn bijna altijd de scandatum van de reproductie.

Hoe DateCreated gelezen wordt:
- zijn IPTC en EXIF het eens en wijkt alleen XMP af, dan winnen IPTC/EXIF;
- is het jaartal precies het midden van het FotoLineage-bereik (bv. 1904 bij `1902/1906`), dan wordt het bereik zelf het
  antwoord; bij een bereik van meer dan `max_range` jaar wordt de foto uitgesloten;
- andere tegenstrijdigheden: de foto wordt uitgesloten tot het jaartal rechtgezet is (de reden staat in de controlepagina).

**Handmatig jaartal** gaat altijd voor alle metadata. Zet het in `overrides.json`:

```json
"jaar": { "map/foto.jpg": 1902 }
```

## Optioneel

- **beschrijving** verschijnt onder de foto na het raden;
- **keywords** (plaats, fotograaf, afdruktechniek) verschijnen als labels; verbergen of linken via `keywords.json`
  (zie `tools/keywords.example.json`);
- **fotograaf en plaats** verschijnen als onderschrift.

`FotoLineage` is een programma waarmee de oorspronkelijke gebruiker zijn collectie beheert; de koppeling (database via
`fotolineage_db`, config via `fotolineage_config`) is volledig optioneel. Zonder werken keywords, `DateCreated` en de
andere bronnen gewoon.

## Inlezen

```
python build.py scan                 # hele collectie (kan lang duren)
python build.py scan foto.jpg        # een of enkele bestanden, of een map: enkele seconden
```

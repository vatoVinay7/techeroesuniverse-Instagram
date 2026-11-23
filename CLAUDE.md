# CLAUDE.md – Social-Media-Manager für @techeroesuniverse

Dieses Repository postet Reels und Stories automatisch auf Instagram (@techeroesuniverse,
englischsprachig, Tiny Dragon: Code Quest + Techeroes Explains). Claude plant die Wochen,
Vinay gibt frei, GitHub Actions postet.

Die inhaltlichen Regeln (Ton, Caption-Format, Hashtags, Rhythmus, Story-Typen) stehen im
Sqemes-Skill **„Tiny Dragon Instagram (@techeroesuniverse)“** – vor jeder Planung laden.
Kurzfassung: Englisch, max. 5 Hashtags, Serien-Hashtag zuerst, keine aufgesetzten
Kommentar-Aufrufe, Reels Mo–Fr 18:00 abwechselnd Folge/Erklärvideo, Stories 12:00 (täglich)
und 18:00 (Ankündigung an Reel-Tagen). Nichts ohne Vinays „ok“.

## Aufbau

| Pfad | Inhalt |
|---|---|
| `config.yaml` | Zeiten, Drosselung, Pages-Adresse |
| `content/library.yaml` | alle Reels mit Drive-ID, Reihenfolge und Caption-Entwurf |
| `plans/<YYYY-Www>.yaml` | Wochenplan; wird nur gepostet, wenn `approved: true` |
| `state/posted.json` | Protokoll (schreibt nur der Workflow) |
| `state/pending.json` | angelegte, noch nicht veröffentlichte Container (nur Workflow) |
| `state/token.enc.json` | verschlüsselter, automatisch erneuerter Instagram-Token |
| `igpost/` | Python-Code (`python -m igpost --help`) |
| Branch `media/<YYYY-Www>` | Video-/Bilddateien der Woche (eigener Branch, nie in main) |

Workflows: `post.yml` (alle 15 min), `pages.yml` (stellt Medien über GitHub Pages bereit –
Instagram lädt sie von dort), `refresh-token.yml` (wöchentlich), `ci.yml` (Tests).

## Wochenablauf (Claude)

1. Sqemes-Skill laden. `python -m igpost status` – Vorrat und offene Posts ansehen.
2. Reels vorschlagen: `python -m igpost suggest <YYYY-Www>` → Entwurf nach `plans/<YYYY-Www>.yaml`.
   Captions bei Bedarf anpassen (Caption-Text ohne Hashtags, Hashtags in `hashtags`).
3. Stories einplanen: Vinay lädt die Story-Bilder der Woche hoch (ohne feste Namen).
   Bilder ansehen, Story-Typ zuordnen, über die Woche verteilen (12:00 täglich, 18:00
   Ankündigung an Reel-Tagen; „Guess the Tech“ und Auflösung an Folgetagen).
   Stories mit Umfrage/Quiz/Link-Sticker: `manual: true` + `note` (Vinay postet selbst).
   Fehlen Stories → melden und ChatGPT-Prompts vorschlagen. Keine Bilder selbst generieren.
4. Medien vorbereiten (lokal, mit ffmpeg):
   - Reels: Quellvideo besorgen. Die Drive-Dateien sind zu groß für den Drive-Connector –
     sie kommen von Vinays Computer (Gerätebrücke, Ordner mit den heruntergeladenen Videos)
     oder als Upload im Chat. Drive-ID und Originalname stehen in der Bibliothek. Dann
     `python -m igpost prepare reel <quelle> build/<YYYY-Www>/<library_id>.mp4`
   - Stories: `python -m igpost prepare story <quelle> build/<YYYY-Www>/<item-id>.jpg`
   - Dateiname in `media` muss exakt dem Dateinamen im Medien-Branch entsprechen.
5. Plan (noch `approved: false`) committen und pushen – sonst räumt der nächtliche
   Aufräum-Lauf den Medien-Branch einer unbekannten Woche wieder ab.
6. Wochenplan als Übersicht an Vinay schicken (Tag, Uhrzeit, Typ, Caption, Vorschau der Stories,
   Sticker-Hinweise). Auf „ok“ warten.
7. Nach „ok“:
   - `scripts/push-media.sh <YYYY-Www> build/<YYYY-Www>` (lädt jede Datei einzeln auf `media/<YYYY-Www>`)
   - im Plan `approved: true` und `approved_at` setzen, `python -m igpost check`, committen, pushen.
     Der Push startet `pages.yml` automatisch. (Diese Sitzung darf keine Workflows starten,
     keine Releases anlegen und keine Branches löschen – das erledigen die Workflows selbst.)
   - einige Minuten später prüfen, dass eine Medien-URL antwortet:
     `curl -I <pages_base_url>/media/<YYYY-Www>/<datei>` → HTTP 200
8. Bei Änderungswünschen nach der Freigabe: Plan anpassen, neu committen. Bereits gepostete
   Einträge (state/posted.json) nicht mehr ändern.

## Regeln für Änderungen am Code

- `state/` nie von Hand bearbeiten – nur der Workflow schreibt dort.
- Tests: `python -m pytest -q` und `python -m igpost check` vor jedem Push.
- Secrets: `IG_ACCESS_TOKEN` (von Vinay, aus Meta for Developers), `IG_TOKEN_KEY` (Schlüssel für
  `state/token.enc.json`; nie ändern, sonst ist die gespeicherte Datei unlesbar und der
  Seed-Token aus `IG_ACCESS_TOKEN` wird wieder benutzt).
- Instagram-Fehler landen als GitHub-Issue mit Label `bot` und @-Erwähnung von Vinay.

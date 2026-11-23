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
| Release `media-<YYYY-Www>` | Video-/Bilddateien der Woche (nicht im Git!) |

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
   - Reels: Quellvideo besorgen (Drive-ID steht in der Bibliothek), dann
     `python -m igpost prepare reel <quelle> build/<YYYY-Www>/<library_id>.mp4`
   - Stories: `python -m igpost prepare story <quelle> build/<YYYY-Www>/<item-id>.jpg`
   - Dateiname in `media` muss exakt dem Dateinamen im Release entsprechen.
5. Wochenplan als Übersicht an Vinay schicken (Tag, Uhrzeit, Typ, Caption, Vorschau der Stories,
   Sticker-Hinweise). Auf „ok“ warten.
6. Nach „ok“:
   - `gh release create media-<YYYY-Www> build/<YYYY-Www>/* --title "Medien <YYYY-Www>" --notes "Wochenmedien"`
     (bei vorhandenem Release: `gh release upload media-<YYYY-Www> … --clobber`)
   - im Plan `approved: true` und `approved_at` setzen, `python -m igpost check`, committen, pushen.
     Der Push startet `pages.yml` automatisch (sonst: `gh workflow run pages.yml`).
   - prüfen, dass eine Medien-URL antwortet: `curl -I <pages_base_url>/media/<YYYY-Www>/<datei>`
7. Bei Änderungswünschen nach der Freigabe: Plan anpassen, neu committen. Bereits gepostete
   Einträge (state/posted.json) nicht mehr ändern.

## Regeln für Änderungen am Code

- `state/` nie von Hand bearbeiten – nur der Workflow schreibt dort.
- Tests: `python -m pytest -q` und `python -m igpost check` vor jedem Push.
- Secrets: `IG_ACCESS_TOKEN` (von Vinay, aus Meta for Developers), `IG_TOKEN_KEY` (Schlüssel für
  `state/token.enc.json`; nie ändern, sonst ist die gespeicherte Datei unlesbar und der
  Seed-Token aus `IG_ACCESS_TOKEN` wird wieder benutzt).
- Instagram-Fehler landen als GitHub-Issue mit Label `bot` und @-Erwähnung von Vinay.

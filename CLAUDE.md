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
   **Highlights:** Jede Story bekommt im Plan als `note` ihr Ziel-Highlight aus
   `content/highlights.yaml` (Vinay fügt sie in der App hinzu). Entsteht ein Highlight neu,
   gleich den ChatGPT-Cover-Prompt mitliefern.
   Fehlen Stories → melden und ChatGPT-Prompts schreiben. Keine Bilder selbst generieren.
   **Story-Prompts (ChatGPT):** Englisch, 1080×1920, kurzer Text im Bild, oben 250 px und unten
   300 px frei. Jeder Prompt beginnt mit der Liste der anzuhängenden Referenzbilder in fester
   Reihenfolge – immer 1. Tiny, 2. TechVille-Umgebung, 3. jede weitere Figur der Szene,
   **4. zuletzt immer ein Stil-Bild** – mit Dateiname und Drive-Ordner, damit Figuren, Umgebung
   UND Schrift gleich bleiben. Stil-Bild = passendes MUSTER (teaser / episode / explains) oder ein
   früheres Bild als Vorlage („Keep layout, font and style exactly like the last attached image;
   change only: …“). Eigenes techeroes-Logo darf vorkommen, sonst keine Logos. Gilt auch für
   Bild-Beiträge im Feed (dort 1080×1350, 4:5). Das Referenz-Set steht in
   `content/references.yaml` (fehlt es noch: mit Vinay festlegen und dort eintragen).
   Vorlage auch in Sqemes: „Tiny Dragon Story-Bild (ChatGPT-Prompt)“.
4. Medien vorbereiten (lokal, mit ffmpeg):
   - Quellvideos kommen **direkt aus Google Drive** über „Google Drive für Desktop“ (Laufwerk,
     meist `G:\Meine Ablage\Techeroes Universe nützliche Dateien und Videos…`; der geteilte Ordner
     ist als Verknüpfung in „Meine Ablage“ eingebunden). Pfad steht in `config.yaml` unter
     `local_sources.videos` – ist er leer, das Laufwerk durchsuchen, Vinay den gefundenen Pfad
     bestätigen lassen und eintragen. Dateien über `source_name` (bzw. Drive-ID) aus der Bibliothek
     finden, ggf. in Unterordnern. Nicht herunterladen/kopieren lassen – direkt von dort umwandeln.
   - Story-Bilder: Vinay legt sie in den Ordner aus `local_sources.stories` (Unterordner je Woche,
     z. B. `…\Stories\2026-W49`) oder lädt sie im Chat hoch.
   - In einer Cloud-Sitzung ohne lokales Laufwerk kommen die Dateien über die Gerätebrücke.
   - Reels umwandeln:
     `python -m igpost prepare reel <quelle> build/<YYYY-Www>/<library_id>.mp4`
   - **Jedes Reel bekommt sein Poster als Titelbild:** Poster liegt im selben Drive-Ordner wie das
     Video (`poster_name` in der Bibliothek, sonst die PNG im Ordner).
     `python -m igpost prepare story <poster> build/<YYYY-Www>/<library_id>-cover.jpg` und im Plan
     `cover: <library_id>-cover.jpg` eintragen.
   - Eingangsordner für Vinay: `inbox/<YYYY-Www>/` im Repo (in VS Code links; wird nie hochgeladen).
   - Stories: `python -m igpost prepare story <quelle> build/<YYYY-Www>/<item-id>.jpg`
   - Dateiname in `media` muss exakt dem Dateinamen im Medien-Branch entsprechen.
   - Bild-Beiträge im Feed (`kind: post`, z. B. Vorstellung zum Anpinnen):
     `python -m igpost prepare post <quelle> build/<YYYY-Www>/<item-id>.jpg` (1080×1350, 4:5).
     Caption wie bei Reels; Anpinnen macht Vinay in der App.
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

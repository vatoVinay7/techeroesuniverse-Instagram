# @techeroesuniverse – automatisches Posten

Postet die Reels von **Tiny Dragon: Code Quest** und **Techeroes Explains** sowie die Stories
automatisch auf Instagram. Claude plant jede Woche, Vinay gibt mit einem „ok“ frei, GitHub postet.

## So läuft eine Woche

1. **Anfang der Woche:** Vinay lädt die Story-Bilder der Woche bei Claude hoch.
2. **Claude** wählt die Reels (abwechselnd Folge / Erklärvideo), sortiert die Stories ein und
   schickt den Wochenplan.
3. **Vinay** antwortet mit „ok“ (oder Änderungswünschen).
4. **GitHub** postet automatisch:
   - Reels Mo–Fr um 18:00 Uhr
   - Stories täglich um 12:00 Uhr, an Reel-Tagen zusätzlich eine Ankündigung um 18:00 Uhr
5. Stories mit Umfrage, Quiz oder Link postet Vinay selbst – GitHub erinnert zur richtigen Zeit.

Wird der Vorrat knapp, postet der Plan seltener: ab 10 Reels 5×/Woche, ab 5 Reels 3×/Woche,
darunter 2×/Woche.

## Wenn etwas schiefgeht

Probleme (Post fehlgeschlagen, Token abgelaufen, Erinnerung für Sticker-Stories) erscheinen als
**Issue** in diesem Repository – GitHub schickt dazu eine Benachrichtigung bzw. E-Mail.

## Einmalige Einrichtung

| Schritt | Wer | Stand |
|---|---|---|
| Instagram-Business-Konto @techeroesuniverse | Vinay | erledigt |
| Meta-App mit „API setup with Instagram login“ | Vinay | erledigt |
| Secret `IG_TOKEN_KEY` (Verschlüsselungsschlüssel) | Claude | wird gesetzt |
| Secret `IG_ACCESS_TOKEN` (Token aus Meta for Developers) | Vinay | offen |
| GitHub Pages (Quelle: GitHub Actions) | Claude | wird gesetzt |

Den Instagram-Token erneuert der Workflow „Token erneuern“ jede Woche selbst. Nur wenn Instagram
ihn ablehnt, muss in Meta for Developers ein neuer erzeugt und `IG_ACCESS_TOKEN` ersetzt werden.

## Technik

- `python -m igpost status` – Überblick
- `python -m igpost suggest 2026-W49` – Reels für eine Woche vorschlagen
- `python -m igpost check` – Bibliothek und Pläne prüfen
- `python -m igpost whoami` – Token testen (braucht `IG_ACCESS_TOKEN` und `IG_TOKEN_KEY`)

Details für Claude: [CLAUDE.md](CLAUDE.md).

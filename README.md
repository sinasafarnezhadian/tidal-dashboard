# tidal-dashboard

Ein einfaches, statisches Musik-Dashboard fürs iPad. Vorausgewählte Tidal-Playlists
und Lieder werden als große, antippbare Kacheln angezeigt. Beim Antippen öffnet
sich der offizielle Tidal-Embed-Player mit eigenem Play/Pause-Button.

Reines HTML/CSS/JS, kein Server-Backend, keine Zugangsdaten im Code. Die
Wiedergabe läuft über Tidals offizielles `embed.tidal.com`-Widget – dafür
muss man sich im Widget einmalig mit einem Tidal-Konto anmelden (kostenloses
oder bezahltes Konto).

**Wichtig:** Tidals Embed-Player nutzt für Login/Lizenzierung die
Web-Crypto-API, die Browser nur in einem sicheren Kontext (HTTPS)
bereitstellen. Läuft die Seite über einfaches HTTP (z. B. lokal im
Heimnetz ohne eigenes Zertifikat), schlägt die Wiedergabe fehl. Deshalb
läuft dieses Dashboard über **GitHub Pages**, das automatisch HTTPS
bereitstellt.

## Playlists/Lieder pflegen

Alles wird in `config.json` gepflegt:

```json
{
  "items": [
    { "type": "playlist", "title": "Gute-Laune-Playlist", "tidalId": "PLAYLIST-UUID", "emoji": "🎧" },
    { "type": "track", "title": "Lieblingslied", "artist": "Interpret", "tidalId": "TRACK-ID", "emoji": "🎵" }
  ]
}
```

So findet man die IDs in der Tidal-App/Website:
- **Playlist**: Playlist öffnen → Teilen → Link kopieren, z. B.
  `https://tidal.com/playlist/1234abcd-...` → die UUID nach `/playlist/` ist die `tidalId`.
- **Track**: Lied öffnen → Teilen → Link kopieren, z. B.
  `https://tidal.com/track/59978731` → die Zahl am Ende ist die `tidalId`.

Nach dem Ändern von `config.json` (siehe unten committen/pushen) lädt die
Seite die neuen Inhalte automatisch beim nächsten Aufruf – kein separates
Deployment nötig.

## Hosting über GitHub Pages einrichten (einmalig)

GitHub Pages kann Dateien nicht automatisch selbst aktivieren – das ist ein
einmaliger manueller Klick in den Repo-Einstellungen:

1. Im Repo auf **Settings** → **Pages** gehen.
2. Unter **Build and deployment** → **Source**: „Deploy from a branch“ wählen.
3. **Branch**: `main`, Ordner `/ (root)` auswählen, **Save**.
4. Nach ein bis zwei Minuten ist die Seite erreichbar unter:
   `https://sinasafarnezhadian.github.io/tidal-dashboard/`

Jeder weitere Push auf `main` (z. B. nach einer Änderung an `config.json`)
aktualisiert die Seite automatisch.

## Auf dem iPad einrichten

1. Im Safari-Browser `https://sinasafarnezhadian.github.io/tidal-dashboard/`
   öffnen.
2. Teilen-Button → „Zum Home-Bildschirm“ – dann startet das Dashboard wie
   eine App, ganzseitig, ohne Browserleiste.
3. Beim ersten Antippen einer Kachel im Tidal-Embed-Player einmalig mit dem
   Tidal-Konto anmelden.

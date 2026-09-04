# tidal-dashboard

Ein einfaches, statisches Musik-Dashboard fürs iPad. Vorausgewählte Tidal-Playlists
und Lieder werden als große, antippbare Kacheln angezeigt. Beim Antippen öffnet
sich der offizielle Tidal-Embed-Player mit eigenem Play/Pause-Button.

Reines HTML/CSS/JS, kein Server-Backend, keine Zugangsdaten im Code. Die
Wiedergabe läuft über Tidals offizielles `embed.tidal.com`-Widget – dafür
muss man sich im Widget einmalig mit einem Tidal-Konto anmelden (kostenloses
oder bezahltes Konto).

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

Nach dem Speichern von `config.json` reicht ein Neuladen der Seite im
iPad-Browser – kein Deploy, kein Neustart nötig.

## Lokal im Heimnetz starten

Auf einem immer laufenden Rechner im Heimnetz (z. B. Raspberry Pi, NAS, alter PC):

```bash
cd tidal-dashboard
python3 -m http.server 8080
```

Die Seite ist dann für alle Geräte im selben WLAN erreichbar unter:

```
http://<lokale-IP-des-Rechners>:8080
```

Die lokale IP findet man z. B. mit `hostname -I` (Linux) oder in den
WLAN-Einstellungen des Rechners.

Damit der Server automatisch nach einem Neustart wieder läuft, kann man ihn
z. B. als systemd-Service oder Cronjob (`@reboot`) einrichten – optional,
für den Start reicht der obige Befehl.

## Auf dem iPad einrichten

1. Im Safari-Browser die lokale Adresse (siehe oben) öffnen.
2. Teilen-Button → „Zum Home-Bildschirm“ – dann startet das Dashboard wie
   eine App, ganzseitig, ohne Browserleiste.
3. Beim ersten Antippen einer Kachel im Tidal-Embed-Player einmalig mit dem
   Tidal-Konto anmelden.

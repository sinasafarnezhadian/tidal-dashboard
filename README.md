# tidal-dashboard

Ein einfaches Musik-Dashboard fürs iPad. Vorausgewählte Tidal-Playlists,
Alben und Lieder werden als große, antippbare Kacheln angezeigt. Play/Pause
läuft direkt im Dashboard über einen eigenen Player.

## ⚠️ Wichtiger Hinweis

Tidal bietet **keine offizielle API für eingebettete Vollwiedergabe** durch
Drittanbieter-Seiten (das offizielle Embed-Widget spielt nur 30-Sekunden-
Vorschauen). Damit trotzdem volle Songs direkt im Dashboard laufen, nutzt
dieses Projekt die **inoffizielle Tidal-API** über die Bibliothek
[`tidalapi`](https://github.com/tamland/python-tidal).

Das bedeutet konkret:
- Es verstößt gegen Tidals Nutzungsbedingungen – im schlimmsten Fall könnte
  der Tidal-Account gesperrt werden.
- Die Bibliothek kann jederzeit ohne Vorwarnung aufhören zu funktionieren,
  wenn Tidal seine private API ändert.
- Der Login-Token wird lokal auf dem Server gespeichert (`server/tidal_session.json`,
  per `.gitignore` vom Git-Repo ausgeschlossen) – niemals committen oder
  öffentlich hosten.

Deshalb läuft der Server **nur lokal im Heimnetz**, nicht öffentlich im
Internet (kein Vercel/GitHub Pages mehr nötig).

## Architektur

- `index.html` / `style.css` / `app.js` – Frontend mit den Kacheln und dem
  eigenen Play/Pause-Player (Beige/Hellgrün/Erdtöne).
- `server/app.py` – kleiner Python-Server (Flask), der sich einmalig bei
  Tidal anmeldet, Playlist/Album/Track-Infos abruft und Stream-URLs an das
  Frontend liefert. Liefert auch gleich die statischen Dateien aus.
- `config.json` – Liste der Playlists/Alben/Lieder, die als Kacheln
  angezeigt werden.

## Einrichtung

Auf einem immer laufenden Rechner im Heimnetz (Raspberry Pi, NAS, alter PC),
mit Python 3 installiert:

```bash
cd tidal-dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r server/requirements.txt
python3 server/app.py
```

Beim **ersten Start** zeigt das Terminal einen Link und einen Code an, z. B.:

```
Visit https://link.tidal.com/XXXXX to log in, the code will expire in 300 seconds
```

Diesen Link auf einem beliebigen Gerät (Handy reicht) öffnen und mit dem
Tidal-Konto bestätigen (das Konto braucht ein aktives Abo). Danach läuft der
Server weiter und merkt sich den Login in `server/tidal_session.json` – bei
späteren Starts ist kein erneuter Login nötig.

Die Seite ist danach im Heimnetz erreichbar unter:

```
http://<lokale-IP-des-Rechners>:8080
```

Damit der Server automatisch nach einem Neustart wieder läuft, kann man ihn
z. B. als systemd-Service einrichten (optional).

## Playlists/Lieder pflegen

Alles wird in `config.json` gepflegt:

```json
{
  "items": [
    { "type": "playlist", "title": "Gute-Laune-Playlist", "tidalId": "PLAYLIST-UUID", "emoji": "🎧" },
    { "type": "album", "title": "Albumname", "tidalId": "ALBUM-ID", "emoji": "💿" },
    { "type": "track", "title": "Lieblingslied", "artist": "Interpret", "tidalId": "TRACK-ID", "emoji": "🎵" }
  ]
}
```

So findet man die IDs in der Tidal-App:
- **Playlist**: Playlist öffnen → Teilen → Link kopieren, z. B.
  `https://tidal.com/playlist/1234abcd-...` → die UUID ist die `tidalId`.
- **Album**: Album öffnen → Teilen → Link kopieren, z. B.
  `https://tidal.com/album/59978731` → die Zahl ist die `tidalId`.
- **Track**: Lied öffnen → Teilen → Link kopieren, z. B.
  `https://tidal.com/track/59978731` → die Zahl ist die `tidalId`.

Anders als beim früheren Embed-Widget müssen Playlists **nicht** öffentlich
gestellt werden, da der Server mit dem eigenen Tidal-Login zugreift.

Nach dem Ändern von `config.json` reicht ein Neuladen der Seite im
iPad-Browser – kein Neustart des Servers nötig.

## Auf dem iPad einrichten

1. Im Safari-Browser die lokale Adresse (siehe oben) öffnen.
2. Teilen-Button → „Zum Home-Bildschirm" – dann startet das Dashboard wie
   eine App, ganzseitig, ohne Browserleiste.

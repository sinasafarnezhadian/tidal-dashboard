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
  Tidal anmeldet, Playlist/Album/Track-Infos abruft und Stream-Infos an das
  Frontend liefert. Liefert auch gleich die statischen Dateien aus.
- `config.json` – Liste der Playlists/Alben/Lieder, die als Kacheln
  angezeigt werden.
Tidal liefert die meisten Tracks als MPEG-DASH aus (Init-Segment + viele
Einzelsegmente statt einer fertigen Datei). Der Server setzt diese Segmente
zusammen und schickt dem Browser eine ganz normale Audio-Datei – im Frontend
läuft daher ein simples `<audio>`-Element, ohne DASH-Player, MediaSource oder
DRM-Handling. Das ist derselbe Ansatz, den auch Download-Tools wie tidarr
serverseitig verwenden, und umgeht die Wiedergabe-Eigenheiten von iOS-Safari.

## Einrichtung

### Variante A: Docker / Dockge (empfohlen)

Das Repo enthält ein `Dockerfile` und `docker-compose.yml`.

**A1 – Repo vorher klonen:**

1. Neuen Stack anlegen, Repo-Ordner (bzw. dessen Inhalt) als Stack-Verzeichnis
   verwenden – `docker-compose.yml` wird automatisch erkannt.
2. Stack starten (Deploy). Dockge/Docker Compose baut das Image aus dem
   `Dockerfile` und startet den Container.

**A2 – Direkt in Dockge einfügen (kein Klonen nötig):** neuen Stack anlegen
und diese `compose.yaml` einfügen – Docker holt sich den Build-Context
selbst per Git:

```yaml
services:
  tidal-dashboard:
    build:
      context: https://github.com/sinasafarnezhadian/tidal-dashboard.git#main
    container_name: tidal-dashboard
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/app/data
```

Bei beiden Varianten gilt: Der Login-Token landet dank Volume-Mount in
`./data/tidal_session.json`
   im Stack-Ordner auf dem Host – bleibt also auch bei Neubau/Neustart des
   Containers erhalten.

Beim **ersten Start** (und wenn `./data/tidal_session.json` fehlt/ungültig
ist) im Browser aufrufen:

```
http://<lokale-IP-des-Docker-Hosts>:8080/login/start
```

Dort auf den Login-Link tippen, mit dem Tidal-Konto anmelden (aktives Abo
nötig). Nach dem Login landet man auf einer „Oops"-Fehlerseite – deren
komplette Adresse aus der Adresszeile kopieren und auf der `/login/start`-
Seite ins Textfeld einfügen und bestätigen. Der Server merkt sich den Login
danach dauerhaft in `./data/tidal_session.json` – kein erneuter Login bei
künftigen Neustarts, solange der `./data`-Ordner erhalten bleibt.

(Dieser Umweg über eine Fehlerseiten-URL ist Tidals eigener PKCE-Login-Ablauf,
der – anders als der einfachere Geräte-Code-Login – auch bei Konten
funktioniert, die sonst einen „401 Unauthorized" beim Abspielen bekommen.)

Die Seite ist danach im Heimnetz erreichbar unter:

```
http://<lokale-IP-des-Docker-Hosts>:8080
```

Port lässt sich in `docker-compose.yml` unter `ports` anpassen, falls 8080
schon belegt ist.

### Variante B: Direkt mit Python (ohne Docker)

Auf einem immer laufenden Rechner im Heimnetz, mit Python 3 installiert:

```bash
cd tidal-dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r server/requirements.txt
python3 server/app.py
```

Login-Ablauf und Seiten-Adresse wie oben beschrieben; der Token landet dann
in `server/tidal_session.json`. Für Autostart nach Neustart z. B. als
systemd-Service einrichten (optional).

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

---
Letzte Änderung: 2026-09-08 20:35 UTC

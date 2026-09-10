# tidal-dashboard

Ein einfaches Musik-Dashboard fürs iPad. Vorausgewählte Tidal-Playlists,
Alben und Lieder werden als große, antippbare Kacheln angezeigt. Play/Pause
läuft direkt im Dashboard über einen eigenen Player.

## ⚠️ Wichtiger Hinweis

Tidal bietet **keine offizielle API für eingebettete Vollwiedergabe** durch
Drittanbieter-Seiten (das offizielle Embed-Widget spielt nur 30-Sekunden-
Vorschauen). Damit trotzdem volle Songs direkt im Dashboard laufen, nutzt
dieses Projekt die **inoffizielle Tidal-API** über die Bibliothek
[`tiddl`](https://github.com/oskvr37/tiddl) – dieselbe, die auch das
Download-Tool tidarr verwendet.

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
  Player im Kopfbereich: Titel und Interpret, darunter in einer Zeile
  Vor/Play/Zurück, Fortschrittsbalken und Zeitangaben (Beige/Hellgrün/
  Erdtöne).
- `server/app.py` – kleiner Python-Server (Flask), der sich einmalig bei
  Tidal anmeldet, Playlist/Album/Track-Infos abruft und die Audiodateien an
  das Frontend liefert. Liefert auch gleich die statischen Dateien aus.
- `config.json` – Liste der Playlists/Alben/Lieder, die als Kacheln
  angezeigt werden.

Der Server ermittelt bei Tidal die Adresse der fertigen Audiodatei und reicht
sie durch: Der `Range`-Header des Browsers geht unverändert an Tidals CDN, und
dessen Antwort (`206`, `Content-Length`, `Content-Range`) kommt genauso zurück.
Dadurch startet die Wiedergabe sofort, statt erst nach einem vollständigen
Download, und Safari bekommt die Byte-Bereiche, ohne die es die Wiedergabe
verweigert. Im Frontend genügt darum ein simples `<audio>`-Element – ohne
DASH-Player, MediaSource oder DRM-Handling.

Verwendet werden nur „bts"-Manifeste, also fertige Dateien; die Qualitäten
`HIGH`, `LOW` und `LOSSLESS` werden der Reihe nach probiert. `HI_RES_LOSSLESS`
bleibt außen vor, weil es nur als MPEG-DASH-Segmente ausgeliefert wird.

## Einrichtung

### Variante A: Docker / Dockge (empfohlen)

Das Repo enthält ein `Dockerfile` und `docker-compose.yml`.

**A1 – Repo vorher klonen:**

1. Neuen Stack anlegen, Repo-Ordner (bzw. dessen Inhalt) als Stack-Verzeichnis
   verwenden – `docker-compose.yml` wird automatisch erkannt.
2. Stack starten (Deploy). Dockge/Docker Compose baut das Image aus dem
   `Dockerfile` und startet den Container.

**A2 – Klon im Unterordner `src`:** Wenn der Stack-Ordner und der Klon
getrennt sein sollen, das Repo nach `src/` klonen und diese `compose.yaml` in
den Stack legen:

```yaml
services:
  tidal-dashboard:
    build: ./src
    container_name: tidal-dashboard
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/app/data
      - ./src:/app:ro
```

Bei beiden Varianten gilt: Der Login-Token landet dank Volume-Mount in
`./data/tidal_session.json`
   im Stack-Ordner auf dem Host – bleibt also auch bei Neubau/Neustart des
   Containers erhalten.

Beim **ersten Start** (und wenn `./data/tidal_session.json` fehlt) im Browser
aufrufen:

```
http://<lokale-IP-des-Docker-Hosts>:8080/login/start
```

Dort auf den Link tippen und die Anmeldung im Tidal-Konto bestätigen (aktives
Abo nötig) – mehr nicht, die Seite meldet von selbst „Angemeldet". Der Login
wird dauerhaft in `./data/tidal_session.json` gespeichert und bei Ablauf
automatisch erneuert; solange der `./data`-Ordner erhalten bleibt, ist kein
erneuter Login nötig.

Die Seite ist danach im Heimnetz erreichbar unter:

```
http://<lokale-IP-des-Docker-Hosts>:8080
```

Port lässt sich in `docker-compose.yml` unter `ports` anpassen, falls 8080
schon belegt ist.

#### Aktualisieren ohne Neubau

Der Quellcode kommt im Betrieb aus dem gemounteten Klon, nicht aus dem Image
(`- .:/app:ro` bzw. `- ./src:/app:ro`). Deshalb reicht meistens ein `git pull`:

| Was sich geändert hat | Was zu tun ist |
| --- | --- |
| Playlists, Favoriten, Vorschläge, Explizit-Filter | nichts – das macht das Zahnrad |
| `index.html`, `style.css`, `app.js` | `git pull`, Seite im Browser neu laden |
| `server/app.py` | `git pull && docker compose restart tidal-dashboard` |
| `server/requirements.txt` oder `Dockerfile` | `git pull && docker compose up -d --build` |

Der Mount ist schreibgeschützt: Alles Veränderliche – Login-Token, gepflegte
`config.json`, PIN, API-Cache – liegt in `./data`, der Container hat im Klon
also nichts verloren. So legt er dort auch keine root-eigenen Dateien ab, die
das nächste `git pull` blockieren würden.

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

## Einstellungen im Dashboard

Unten links auf jeder Seite sitzt ein Zahnrad (bewusst nicht mitscrollend). Es
öffnet ein Overlay, das zuerst nach einem **vierstelligen PIN** fragt. Beim
ersten Mal wird der PIN dort festgelegt – zur Sicherheit mit Wiederholung,
denn zurücksetzen lässt er sich nur durch Löschen von
`./data/settings_pin.json` auf dem Host.

Danach erscheinen die Einstellungen:

- **Vorschläge zeigen (Discovery)** – Häkchen, ab Werk aus.
- **Favoriten-Liste** – die Playlist, die unter den Kacheln erscheint und die
  das Herz befüllt. ID oder Tidal-Link, beides wird erkannt.
- **Sichtbare Playlisten** – eine pro Zeile, als Playlist-UUID, Album-Nummer
  oder Tidal-Link. Eine nicht erkennbare Zeile wird gemeldet und **nichts**
  gespeichert, statt die Hälfte zu übernehmen.
- **Explizit-Filter** – zwei Auswahlknöpfe. Steht die Auswahl auf
  „deaktiviert", spielt das Dashboard auch Titel, die Tidal als `explicit`
  markiert. Nicht streambare und Dolby-Atmos-Titel bleiben unabhängig davon
  außen vor, die kann der Browser ohnehin nicht abspielen.

„Speichern" schreibt und lädt die Seite neu, „Abbrechen" verwirft.

Der PIN wird nicht im Klartext abgelegt, sondern als PBKDF2-Hash mit
zufälligem Salt in `./data/settings_pin.json` – bewusst **nicht** in der
Config, denn die wird an den Browser ausgeliefert. Gegen simples Durchprobieren
aller 10 000 Kombinationen gilt: nach fünf Fehlversuchen eine Minute Pause,
und zwischen zwei Fehlversuchen mindestens eine Sekunde. Ein richtiger PIN
wird nie gebremst. Das ist eine Kindersicherung im Heimnetz, kein Türsteher –
wer im selben WLAN ist, kommt an die Musik ohnehin heran.

## Wo die Einstellungen liegen

Gepflegt wird `./data/config.json` im Stack-Ordner auf dem Host, also im
gemounteten Volume. Die `config.json` **im Repo ist nur die Vorlage**: Sie
steckt im Docker-Image und wäre nach jedem `--build` wieder im Ausgangszustand.
Beim ersten Start ohne `./data/config.json` wird die Vorlage einmalig dorthin
kopiert; ab da ändert nur noch das Zahnrad (oder ein Editor auf dem Host) etwas
daran.

Von Hand lässt sich dieselbe Datei weiterhin bearbeiten:

```json
{
  "discover": false,
  "allowExplicit": false,
  "favorites": "PLAYLIST-UUID",
  "items": [
    { "type": "playlist", "title": "Gute-Laune-Playlist", "tidalId": "PLAYLIST-UUID", "emoji": "🎧" },
    { "type": "album", "title": "Albumname", "tidalId": "ALBUM-ID", "emoji": "💿" }
  ]
}
```

`items` enthält Playlists und Alben, die als Kacheln erscheinen. Einzelne
Lieder gibt es dort nicht mehr – die stehen in der `favorites`-Playlist.

`favorites` ist die UUID einer Playlist, deren Titel direkt unter den Kacheln
als eigene Liste mit Cover erscheinen – rechts in jeder Zeile steht ein Herz
als Kennzeichen für den Favoritenbereich (vorerst nur das Symbol, ohne
Funktion; später soll darüber ein Titel wieder aus der Playlist fliegen) und die das Herz im Player befüllt – gedacht für die Lieblingslieder des
Kindes. Ein Tipp darauf spielt ab dieser Stelle die ganze Playlist weiter. Fehlt der
Eintrag, entfällt der Bereich.

`discover` schaltet den Empfehlungsbereich unter den Liedern ein oder aus (ab
Werk aus).
Tidal hat **keinen** Endpunkt für „ähnliche Playlists"; es gibt nur ähnliche
Künstler, Radios und ähnliche Alben, die alle keine Playlists liefern. Der
Bereich nimmt daher die Künstler aus den eingetragenen Playlists, wählt davon
zufällig drei aus und sucht nach ihnen – die Suche ist die einzige Stelle der
API, die Playlists zurückgibt. Ausgewertet wird nur der `playlists`-Zweig der
Suche, es können dort also keine einzelnen Lieder auftauchen. Aussortiert
werden bereits eingetragene Playlists und solche ohne Titel, die beim Antippen
nur ins Leere liefen. Angezeigt werden höchstens vier (`DISCOVER_LIMIT` in
`server/app.py`), die Auswahl wechselt bei jedem Seitenaufruf.

So findet man die IDs in der Tidal-App:
- **Playlist**: Playlist öffnen → Teilen → Link kopieren, z. B.
  `https://tidal.com/playlist/1234abcd-...` → die UUID ist die `tidalId`.
- **Album**: Album öffnen → Teilen → Link kopieren, z. B.
  `https://tidal.com/album/59978731` → die Zahl ist die `tidalId`.

Anders als beim früheren Embed-Widget müssen Playlists **nicht** öffentlich
gestellt werden, da der Server mit dem eigenen Tidal-Login zugreift.

**Jugendschutz:** Aus Playlists und Alben werden Titel übersprungen, die Tidal
als `explicit` markiert (ebenso nicht streambare und Dolby-Atmos-Titel).
Abschalten lässt sich das über das Zahnrad oder mit `"allowExplicit": true`.

Nach dem Ändern von `./data/config.json` reicht ein Neuladen der Seite im
iPad-Browser – kein Neustart des Servers nötig.

Die Kacheln zeigen Cover und Name aus Tidal; `emoji` und `title` aus der
`config.json` dienen nur noch als Rückfall, falls Bild oder Name nicht
abrufbar sind. Die Bilder laufen über
`/api/art/...` durch den eigenen Server, damit der Browser keine weitere
Tidal-Domain braucht (relevant, wenn im Heimnetz ein DNS-Filter läuft).

Das Board ist dreigeteilt: Playlists und Alben stehen oben als zweispaltige
Kacheln (Cover links, Name rechts), darunter – jeweils durch eine Linie
getrennt – die Titel der `favorites`-Playlist und die Empfehlungen. Ein Tipp auf eine Kachel oder Zeile startet die
Wiedergabe sofort; der Player bleibt beim Scrollen oben stehen. Läuft eine
Playlist oder ein Album, klappt der Kopfbereich nach unten auf und zeigt alle
Titel von 1 bis n – jede Zeile ist antippbar und springt direkt dorthin, der
laufende Titel ist hervorgehoben. Die Liste ist auf 45 % der Bildschirmhöhe
begrenzt und scrollt innen, damit eine lange Playlist das Board nicht
verdrängt; über den Pfeil an ihrer Unterkante lässt sie sich ganz einklappen
und wieder auf die Standardgröße bringen. Im Fortschrittsbalken lässt sich im Titel springen, und
am Ende eines Titels läuft die Playlist automatisch weiter.

Das Herz rechts im Player trägt den laufenden Titel in die
`favorites`-Playlist ein. Tidal verlangt für Änderungen an einer Playlist
deren aktuellen ETag, der Server liest sie also zuerst und schickt den Tag als
`If-None-Match` zurück; `onDupes=SKIP` überlässt es Tidal, einen schon
vorhandenen Titel abzulehnen – die Oberfläche meldet dann „Ist schon in
Younes-Favoriten". Ein Entfernen gibt es bewusst nicht.

Damit ein Kind die Playlist nicht durch schnelles Tippen vollschreibt, greift
ein Guard: Der Server nimmt höchstens alle 3 Sekunden einen Titel an und
antwortet sonst mit `429` und „Zu schnell – bitte kurz warten." Der Knopf
sperrt sich für dieselbe Zeit, sodass es gar nicht erst zum Hämmern kommt. Die
Rückmeldung bleibt diese 3 Sekunden stehen und wird nicht von einem später
eintreffenden Aufräumen des Players überschrieben.

### Ältere iPads

Das Frontend läuft bewusst auch auf altem Safari (iOS 12). Deshalb: kein
`gap` in Flexbox (gibt es erst ab Safari 14.1, Abstände laufen über
`margin`), `position: -webkit-sticky` zusätzlich zur unpräfixierten Form,
kein `var()` innerhalb von `calc()`, und keine neuere JS-Syntax wie `?.`.
Die zweispaltigen Bereiche nutzen `minmax(0, 1fr)` statt `1fr`: mit `1fr` ist
die Mindestbreite einer Spalte die ihres Inhalts, ein langer Titel drückt sie
dann breiter als die Nachbarspalte, statt mit „…" zu kürzen.
Wer hier etwas ändert, sollte das im Blick behalten.

## Auf dem iPad einrichten

1. Im Safari-Browser die lokale Adresse (siehe oben) öffnen.
2. Teilen-Button → „Zum Home-Bildschirm" – dann startet das Dashboard wie
   eine App, ganzseitig, ohne Browserleiste.

---
Letzte Änderung: 2026-09-10 11:16 UTC

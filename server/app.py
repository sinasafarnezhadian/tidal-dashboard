import base64
import hashlib
import hmac
import json
import os
import pathlib
import random
import re
import threading
import time

import requests
from flask import Flask, Response, abort, jsonify, request, send_from_directory, stream_with_context
from tiddl.core.api import TidalAPI, TidalClient
from tiddl.core.auth.api import AuthAPI
from tiddl.core.auth.exceptions import AuthClientError

BASE_DIR = pathlib.Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR.parent
DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FILE = DATA_DIR / "tidal_session.json"
API_CACHE = DATA_DIR / "api_cache"

# Tried in order until one yields a "bts" manifest, i.e. one finished audio
# file. HI_RES_LOSSLESS is deliberately absent: it only comes as MPEG-DASH
# segments, which a plain <audio> element cannot play.
QUALITIES = ["HIGH", "LOW", "LOSSLESS"]

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

auth_api = AuthAPI()
api: TidalAPI | None = None
tokens: dict | None = None
login_state = {"status": "logged_out"}

# Das Herz verändert eine echte Playlist - ein hämmerndes Kind soll nicht
# im Sekundentakt schreiben. Der Browser sperrt den Button ohnehin, aber
# verlassen wird sich darauf nicht.
# Wie viele Zufalls-Playlists der Empfehlungsbereich hoechstens zeigt.
DISCOVER_LIMIT = 4

FAVORITE_COOLDOWN = 3.0
favorite_lock = threading.Lock()
last_favorite_add = 0.0

# Die Datei im Repo ist nur die Vorlage: sie steckt im Image und waere nach
# jedem Rebuild wieder da. Gepflegt wird die Kopie im gemounteten DATA_DIR.
CONFIG_SEED = STATIC_DIR / "config.json"
CONFIG_FILE = DATA_DIR / "config.json"

# Der PIN gehoert nicht in die Config: die wird statisch ausgeliefert und ist
# damit im Heimnetz fuer jeden lesbar.
PIN_FILE = DATA_DIR / "settings_pin.json"
PIN_ITERATIONS = 200_000
PIN_MIN_INTERVAL = 1.0   # Sekunden zwischen zwei Versuchen
PIN_MAX_FAILURES = 5     # danach eine Zwangspause
PIN_LOCKOUT = 60.0
pin_lock = threading.Lock()
pin_state = {"last_fail": 0.0, "failures": 0, "locked_until": 0.0}


def load_config() -> dict:
    """Effective settings, seeded from the repo copy on first start."""
    if not CONFIG_FILE.exists():
        seed = json.loads(CONFIG_SEED.read_text()) if CONFIG_SEED.exists() else {}
        CONFIG_FILE.write_text(json.dumps(seed, indent=2, ensure_ascii=False))
    return json.loads(CONFIG_FILE.read_text())


def hash_pin(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PIN_ITERATIONS).hex()


def pin_is_set() -> bool:
    return PIN_FILE.exists()


def check_pin(pin) -> tuple:
    """(ok, error response). Guards against simply trying all 10000 PINs."""
    if not isinstance(pin, str) or not re.fullmatch(r"\d{4}", pin):
        return False, (jsonify({"error": "PIN muss vierstellig sein."}), 400)
    if not pin_is_set():
        return False, (jsonify({"error": "Es ist noch kein PIN vergeben."}), 409)

    with pin_lock:
        now = time.monotonic()
        if now < pin_state["locked_until"]:
            return False, (jsonify({"error": "Zu viele Fehlversuche.",
                                    "retryIn": round(pin_state["locked_until"] - now)}), 429)

    stored = json.loads(PIN_FILE.read_text())
    ok = hmac.compare_digest(hash_pin(pin, bytes.fromhex(stored["salt"])), stored["hash"])

    with pin_lock:
        if ok:
            # Der richtige PIN wird nie gebremst: sonst liefe schon das
            # Speichern direkt nach dem Entsperren in die Sperre.
            pin_state["failures"] = 0
            return True, None
        now = time.monotonic()
        if now - pin_state["last_fail"] < PIN_MIN_INTERVAL:
            return False, (jsonify({"error": "Zu schnell - bitte kurz warten."}), 429)
        pin_state["last_fail"] = now
        pin_state["failures"] += 1
        if pin_state["failures"] >= PIN_MAX_FAILURES:
            pin_state["failures"] = 0
            pin_state["locked_until"] = now + PIN_LOCKOUT
    return False, (jsonify({"error": "Falscher PIN."}), 401)


ID_FROM_URL = re.compile(r"(?:playlist|album)/([0-9a-fA-F-]+)")


def parse_item(line: str) -> dict:
    """One line of the playlist field: a UUID, an album number or a Tidal link."""
    text = line.strip()
    if not text:
        return {}
    match = ID_FROM_URL.search(text)
    if match:
        text = match.group(1)
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", text):
        return {"type": "playlist", "tidalId": text}
    if text.isdigit():
        return {"type": "album", "tidalId": text}
    raise ValueError(line.strip())


def save_tokens(tokens):
    SESSION_FILE.write_text(json.dumps(tokens))


def refresh_access_token() -> str:
    refreshed = auth_api.refresh_token(tokens["refresh_token"])
    tokens["access_token"] = refreshed.access_token
    save_tokens(tokens)
    return refreshed.access_token


def build_api(tokens) -> TidalAPI:
    client = TidalClient(
        token=tokens["access_token"],
        cache_name=str(API_CACHE),
        on_token_expiry=refresh_access_token,
    )
    return TidalAPI(client, str(tokens["user_id"]), tokens["country_code"])


def load_saved_login():
    """Restore a stored login, ignoring an unusable session file rather than
    crashing on startup (e.g. one written by the earlier tidalapi backend)."""
    global api, tokens
    if not SESSION_FILE.exists():
        return
    try:
        saved = json.loads(SESSION_FILE.read_text())
        if not all(k in saved for k in ("access_token", "refresh_token", "user_id", "country_code")):
            return
        tokens = saved
        api = build_api(tokens)
    except Exception as exc:  # noqa: BLE001
        print(f"Gespeicherte Sitzung unbrauchbar ({exc}), bitte neu anmelden.")


load_saved_login()
if api is not None:
    login_state = {"status": "logged_in"}
else:
    print("Nicht bei Tidal eingeloggt. Bitte http://<server>:8080/login/start öffnen.")


def poll_for_login(device):
    global api, login_state, tokens
    deadline = time.time() + device.expiresIn
    while time.time() < deadline:
        time.sleep(device.interval)
        try:
            auth = auth_api.get_auth(device.deviceCode)
        except AuthClientError as exc:
            if exc.error == "authorization_pending":
                continue
            login_state = {"status": "error", "message": str(exc)}
            return

        tokens = {
            "access_token": auth.access_token,
            "refresh_token": auth.refresh_token,
            "user_id": auth.user.userId,
            "country_code": auth.user.countryCode,
        }
        save_tokens(tokens)
        api = build_api(tokens)
        login_state = {"status": "logged_in"}
        return

    login_state = {"status": "expired"}


LOGIN_PAGE = """
<body style="font-family: sans-serif; max-width: 460px; margin: 40px auto; line-height: 1.5">
  <h2>Tidal-Anmeldung</h2>
  <p><a href="{url}" target="_blank" style="font-size: 1.2rem">Hier tippen und mit dem
     Tidal-Konto bestätigen</a></p>
  <p>Code: <b>{code}</b></p>
  <p id="state">Warte auf Bestätigung …</p>
  <script>
    setInterval(async () => {{
      const s = await (await fetch("/login/status")).json();
      if (s.status === "logged_in") document.getElementById("state").textContent =
        "Angemeldet! Das Dashboard kann jetzt Musik abspielen.";
      else if (s.status !== "waiting") document.getElementById("state").textContent =
        "Fehlgeschlagen (" + s.status + "). Seite neu laden für einen neuen Code.";
    }}, 2000);
  </script>
</body>
"""


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/login/start")
def login_start():
    global login_state
    if login_state.get("status") != "waiting":
        device = auth_api.get_device_auth()
        url = device.verificationUriComplete
        if not url.startswith("http"):
            url = "https://" + url
        login_state = {"status": "waiting", "url": url, "code": device.userCode}
        threading.Thread(target=poll_for_login, args=(device,), daemon=True).start()
    return LOGIN_PAGE.format(url=login_state["url"], code=login_state["code"])


@app.route("/login/status")
def login_status():
    return jsonify(login_state)


def track_info(track):
    album = getattr(track, "album", None)
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist.name if track.artist else "",
        "duration": track.duration,
        # Passed along so a cover can be shown without one API call per row.
        "cover": getattr(album, "cover", None) if album else None,
    }


def is_playable(track, allow_explicit=False):
    """Skip what the browser could not play anyway: tracks the account may not
    stream (tiddl checks the same flag before downloading) and Dolby Atmos,
    which is delivered as eac3/ac4. Tracks Tidal marks as explicit are left
    out too - this dashboard is for a child - unless that filter was switched
    off in the settings."""
    if not getattr(track, "allowStreaming", True):
        return False
    if not allow_explicit and getattr(track, "explicit", False):
        return False
    return "DOLBY_ATMOS" not in (getattr(track, "audioModes", None) or [])


def collect_tracks(fetch_page):
    tracks, offset = [], 0
    while True:
        page = fetch_page(100, offset)
        tracks += [entry.item for entry in page.items if entry.type == "track"]
        offset += page.limit
        if offset >= page.totalNumberOfItems:
            allow_explicit = bool(load_config().get("allowExplicit"))
            return [t for t in tracks if is_playable(t, allow_explicit)]


@app.route("/api/queue/<item_type>/<item_id>")
def queue(item_type, item_id):
    if api is None:
        return jsonify({"error": "Nicht bei Tidal eingeloggt. Bitte /login/start öffnen."}), 401
    try:
        if item_type == "track":
            tracks = [api.get_track(item_id)]
        elif item_type == "playlist":
            tracks = collect_tracks(lambda limit, offset: api.get_playlist_items(item_id, limit, offset))
        elif item_type == "album":
            tracks = collect_tracks(lambda limit, offset: api.get_album_items(item_id, limit, offset))
        else:
            abort(400)
    except Exception as exc:  # noqa: BLE001 - surface the real Tidal error to the frontend
        return jsonify({"error": str(exc)}), 502

    return jsonify([track_info(t) for t in tracks])


@app.route("/api/discover")
def discover():
    """Playlists related to the configured ones.

    Tidal has no "playlists similar to this playlist" endpoint - only similar
    artists, radios and similar albums, none of which return playlists. So we
    go via the artists actually present in the configured playlists and use
    the one endpoint that does return playlists: search.
    """
    if api is None:
        return jsonify({"error": "Nicht bei Tidal eingeloggt."}), 401

    config = load_config()
    if not config.get("discover"):
        return jsonify([])

    configured = {item.get("tidalId") for item in config.get("items", [])}
    artists, seen = [], set()
    try:
        for item in config.get("items", []):
            if item.get("type") != "playlist":
                continue
            for entry in api.get_playlist_items(item["tidalId"], 50, 0).items:
                name = entry.item.artist.name if entry.item.artist else None
                if name and name not in seen:
                    seen.add(name)
                    artists.append(name)

        found, ids = [], set()
        for name in random.sample(artists, min(3, len(artists))):
            # Nur der playlists-Zweig der Suche, also niemals einzelne Titel.
            for playlist in api.get_search(name).playlists.items:
                if playlist.uuid in configured or playlist.uuid in ids:
                    continue
                # Eine leere Playlist wuerde beim Antippen nur ins Leere laufen.
                if not playlist.numberOfTracks:
                    continue
                ids.add(playlist.uuid)
                found.append({"type": "playlist", "tidalId": playlist.uuid,
                              "title": playlist.title})
    except Exception as exc:  # noqa: BLE001 - the section simply stays empty
        return jsonify({"error": str(exc)}), 502

    random.shuffle(found)
    return jsonify(found[:DISCOVER_LIMIT])


@app.route("/api/favorites/add/<track_id>", methods=["POST"])
def favorites_add(track_id):
    """Put a track into the configured favourites playlist.

    Tidal wants the playlist's current ETag for any change to it, so the
    playlist is read first and the tag sent back as If-None-Match. onDupes=SKIP
    leaves it to Tidal to refuse a track that is already in there.
    """
    if api is None:
        return jsonify({"error": "Nicht bei Tidal eingeloggt."}), 401
    if not track_id.isdigit():
        abort(400)

    playlist_id = load_config().get("favorites")
    if not playlist_id:
        return jsonify({"error": "Keine favorites-Playlist in der config.json."}), 400

    global last_favorite_add
    with favorite_lock:
        waited = time.monotonic() - last_favorite_add
        if waited < FAVORITE_COOLDOWN:
            return jsonify({"error": "Zu schnell – bitte kurz warten.",
                            "retryIn": round(FAVORITE_COOLDOWN - waited, 1)}), 429
        last_favorite_add = time.monotonic()

    url = f"https://api.tidal.com/v1/playlists/{playlist_id}"
    auth = {"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json"}
    try:
        current = requests.get(url, params={"countryCode": tokens["country_code"]},
                               headers=auth, timeout=15)
        if current.status_code == 401:
            auth["Authorization"] = f"Bearer {refresh_access_token()}"
            current = requests.get(url, params={"countryCode": tokens["country_code"]},
                                   headers=auth, timeout=15)
        current.raise_for_status()

        resp = requests.post(
            url + "/items",
            params={"countryCode": tokens["country_code"], "limit": 100},
            data={
                "trackIds": track_id,
                "toIndex": current.json().get("numberOfTracks", 0),
                "onArtifactNotFound": "SKIP",
                "onDupes": "SKIP",
            },
            headers={**auth, "If-None-Match": current.headers.get("etag", "")},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502

    return jsonify({"added": bool(resp.json().get("addedItemIds"))})


@app.route("/api/info/<item_type>/<item_id>")
def info(item_type, item_id):
    """Name as it is in Tidal, so tiles do not depend on the title in
    config.json."""
    if api is None:
        return jsonify({"error": "Nicht bei Tidal eingeloggt."}), 401
    try:
        if item_type == "playlist":
            title = api.get_playlist(item_id).title
        elif item_type == "album":
            title = api.get_album(item_id).title
        else:
            abort(400)
    except Exception as exc:  # noqa: BLE001 - the tile keeps its configured title
        return jsonify({"error": str(exc)}), 502
    return jsonify({"title": title})


@app.route("/api/art/<item_type>/<item_id>")
def art(item_type, item_id):
    """Cover image for a tile. Proxied rather than linked so the browser only
    ever talks to this server."""
    if api is None:
        abort(404)
    try:
        if item_type == "playlist":
            playlist = api.get_playlist(item_id)
            uid = playlist.squareImage or playlist.image
        elif item_type == "album":
            uid = api.get_album(item_id).cover
        elif item_type == "cover":
            # Comes straight from the URL, unlike the ids above, which the API
            # gave us - so this one gets checked before it lands in a path.
            if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", item_id):
                abort(404)
            uid = item_id
        else:
            abort(404)
        if not uid:
            abort(404)

        # Tidal stores the uuid as a path: 1234-5678-... -> 1234/5678/...
        upstream = requests.get(
            f"https://resources.tidal.com/images/{uid.replace('-', '/')}/640x640.jpg",
            timeout=15,
        )
        if not upstream.ok:
            abort(404)
    except Exception:  # noqa: BLE001 - the tile falls back to its emoji
        abort(404)

    return Response(
        upstream.content,
        mimetype=upstream.headers.get("Content-Type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


def playback_urls(track_id, quality, retry=True):
    """Ask Tidal where the audio lives. Only "bts" manifests are accepted:
    they point at one finished file, while DASH would hand us segments that a
    plain <audio> element cannot play. This mirrors tidarr's player, which
    uses playbackinfo rather than the downloader's playbackinfopostpaywall."""
    resp = requests.get(
        f"https://api.tidal.com/v1/tracks/{track_id}/playbackinfo",
        params={
            "countryCode": tokens["country_code"],
            "audioquality": quality,
            "playbackmode": "STREAM",
            "assetpresentation": "FULL",
        },
        headers={"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json"},
        timeout=15,
    )
    if resp.status_code == 401 and retry:
        refresh_access_token()
        return playback_urls(track_id, quality, retry=False)
    if not resp.ok:
        return None

    data = resp.json()
    if data.get("manifestMimeType") != "application/vnd.tidal.bts":
        return None
    manifest = json.loads(base64.b64decode(data["manifest"]))
    return manifest.get("urls")


@app.route("/api/stream/<track_id>")
def stream(track_id):
    if api is None:
        return jsonify({"error": "Nicht bei Tidal eingeloggt. Bitte /login/start öffnen."}), 401

    source = None
    for quality in QUALITIES:
        try:
            urls = playback_urls(track_id, quality)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 502
        if urls:
            source = urls[0]
            break
    if source is None:
        return jsonify({"error": "Keine abspielbare Qualität für diesen Titel."}), 502

    # Pass the browser's Range request straight through to Tidal and hand its
    # answer back unchanged. That way playback starts immediately instead of
    # after a full download, and Safari gets the 206 plus Content-Length it
    # insists on - both come from Tidal's CDN.
    upstream = requests.get(
        source,
        headers={"Range": request.headers["Range"]} if "Range" in request.headers else {},
        stream=True,
        timeout=30,
    )
    if not upstream.ok:
        upstream.close()
        return jsonify({"error": f"Tidal antwortete mit {upstream.status_code}."}), 502

    passthrough = ("Content-Type", "Content-Length", "Accept-Ranges", "Content-Range",
                   "Cache-Control", "Last-Modified", "ETag")

    def body():
        with upstream:
            yield from upstream.iter_content(chunk_size=65536)

    return Response(
        stream_with_context(body()),
        status=upstream.status_code,
        headers={h: upstream.headers[h] for h in passthrough if h in upstream.headers},
    )


@app.route("/api/config")
def get_config():
    """What the board needs. Replaces the formerly static config.json, which
    still exists in the image but is only the seed."""
    config = load_config()
    return jsonify({
        "discover": bool(config.get("discover")),
        "favorites": config.get("favorites", ""),
        "items": config.get("items", []),
    })


@app.route("/api/settings/state")
def settings_state():
    return jsonify({"pinSet": pin_is_set()})


def settings_payload(config) -> dict:
    """The settings as the form shows them."""
    lines = [item.get("tidalId", "") for item in config.get("items", [])]
    return {
        "discover": bool(config.get("discover")),
        "favorites": config.get("favorites", ""),
        "playlists": "\n".join(line for line in lines if line),
        "allowExplicit": bool(config.get("allowExplicit")),
    }


@app.route("/api/settings/pin", methods=["POST"])
def settings_set_pin():
    """Only ever once - a set PIN cannot be replaced from the outside."""
    if pin_is_set():
        return jsonify({"error": "Es ist bereits ein PIN vergeben."}), 409
    pin = (request.get_json(silent=True) or {}).get("pin")
    if not isinstance(pin, str) or not re.fullmatch(r"\d{4}", pin):
        return jsonify({"error": "PIN muss aus vier Ziffern bestehen."}), 400

    salt = os.urandom(16)
    PIN_FILE.write_text(json.dumps({"salt": salt.hex(), "hash": hash_pin(pin, salt)}))
    try:
        PIN_FILE.chmod(0o600)
    except OSError:  # noqa: PERF203 - a mount may not allow it, that is fine
        pass
    return jsonify({"settings": settings_payload(load_config())})


@app.route("/api/settings/unlock", methods=["POST"])
def settings_unlock():
    ok, error = check_pin((request.get_json(silent=True) or {}).get("pin"))
    if not ok:
        return error
    return jsonify({"settings": settings_payload(load_config())})


@app.route("/api/settings/save", methods=["POST"])
def settings_save():
    body = request.get_json(silent=True) or {}
    ok, error = check_pin(body.get("pin"))
    if not ok:
        return error

    incoming = body.get("settings") or {}
    favorites = ""
    if incoming.get("favorites"):
        try:
            favorites = parse_item(str(incoming["favorites"]))["tidalId"]
        except (ValueError, KeyError):
            return jsonify({"error": "Favoriten-Liste: keine gültige Playlist-ID."}), 400

    config = load_config()
    # Titel und Emoji sind nur Rückfallwerte, sollen aber nicht verloren gehen.
    known = {item.get("tidalId"): item for item in config.get("items", [])}
    items = []
    for line in str(incoming.get("playlists", "")).splitlines():
        try:
            parsed = parse_item(line)
        except ValueError as exc:
            return jsonify({"error": f"Nicht erkannt: {exc}"}), 400
        if not parsed:
            continue
        old = known.get(parsed["tidalId"], {})
        if old.get("title"):
            parsed["title"] = old["title"]
        if old.get("emoji"):
            parsed["emoji"] = old["emoji"]
        items.append(parsed)

    config.update({
        "discover": bool(incoming.get("discover")),
        "allowExplicit": bool(incoming.get("allowExplicit")),
        "favorites": favorites,
        "items": items,
    })
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    return jsonify({"saved": True, "settings": settings_payload(config)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)

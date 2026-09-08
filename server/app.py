import collections
import json
import os
import pathlib
import threading
import time

import requests
from flask import Flask, abort, jsonify, send_file, send_from_directory
from tiddl.core.api import TidalAPI, TidalClient
from tiddl.core.auth.api import AuthAPI
from tiddl.core.auth.exceptions import AuthClientError
from tiddl.core.utils.parse import parse_track_stream

BASE_DIR = pathlib.Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR.parent
DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FILE = DATA_DIR / "tidal_session.json"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
API_CACHE = DATA_DIR / "api_cache"

# HIGH returns a "bts" manifest, i.e. ready-to-play m4a urls. Only
# HI_RES_LOSSLESS comes back as MPEG-DASH, which would need reassembly.
QUALITY = "HIGH"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

auth_api = AuthAPI()
api: TidalAPI | None = None
login_state = {"status": "logged_out"}

# Safari fires several requests for the same track at once; without a lock they
# would all download into the same file and corrupt it.
download_locks = collections.defaultdict(threading.Lock)


def save_tokens(tokens):
    SESSION_FILE.write_text(json.dumps(tokens))


def build_api(tokens) -> TidalAPI:
    def on_token_expiry():
        refreshed = auth_api.refresh_token(tokens["refresh_token"])
        tokens["access_token"] = refreshed.access_token
        save_tokens(tokens)
        return refreshed.access_token

    client = TidalClient(
        token=tokens["access_token"],
        cache_name=str(API_CACHE),
        on_token_expiry=on_token_expiry,
    )
    return TidalAPI(client, str(tokens["user_id"]), tokens["country_code"])


def load_saved_api():
    """Restore a stored login, ignoring an unusable session file rather than
    crashing on startup (e.g. one written by the earlier tidalapi backend)."""
    if not SESSION_FILE.exists():
        return None
    try:
        tokens = json.loads(SESSION_FILE.read_text())
        if not all(k in tokens for k in ("access_token", "refresh_token", "user_id", "country_code")):
            return None
        return build_api(tokens)
    except Exception as exc:  # noqa: BLE001
        print(f"Gespeicherte Sitzung unbrauchbar ({exc}), bitte neu anmelden.")
        return None


api = load_saved_api()
if api is not None:
    login_state = {"status": "logged_in"}
else:
    print("Nicht bei Tidal eingeloggt. Bitte http://<server>:8080/login/start öffnen.")


def poll_for_login(device):
    global api, login_state
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
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist.name if track.artist else "",
    }


def collect_tracks(fetch_page):
    tracks, offset = [], 0
    while True:
        page = fetch_page(100, offset)
        tracks += [entry.item for entry in page.items if entry.type == "track"]
        offset += page.limit
        if offset >= page.totalNumberOfItems:
            return tracks


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


@app.route("/api/stream/<track_id>")
def stream(track_id):
    if api is None:
        return jsonify({"error": "Nicht bei Tidal eingeloggt. Bitte /login/start öffnen."}), 401
    if not track_id.isdigit():  # the id becomes a filename below
        abort(400)

    # The finished file is served rather than a live stream: Safari rejects a
    # chunked response of unknown length with MEDIA_ERR_SRC_NOT_SUPPORTED and
    # asks for byte ranges instead.
    cached = CACHE_DIR / f"{track_id}.m4a"

    with download_locks[track_id]:
        if not cached.exists():
            try:
                urls, _ = parse_track_stream(api.get_track_stream(track_id, QUALITY))
                partial = cached.with_suffix(".part")
                with partial.open("wb") as out:
                    for url in urls:
                        with requests.get(url, stream=True, timeout=30) as resp:
                            resp.raise_for_status()
                            for chunk in resp.iter_content(chunk_size=65536):
                                out.write(chunk)
                partial.replace(cached)
            except Exception as exc:  # noqa: BLE001
                cached.with_suffix(".part").unlink(missing_ok=True)
                return jsonify({"error": str(exc)}), 502

    return send_file(cached, mimetype="audio/mp4", conditional=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)

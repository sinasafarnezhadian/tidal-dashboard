import base64
import json
import os
import pathlib
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
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist.name if track.artist else "",
    }


def is_playable(track):
    """Skip what the browser could not play anyway: tracks the account may not
    stream (tiddl checks the same flag before downloading) and Dolby Atmos,
    which is delivered as eac3/ac4."""
    if not getattr(track, "allowStreaming", True):
        return False
    return "DOLBY_ATMOS" not in (getattr(track, "audioModes", None) or [])


def collect_tracks(fetch_page):
    tracks, offset = [], 0
    while True:
        page = fetch_page(100, offset)
        tracks += [entry.item for entry in page.items if entry.type == "track"]
        offset += page.limit
        if offset >= page.totalNumberOfItems:
            return [t for t in tracks if is_playable(t)]


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)

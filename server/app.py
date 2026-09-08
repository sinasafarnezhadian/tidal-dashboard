import datetime
import json
import os
import pathlib

import requests
import tidalapi
from flask import Flask, abort, jsonify, request, send_file, send_from_directory

BASE_DIR = pathlib.Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR.parent
DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FILE = DATA_DIR / "tidal_session.json"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

session = tidalapi.Session()
# Stay on AAC: concatenated AAC segments are a playable .m4a as-is. LOSSLESS
# would hand us FLAC-in-MP4, which needs an ffmpeg remux before a browser can
# play it (that is exactly where tiddl calls extract_flac).
session.audio_quality = tidalapi.Quality.low_320k


def save_session():
    SESSION_FILE.write_text(json.dumps({
        "token_type": session.token_type,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expiry_time": session.expiry_time.isoformat() if session.expiry_time else None,
    }))


def load_session():
    if not SESSION_FILE.exists():
        return False
    data = json.loads(SESSION_FILE.read_text())
    expiry = (
        datetime.datetime.fromisoformat(data["expiry_time"])
        if data.get("expiry_time")
        else None
    )
    try:
        return session.load_oauth_session(
            data["token_type"],
            data["access_token"],
            data.get("refresh_token"),
            expiry,
            is_pkce=True,
        )
    except Exception:  # noqa: BLE001 - fall through to "not logged in"
        return False


LOGGED_IN = load_session()
if not LOGGED_IN:
    print("Nicht bei Tidal eingeloggt. Bitte http://<server>:8080/login/start im Browser öffnen.")


def track_info(track):
    return {
        "id": track.id,
        "title": track.name,
        "artist": track.artist.name if track.artist else "",
    }


def require_login():
    if not session.check_login():
        return jsonify({
            "error": "Nicht bei Tidal eingeloggt. Bitte /login/start im Browser öffnen."
        }), 401
    return None


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/login/start")
def login_start():
    url = session.pkce_login_url()
    return f"""
    <body style="font-family: sans-serif; max-width: 500px; margin: 40px auto;">
      <p><a href="{url}" target="_blank">1. Hier klicken und mit dem Tidal-Konto einloggen</a></p>
      <p>2. Nach dem Login landest du auf einer "Oops"-Fehlerseite &ndash; die komplette
         Adresse aus der Adresszeile kopieren und hier einfügen:</p>
      <form method="post" action="/login/callback">
        <input type="text" name="url" style="width: 100%" placeholder="https://...">
        <button type="submit">Bestätigen</button>
      </form>
    </body>
    """


@app.route("/login/callback", methods=["POST"])
def login_callback():
    url_redirect = request.form.get("url", "")
    try:
        token_dict = session.pkce_get_auth_token(url_redirect)
        session.process_auth_token(token_dict, is_pkce_token=True)
        save_session()
    except Exception as exc:  # noqa: BLE001
        return f"Login fehlgeschlagen: {exc}", 400
    return "Login erfolgreich! Dieses Fenster kann geschlossen werden."


@app.route("/api/queue/<item_type>/<item_id>")
def queue(item_type, item_id):
    if (err := require_login()) is not None:
        return err
    try:
        if item_type == "track":
            tracks = [session.track(item_id)]
        elif item_type == "playlist":
            tracks = session.playlist(item_id).tracks()
        elif item_type == "album":
            tracks = session.album(item_id).tracks()
        else:
            abort(400)
    except Exception as exc:  # noqa: BLE001 - surface the real Tidal error to the frontend
        return jsonify({"error": str(exc)}), 502

    return jsonify([track_info(t) for t in tracks])


@app.route("/api/stream/<track_id>")
def stream(track_id):
    if (err := require_login()) is not None:
        return err
    if not track_id.isdigit():  # the id becomes a filename below
        abort(400)
    # Tidal serves most tracks as MPEG-DASH: an init segment plus media segments.
    # Concatenated they form a plain .m4a, so we assemble the whole file first and
    # then serve it - Safari rejects a chunked response of unknown length with
    # MEDIA_ERR_SRC_NOT_SUPPORTED and only accepts byte-range requests.
    cached = CACHE_DIR / f"{track_id}.m4a"

    if not cached.exists():
        try:
            manifest = session.track(track_id).get_stream().get_stream_manifest()
            urls = manifest.get_urls()
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

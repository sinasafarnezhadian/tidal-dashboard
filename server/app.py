import os
import pathlib

import tidalapi
from flask import Flask, abort, jsonify, send_from_directory

BASE_DIR = pathlib.Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR.parent
DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FILE = DATA_DIR / "tidal_session.json"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

session = tidalapi.Session()
session.login_session_file(SESSION_FILE)


def track_info(track):
    return {
        "id": track.id,
        "title": track.name,
        "artist": track.artist.name if track.artist else "",
    }


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/queue/<item_type>/<item_id>")
def queue(item_type, item_id):
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
    try:
        media = session.track(track_id).get_stream()
        manifest = media.get_stream_manifest()
        is_direct_url = getattr(media, "is_bts", None) or getattr(manifest, "is_bts", None)
        if not is_direct_url:
            return jsonify({
                "error": "Nur MPEG-DASH-Stream verfügbar (höchste Tidal-Qualität). "
                         "Bitte im Tidal-Konto die Streaming-Qualität auf 'High' statt "
                         "'Lossless/Max' stellen, dann neu versuchen."
            }), 502
        urls = manifest.get_urls()
        return jsonify({"url": urls[0]})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

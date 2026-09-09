const collections = document.getElementById("collections");
const discoverGrid = document.getElementById("discover");
const discoverDivider = document.getElementById("discover-divider");
const audio = document.getElementById("audio");

const player = document.getElementById("player");
const npTitle = document.getElementById("np-title");
const npArtist = document.getElementById("np-artist");
const playPauseBtn = document.getElementById("play-pause-btn");
const prevBtn = document.getElementById("prev-btn");
const nextBtn = document.getElementById("next-btn");
const seek = document.getElementById("seek");
const timeCurrent = document.getElementById("time-current");
const timeTotal = document.getElementById("time-total");
const statusLine = document.getElementById("player-status");
const queueList = document.getElementById("queue-list");
const queueToggle = document.getElementById("queue-toggle");
const favBtn = document.getElementById("fav-btn");
const favoritesGrid = document.getElementById("favorites");
const favoritesDivider = document.getElementById("favorites-divider");

let queue = [];
let queueIndex = 0;
let trackLoaded = false;
let failedInARow = 0;
let scrubbing = false;
// Beim Antippen einer Zeile darf die Liste nicht springen - sonst rutscht der
// Titel unter dem Finger weg. Beim automatischen Weiterlaufen dagegen schon.
let keepQueueScroll = false;

// iOS only starts audio that began inside a real tap. Tapping a card has to
// fetch the track list first, and that await would spend the tap - so the
// element is unlocked with a silent clip while the tap is still valid.
const SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";
let audioUnlocked = false;

function unlockAudio() {
  if (audioUnlocked) return;
  audioUnlocked = true;
  audio.src = SILENT_WAV;
  audio.play().catch(() => {});
}

// Bestätigungen sollen kurz stehen bleiben. Ein spät eintreffendes Aufräumen
// (etwa das erfolgreiche play()-Versprechen) darf sie nicht wegwischen, darum
// hält holdMs die Meldung so lange gegen leere Meldungen.
let statusHoldUntil = 0;
let statusClearTimer = 0;

function setStatus(text, holdMs) {
  const now = Date.now();
  if (!text && now < statusHoldUntil) {
    // Nicht verwerfen, sondern nachholen, sobald die Haltezeit vorbei ist.
    clearTimeout(statusClearTimer);
    statusClearTimer = setTimeout(function () { setStatus(""); }, statusHoldUntil - now);
    return;
  }
  clearTimeout(statusClearTimer);
  statusLine.textContent = text;
  statusHoldUntil = text && holdMs ? now + holdMs : 0;
}

const PLAYED_COLOR = getComputedStyle(document.documentElement)
  .getPropertyValue("--accent-green")
  .trim();

// Set the gradient from here rather than via a CSS variable inside calc(),
// which older WebKit (iOS 12) does not evaluate reliably.
function paintProgress() {
  const max = Number(seek.max) || 0;
  const pct = max ? (Number(seek.value) / max) * 100 : 0;
  seek.style.backgroundImage =
    "linear-gradient(to right, " +
    PLAYED_COLOR + " 0%, " + PLAYED_COLOR + " " + pct + "%, " +
    "transparent " + pct + "%, transparent 100%)";
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

// The queue only earns its space when there is more than one track.
function renderQueueList() {
  queueList.innerHTML = "";
  applyQueueCollapsed();
  if (queue.length < 2) return;

  queue.forEach(function (track, index) {
    const row = document.createElement("li");
    row.className = "queue-item";
    row.innerHTML =
      '<span class="queue-index">' + (index + 1) + "</span>" +
      '<span class="queue-text"><span class="queue-title">' + track.title + "</span>" +
      (track.artist ? '<span class="queue-artist">' + track.artist + "</span>" : "") +
      "</span>";
    row.addEventListener("click", function () {
      if (index === queueIndex) {
        togglePlayPause();
        return;
      }
      keepQueueScroll = true;
      queueIndex = index;
      playCurrentTrack();
    });
    queueList.appendChild(row);
  });
}

let queueCollapsed = false;

function applyQueueCollapsed() {
  queueList.hidden = queueCollapsed || queue.length < 2;
  queueToggle.hidden = queue.length < 2;
  queueToggle.textContent = queueCollapsed ? "▼" : "▲";
}

queueToggle.addEventListener("click", function () {
  queueCollapsed = !queueCollapsed;
  applyQueueCollapsed();
});

function highlightCurrentInQueue() {
  const rows = queueList.children;
  for (let i = 0; i < rows.length; i++) {
    rows[i].className = i === queueIndex ? "queue-item active" : "queue-item";
  }
  if (keepQueueScroll) {
    keepQueueScroll = false;
    return;
  }

  const active = rows[queueIndex];
  // scrollTop instead of scrollIntoView(options), which older Safari ignores.
  if (active && queueList.scrollHeight > queueList.clientHeight) {
    const top = active.offsetTop - queueList.clientHeight / 2 + active.offsetHeight / 2;
    queueList.scrollTop = Math.max(0, top);
  }
}

function renderTrackInfo() {
  const track = queue[queueIndex];
  if (!track) return;
  npTitle.textContent = track.title;
  npArtist.textContent = track.artist || "";
  prevBtn.disabled = queueIndex === 0;
  nextBtn.disabled = queueIndex === queue.length - 1;
  // Tidal knows the length, so show it before the audio metadata arrives.
  seek.max = track.duration || 0;
  timeTotal.textContent = formatTime(track.duration || 0);
  highlightCurrentInQueue();
}

function playCurrentTrack() {
  const track = queue[queueIndex];
  if (!track) return;
  audio.src = `/api/stream/${track.id}`;
  trackLoaded = true;
  seek.value = 0;
  timeCurrent.textContent = "0:00";
  paintProgress();
  renderTrackInfo();
  audio
    .play()
    .then(() => {
      failedInARow = 0;
      setStatus("");
    })
    .catch((err) => setStatus(`${err.name}: ${err.message}`));
}

function changeTrack(direction) {
  const newIndex = queueIndex + direction;
  if (newIndex < 0 || newIndex >= queue.length) return;
  queueIndex = newIndex;
  playCurrentTrack();
}

function togglePlayPause() {
  if (!trackLoaded) {
    playCurrentTrack();
  } else if (audio.paused) {
    audio.play().catch((err) => setStatus(`${err.name}: ${err.message}`));
  } else {
    audio.pause();
  }
}

favBtn.addEventListener("click", function () {
  const track = queue[queueIndex];
  if (!track) return;
  favBtn.disabled = true;
  fetch("/api/favorites/add/" + track.id, { method: "POST" })
    .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, d: d }; }); })
    .then(function (r) {
      if (!r.ok) throw new Error(r.d.error || "Konnte nicht hinzufügen");
      // Haltezeit wie die Sperre des Knopfes, damit die Rückmeldung sichtbar bleibt.
      setStatus(r.d.added ? "♥ zu Younes-Favoriten hinzugefügt"
                          : "Ist schon in Younes-Favoriten", 3000);
      if (r.d.added) reloadFavorites();
    })
    .catch(function (err) { setStatus(String(err.message || err), 3000); })
    .then(function () {
      // Sperre passend zum Server-Guard, damit der Knopf nicht zum Hämmern einlädt.
      setTimeout(function () { favBtn.disabled = false; }, 3000);
    });
});

playPauseBtn.addEventListener("click", togglePlayPause);
prevBtn.addEventListener("click", () => changeTrack(-1));
nextBtn.addEventListener("click", () => changeTrack(1));

audio.addEventListener("play", () => (playPauseBtn.textContent = "⏸"));
audio.addEventListener("pause", () => (playPauseBtn.textContent = "▶"));

audio.addEventListener("timeupdate", () => {
  if (scrubbing) return;
  seek.value = audio.currentTime;
  timeCurrent.textContent = formatTime(audio.currentTime);
  paintProgress();
});

audio.addEventListener("durationchange", () => {
  if (Number.isFinite(audio.duration)) {
    seek.max = audio.duration;
    timeTotal.textContent = formatTime(audio.duration);
  }
});

seek.addEventListener("input", () => {
  scrubbing = true;
  timeCurrent.textContent = formatTime(Number(seek.value));
  paintProgress();
});

seek.addEventListener("change", () => {
  audio.currentTime = Number(seek.value);
  scrubbing = false;
});

audio.addEventListener("ended", () => {
  if (!trackLoaded) return; // the silent unlock clip
  if (queueIndex < queue.length - 1) changeTrack(1);
});

// A single broken track should not strand the whole playlist.
audio.addEventListener("error", () => {
  if (!trackLoaded) return;
  failedInARow += 1;
  if (failedInARow < queue.length && queueIndex < queue.length - 1) {
    setStatus("Titel nicht abspielbar – überspringe …");
    changeTrack(1);
    return;
  }
  const code = audio.error ? audio.error.code : "?";
  setStatus(`Audio-Fehler (Code ${code}) – Stream nicht abspielbar.`);
});

async function openItem(item, startIndex) {
  player.hidden = false;
  npTitle.textContent = "…";
  npArtist.textContent = "";
  // Neue Auswahl: alte Bestätigung darf weg, auch wenn ihre Haltezeit läuft.
  statusHoldUntil = 0;
  setStatus("");

  try {
    const res = await fetch(`/api/queue/${item.type}/${item.tidalId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Konnte Titel nicht laden");
    if (!data.length) throw new Error("Keine abspielbaren Titel gefunden.");
    queue = data;
    queueIndex = startIndex && startIndex < data.length ? startIndex : 0;
    failedInARow = 0;
    renderQueueList();
    playCurrentTrack();
  } catch (err) {
    setStatus(String(err.message || err));
  }
}

function renderTile(item, target) {
  const grid = target || collections;
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML =
    '<div class="cover-slot"><span class="emoji">' + (item.emoji || "🎵") + "</span></div>" +
    '<div class="title">' + item.title + "</div>";
  card.addEventListener("click", function () {
    unlockAudio();
    openItem(item);
  });
  grid.appendChild(card);

  // Show Tidal's own artwork and name; the configured ones stay as fallback.
  const cover = new Image();
  cover.className = "cover";
  cover.alt = "";
  cover.addEventListener("load", function () {
    const slot = card.querySelector(".cover-slot");
    slot.innerHTML = "";
    slot.appendChild(cover);
  });
  cover.src = "/api/art/" + item.type + "/" + item.tidalId;

  // Empfehlungen bringen den Namen schon aus der Suche mit.
  if (item.titleFromTidal) return;

  fetch("/api/info/" + item.type + "/" + item.tidalId)
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (data) {
      if (data && data.title) card.querySelector(".title").textContent = data.title;
    })
    .catch(function () {});
}

// Wie eine Kachel, nur dass die ganze Playlist geladen und ab dieser Stelle
// gespielt wird.
function renderFavoriteRow(playlistId, track, index) {
  const row = document.createElement("div");
  row.className = "track-row";
  row.innerHTML =
    (track.cover
      ? '<img class="track-cover" alt="" src="/api/art/cover/' + track.cover + '">'
      : '<span class="track-play" aria-hidden="true">▶</span>') +
    '<span class="track-text"><span class="track-title">' + track.title + "</span>" +
    (track.artist ? '<span class="track-artist">' + track.artist + "</span>" : "") +
    "</span>" +
    // Vorerst nur das Symbol; spaeter wird daraus das "aus Favoriten entfernen".
    '<span class="track-fav" aria-hidden="true">\u2665</span>';
  row.addEventListener("click", function () {
    unlockAudio();
    openItem({ type: "playlist", tidalId: playlistId, title: track.title }, index);
  });
  favoritesGrid.appendChild(row);
}

let favoritesPlaylistId = null;

// Nach dem Hinzufügen neu laden, damit die Liste unten nicht veraltet.
function reloadFavorites() {
  if (!favoritesPlaylistId) return;
  favoritesGrid.innerHTML = "";
  loadFavorites(favoritesPlaylistId);
}

function loadFavorites(playlistId) {
  favoritesPlaylistId = playlistId;
  fetch("/api/queue/playlist/" + playlistId)
    .then(function (res) { return res.ok ? res.json() : []; })
    .then(function (tracks) {
      if (!tracks.length) return;
      favoritesDivider.hidden = false;
      tracks.forEach(function (track, index) {
        renderFavoriteRow(playlistId, track, index);
      });
    })
    .catch(function () {});
}


// Empfehlungen: nur wenn in der config.json eingeschaltet - der Server
// antwortet sonst mit einer leeren Liste.
function loadDiscover() {
  fetch("/api/discover")
    .then(function (res) { return res.ok ? res.json() : []; })
    .then(function (found) {
      if (!found.length) return;
      discoverDivider.hidden = false;
      found.forEach(function (item) {
        item.titleFromTidal = true;
        renderTile(item, discoverGrid);
      });
    })
    .catch(function () {});
}

// Gepflegt wird die Kopie im DATA_DIR, nicht die statische Datei im Image.
fetch("/api/config")
  .then((res) => res.json())
  .then((data) => {
    // Kein bloßes forEach(renderTile): forEach reicht den Index als zweites
    // Argument durch, das hier das Ziel-Grid wäre.
    (data.items || []).forEach((i) => renderTile(i));
    if (data.favorites) loadFavorites(data.favorites);
    loadDiscover();
  })
  .catch((err) => {
    collections.innerHTML = `<p>Konnte Einstellungen nicht laden: ${err}</p>`;
  });


/* --- Einstellungen: Zahnrad, PIN, Formular ------------------------------ */

const overlay = document.getElementById("settings-overlay");
const pinStep = document.getElementById("pin-step");
const pinHint = document.getElementById("pin-hint");
const pinInput = document.getElementById("pin-input");
const pinRepeatField = document.getElementById("pin-repeat-field");
const pinRepeat = document.getElementById("pin-repeat");
const settingsStep = document.getElementById("settings-step");
const sheetStatus = document.getElementById("sheet-status");
const sheetOk = document.getElementById("sheet-ok");

// Der PIN bleibt nur offen, solange das Overlay offen ist; jede Anfrage
// schickt ihn mit, damit es serverseitig keine Sitzung braucht.
let sheetPin = "";
let pinIsSet = false;

function sheetSay(text) {
  sheetStatus.textContent = text;
}

function postJson(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(function (res) {
    return res.json().then(function (data) {
      if (!res.ok) throw new Error(data.error || "Fehler " + res.status);
      return data;
    });
  });
}

function closeSheet() {
  overlay.hidden = true;
  sheetPin = "";
  pinInput.value = "";
  pinRepeat.value = "";
  sheetSay("");
}

function showSettings(settings) {
  pinStep.hidden = true;
  settingsStep.hidden = false;
  sheetOk.textContent = "Speichern";
  document.getElementById("set-discover").checked = !!settings.discover;
  document.getElementById("set-favorites").value = settings.favorites || "";
  document.getElementById("set-playlists").value = settings.playlists || "";
  document.getElementById("set-explicit-off").checked = !!settings.allowExplicit;
  document.getElementById("set-explicit-on").checked = !settings.allowExplicit;
}

document.getElementById("settings-btn").addEventListener("click", function () {
  overlay.hidden = false;
  pinStep.hidden = false;
  settingsStep.hidden = true;
  sheetSay("");
  fetch("/api/settings/state")
    .then(function (res) { return res.json(); })
    .then(function (state) {
      pinIsSet = !!state.pinSet;
      pinRepeatField.hidden = pinIsSet;
      pinHint.textContent = pinIsSet
        ? "Bitte den vierstelligen PIN eingeben."
        : "Noch kein PIN vergeben. Lege jetzt einen vierstelligen PIN fest – er lässt sich später nur durch Löschen der Datei data/settings_pin.json zurücksetzen.";
      sheetOk.textContent = pinIsSet ? "Weiter" : "PIN festlegen";
      pinInput.focus();
    })
    .catch(function (err) { sheetSay(String(err.message || err)); });
});

document.getElementById("sheet-cancel").addEventListener("click", closeSheet);

overlay.addEventListener("click", function (event) {
  // Nur ein Tipp neben das Blatt schließt, nicht einer ins Formular.
  if (event.target === overlay) closeSheet();
});

sheetOk.addEventListener("click", function () {
  sheetOk.disabled = true;
  const done = function () { sheetOk.disabled = false; };

  if (!settingsStep.hidden) {
    postJson("/api/settings/save", {
      pin: sheetPin,
      settings: {
        discover: document.getElementById("set-discover").checked,
        favorites: document.getElementById("set-favorites").value.trim(),
        playlists: document.getElementById("set-playlists").value,
        allowExplicit: document.getElementById("set-explicit-off").checked,
      },
    })
      .then(function () {
        // Neu laden, damit Kacheln, Favoriten und Vorschläge zusammenpassen.
        window.location.reload();
      })
      .catch(function (err) { sheetSay(String(err.message || err)); })
      .then(done);
    return;
  }

  const pin = pinInput.value;
  if (!/^\d{4}$/.test(pin)) {
    sheetSay("Der PIN besteht aus vier Ziffern.");
    done();
    return;
  }
  if (!pinIsSet && pin !== pinRepeat.value) {
    sheetSay("Die beiden PINs stimmen nicht überein.");
    done();
    return;
  }

  postJson(pinIsSet ? "/api/settings/unlock" : "/api/settings/pin", { pin: pin })
    .then(function (data) {
      sheetPin = pin;
      sheetSay("");
      showSettings(data.settings);
    })
    .catch(function (err) { sheetSay(String(err.message || err)); })
    .then(done);
});

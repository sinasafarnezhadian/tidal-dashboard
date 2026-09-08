const collections = document.getElementById("collections");
const trackList = document.getElementById("tracks");
const sectionDivider = document.getElementById("section-divider");
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

function setStatus(text) {
  statusLine.textContent = text;
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
  queueList.hidden = queue.length < 2;
  if (queueList.hidden) return;

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

async function openItem(item) {
  player.hidden = false;
  npTitle.textContent = "…";
  npArtist.textContent = "";
  setStatus("");

  try {
    const res = await fetch(`/api/queue/${item.type}/${item.tidalId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Konnte Titel nicht laden");
    if (!data.length) throw new Error("Keine abspielbaren Titel gefunden.");
    queue = data;
    queueIndex = 0;
    failedInARow = 0;
    renderQueueList();
    playCurrentTrack();
  } catch (err) {
    setStatus(String(err.message || err));
  }
}

function renderTile(item) {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML =
    '<div class="cover-slot"><span class="emoji">' + (item.emoji || "🎵") + "</span></div>" +
    '<div class="title">' + item.title + "</div>";
  card.addEventListener("click", function () {
    unlockAudio();
    openItem(item);
  });
  collections.appendChild(card);

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

  fetch("/api/info/" + item.type + "/" + item.tidalId)
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (data) {
      if (data && data.title) card.querySelector(".title").textContent = data.title;
    })
    .catch(function () {});
}

function renderTrackRow(item) {
  const row = document.createElement("div");
  row.className = "track-row";
  row.innerHTML =
    '<span class="track-play" aria-hidden="true">▶</span>' +
    '<span class="track-emoji">' + (item.emoji || "🎵") + "</span>" +
    '<span class="track-text"><span class="track-title">' + item.title + "</span>" +
    (item.artist ? '<span class="track-artist">' + item.artist + "</span>" : "") +
    "</span>";
  row.addEventListener("click", function () {
    unlockAudio();
    openItem(item);
  });
  trackList.appendChild(row);
}

fetch("config.json")
  .then((res) => res.json())
  .then((data) => {
    const items = data.items || [];
    items.filter((i) => i.type !== "track").forEach(renderTile);
    const tracks = items.filter((i) => i.type === "track");
    tracks.forEach(renderTrackRow);
    sectionDivider.hidden = !tracks.length || tracks.length === items.length;
  })
  .catch((err) => {
    collections.innerHTML = `<p>Konnte config.json nicht laden: ${err}</p>`;
  });

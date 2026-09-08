const grid = document.getElementById("grid");
const overlay = document.getElementById("player-overlay");
const playerTitle = document.getElementById("player-title");
const playerFrameWrap = document.getElementById("player-frame-wrap");
const closeBtn = document.getElementById("close-player");

const audio = document.getElementById("audio");
let queue = [];
let queueIndex = 0;

function renderPlayerControls() {
  const track = queue[queueIndex];
  if (!track) return;

  playerFrameWrap.innerHTML = `
    <div class="now-playing">
      <div class="np-title">${track.title}</div>
      <div class="np-artist">${track.artist || ""}</div>
    </div>
    <div class="player-controls">
      <button id="prev-btn" class="ctrl-btn" ${queueIndex === 0 ? "disabled" : ""} aria-label="Zurück">⏮</button>
      <button id="play-pause-btn" class="ctrl-btn play-btn" aria-label="Play/Pause">${audio.paused ? "▶" : "⏸"}</button>
      <button id="next-btn" class="ctrl-btn" ${queueIndex === queue.length - 1 ? "disabled" : ""} aria-label="Weiter">⏭</button>
    </div>
    <div id="player-status" class="player-status"></div>
  `;

  document.getElementById("play-pause-btn").addEventListener("click", togglePlayPause);
  document.getElementById("prev-btn").addEventListener("click", () => changeTrack(-1));
  document.getElementById("next-btn").addEventListener("click", () => changeTrack(1));
}

function setStatus(text) {
  const el = document.getElementById("player-status");
  if (el) el.textContent = text;
}

let trackLoaded = false;

function resetPlayback() {
  trackLoaded = false;
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
}

// Kept synchronous on purpose: an await before play() would cost us the
// user gesture that iOS requires to let audio start.
function playCurrentTrack() {
  const track = queue[queueIndex];
  if (!track) return;
  audio.src = `/api/stream/${track.id}`;
  trackLoaded = true;
  const playing = audio.play();
  renderPlayerControls();
  setStatus("Lädt …");
  playing
    .then(() => setStatus(""))
    .catch((err) => setStatus(`${err.name}: ${err.message}`));
}

audio.addEventListener("error", () => {
  const code = audio.error ? audio.error.code : "?";
  setStatus(`Audio-Fehler (Code ${code}) – Stream nicht abspielbar.`);
});

function togglePlayPause() {
  if (!trackLoaded) {
    playCurrentTrack();
  } else if (audio.paused) {
    audio.play().catch((err) => setStatus(`${err.name}: ${err.message}`));
  } else {
    audio.pause();
  }
}

function changeTrack(direction) {
  const newIndex = queueIndex + direction;
  if (newIndex < 0 || newIndex >= queue.length) return;
  queueIndex = newIndex;
  playCurrentTrack();
}

function updatePlayButton() {
  const btn = document.getElementById("play-pause-btn");
  if (btn) btn.textContent = audio.paused ? "▶" : "⏸";
}

audio.addEventListener("play", updatePlayButton);
audio.addEventListener("pause", updatePlayButton);

audio.addEventListener("ended", () => {
  if (queueIndex < queue.length - 1) {
    changeTrack(1);
  } else {
    renderPlayerControls();
  }
});

async function openPlayer(item) {
  playerTitle.textContent = item.title;
  overlay.hidden = false;
  playerFrameWrap.innerHTML = "<p>Lädt …</p>";
  resetPlayback();

  try {
    const res = await fetch(`/api/queue/${item.type}/${item.tidalId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Konnte Titel nicht laden");
    queue = data;
    queueIndex = 0;
    renderPlayerControls();
  } catch (err) {
    playerFrameWrap.innerHTML = `<p>${err.message || err}</p>`;
  }
}

function closePlayer() {
  overlay.hidden = true;
  resetPlayback();
  queue = [];
  queueIndex = 0;
}

closeBtn.addEventListener("click", closePlayer);
overlay.addEventListener("click", (e) => {
  if (e.target === overlay) closePlayer();
});

function renderCard(item) {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div class="type-tag">${item.type === "playlist" ? "Playlist" : item.type === "album" ? "Album" : "Lied"}</div>
    <div class="emoji">${item.emoji || "🎵"}</div>
    <div class="title">${item.title}</div>
    ${item.artist ? `<div class="artist">${item.artist}</div>` : ""}
  `;
  card.addEventListener("click", () => openPlayer(item));
  grid.appendChild(card);
}

fetch("config.json")
  .then((res) => res.json())
  .then((data) => {
    (data.items || []).forEach(renderCard);
  })
  .catch((err) => {
    grid.innerHTML = `<p>Konnte config.json nicht laden: ${err}</p>`;
  });

const grid = document.getElementById("grid");
const overlay = document.getElementById("player-overlay");
const playerTitle = document.getElementById("player-title");
const playerFrameWrap = document.getElementById("player-frame-wrap");
const closeBtn = document.getElementById("close-player");

const EMBED_HEIGHT = {
  track: 180,
  playlist: 420,
  album: 420
};

function embedUrl(item) {
  const type = item.type === "playlist" ? "playlists"
    : item.type === "album" ? "albums"
    : "tracks";
  return `https://embed.tidal.com/${type}/${item.tidalId}?layout=gridify`;
}

function openPlayer(item) {
  playerTitle.textContent = item.title;
  const height = EMBED_HEIGHT[item.type] || 200;
  playerFrameWrap.innerHTML = "";
  const iframe = document.createElement("iframe");
  iframe.src = embedUrl(item);
  iframe.height = height;
  iframe.allow = "encrypted-media; autoplay";
  playerFrameWrap.appendChild(iframe);
  overlay.hidden = false;
}

function closePlayer() {
  overlay.hidden = true;
  playerFrameWrap.innerHTML = "";
}

closeBtn.addEventListener("click", closePlayer);
overlay.addEventListener("click", (e) => {
  if (e.target === overlay) closePlayer();
});

function renderCard(item) {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div class="type-tag">${item.type === "playlist" ? "Playlist" : "Lied"}</div>
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

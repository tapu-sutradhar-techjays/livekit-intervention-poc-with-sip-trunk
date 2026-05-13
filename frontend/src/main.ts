import { Room, RoomEvent } from "livekit-client";
import { attachTranscript } from "./transcript";
import { takeOver, handBack } from "./takeover";

const statusEl = document.getElementById("status")!;
const transcriptEl = document.getElementById("transcript")!;
const placeBtn = document.getElementById("place-call") as HTMLButtonElement;
const takeBtn = document.getElementById("take-over") as HTMLButtonElement;
const handBtn = document.getElementById("hand-back") as HTMLButtonElement;

let room: Room | null = null;

placeBtn.addEventListener("click", async () => {
  placeBtn.disabled = true;
  statusEl.textContent = "Placing call...";
  const resp = await fetch("http://localhost:8001/place-call", { method: "POST" });
  const { supervisor_token, livekit_url, room: roomName } = await resp.json();

  room = new Room({ adaptiveStream: true });
  attachTranscript(room, transcriptEl);

  room.on(RoomEvent.Disconnected, () => {
    statusEl.textContent = "Disconnected";
    takeBtn.disabled = true;
    handBtn.disabled = true;
    placeBtn.disabled = false;
  });

  await room.connect(livekit_url, supervisor_token);
  // Pre-prepare mic so takeover has zero latency — but keep it muted.
  await room.localParticipant.setMicrophoneEnabled(false);
  statusEl.textContent = `Connected to ${roomName} — supervising`;
  takeBtn.disabled = false;
});

takeBtn.addEventListener("click", async () => {
  if (!room) return;
  await takeOver(room);
  takeBtn.disabled = true;
  takeBtn.classList.add("active");
  handBtn.disabled = false;
  statusEl.textContent = "TAKEOVER: supervisor mic LIVE";
});

handBtn.addEventListener("click", async () => {
  if (!room) return;
  await handBack(room);
  handBtn.disabled = true;
  takeBtn.disabled = false;
  takeBtn.classList.remove("active");
  statusEl.textContent = "Supervising (AI in control)";
});

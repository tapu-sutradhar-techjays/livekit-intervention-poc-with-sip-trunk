import {
  Room,
  RoomEvent,
  Track,
  RemoteTrack,
  RemoteTrackPublication,
  RemoteParticipant,
} from "livekit-client";
import { attachTranscript } from "./transcript";
import { takeOver, handBack } from "./takeover";

const statusEl = document.getElementById("status")!;
const transcriptEl = document.getElementById("transcript")!;
const audioEl = document.getElementById("audio-tracks")!;
const placeBtn = document.getElementById("place-call") as HTMLButtonElement;
const takeBtn = document.getElementById("take-over") as HTMLButtonElement;
const handBtn = document.getElementById("hand-back") as HTMLButtonElement;
const muteBtn = document.getElementById("mute") as HTMLButtonElement;
const endBtn = document.getElementById("end-call") as HTMLButtonElement;

let room: Room | null = null;
let currentRoom: string | null = null;
let micOn = false;

function renderMuteBtn() {
  muteBtn.textContent = micOn ? "Mute Mic" : "Unmute Mic";
  muteBtn.classList.toggle("muted", !micOn);
}

async function setMic(on: boolean) {
  if (!room) return;
  await room.localParticipant.setMicrophoneEnabled(on);
  micOn = on;
  renderMuteBtn();
}

placeBtn.addEventListener("click", async () => {
  placeBtn.disabled = true;
  statusEl.textContent = "Placing call...";
  const resp = await fetch("http://localhost:8001/place-call", { method: "POST" });
  const { supervisor_token, livekit_url, room: roomName } = await resp.json();

  room = new Room({ adaptiveStream: true });
  attachTranscript(room, transcriptEl);

  room.on(
    RoomEvent.TrackSubscribed,
    (track: RemoteTrack, _pub: RemoteTrackPublication, participant: RemoteParticipant) => {
      if (track.kind !== Track.Kind.Audio) return;
      const el = track.attach() as HTMLAudioElement;
      el.dataset.identity = participant.identity;
      audioEl.appendChild(el);
    },
  );

  room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
    track.detach().forEach((el) => el.remove());
  });

  room.on(RoomEvent.Disconnected, () => {
    statusEl.textContent = "Disconnected";
    takeBtn.disabled = true;
    handBtn.disabled = true;
    muteBtn.disabled = true;
    endBtn.disabled = true;
    placeBtn.disabled = false;
    audioEl.replaceChildren();
    currentRoom = null;
  });

  await room.connect(livekit_url, supervisor_token);
  currentRoom = roomName;
  // Chrome blocks autoplay until a user gesture — startAudio unlocks it (we're inside a click handler).
  await room.startAudio();
  // Pre-publish mic muted so takeover toggle has zero connection-setup latency.
  await setMic(false);
  statusEl.textContent = `Connected to ${roomName} — supervising (listening)`;
  takeBtn.disabled = false;
  muteBtn.disabled = false;
  endBtn.disabled = false;
});

takeBtn.addEventListener("click", async () => {
  if (!room) return;
  await takeOver(room);
  micOn = true;
  renderMuteBtn();
  takeBtn.disabled = true;
  takeBtn.classList.add("active");
  handBtn.disabled = false;
  statusEl.textContent = "TAKEOVER: supervisor mic LIVE";
});

handBtn.addEventListener("click", async () => {
  if (!room) return;
  await handBack(room);
  micOn = false;
  renderMuteBtn();
  handBtn.disabled = true;
  takeBtn.disabled = false;
  takeBtn.classList.remove("active");
  statusEl.textContent = "Supervising (AI in control)";
});

muteBtn.addEventListener("click", async () => {
  if (!room) return;
  await setMic(!micOn);
});

endBtn.addEventListener("click", async () => {
  if (!currentRoom) return;
  endBtn.disabled = true;
  statusEl.textContent = "Ending call...";
  try {
    const resp = await fetch("http://localhost:8001/end-call", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ room: currentRoom }),
    });
    if (!resp.ok) throw new Error(`end-call HTTP ${resp.status}`);
    // The room.on(Disconnected) handler resets everything else.
  } catch (err) {
    statusEl.textContent = `End call failed: ${err instanceof Error ? err.message : String(err)}`;
    endBtn.disabled = false;
  }
});

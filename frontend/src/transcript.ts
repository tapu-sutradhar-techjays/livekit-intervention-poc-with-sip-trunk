import { Room, RoomEvent, TranscriptionSegment, Participant } from "livekit-client";

export function attachTranscript(room: Room, target: HTMLElement): void {
  room.on(
    RoomEvent.TranscriptionReceived,
    (segments: TranscriptionSegment[], participant?: Participant) => {
      for (const seg of segments) {
        if (!seg.final) continue;
        const line = document.createElement("div");
        line.classList.add("line");
        const role = inferRole(participant?.identity);
        line.classList.add(role);
        line.textContent = `[${role}] ${seg.text}`;
        target.appendChild(line);
        target.scrollTop = target.scrollHeight;
      }
    },
  );
}

function inferRole(identity: string | undefined): "rep" | "agent" | "supervisor" {
  if (!identity) return "agent";
  if (identity === "rep") return "rep";
  if (identity.startsWith("sup-")) return "supervisor";
  return "agent";
}

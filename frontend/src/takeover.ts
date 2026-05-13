import { Room, RemoteParticipant } from "livekit-client";

function findAgentParticipant(room: Room): RemoteParticipant | undefined {
  for (const p of room.remoteParticipants.values()) {
    if (p.identity !== "rep" && !p.identity.startsWith("sup-")) return p;
  }
  return undefined;
}

export async function takeOver(room: Room): Promise<void> {
  const agent = findAgentParticipant(room);
  if (!agent) throw new Error("agent participant not found");
  await room.localParticipant.performRpc({
    destinationIdentity: agent.identity,
    method: "supervisor/take-over",
    payload: "",
  });
  await room.localParticipant.setMicrophoneEnabled(true);
}

export async function handBack(room: Room): Promise<void> {
  const agent = findAgentParticipant(room);
  if (!agent) throw new Error("agent participant not found");
  await room.localParticipant.setMicrophoneEnabled(false);
  await room.localParticipant.performRpc({
    destinationIdentity: agent.identity,
    method: "supervisor/hand-back",
    payload: "",
  });
}

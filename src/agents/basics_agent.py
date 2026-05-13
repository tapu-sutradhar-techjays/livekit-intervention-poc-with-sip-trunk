"""Day 1: trivial agent that says hello and asks one question. Expanded in Day 2."""
from __future__ import annotations
from livekit.agents.voice import Agent


class BasicsAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are VERA, an AI assistant making a TEST call for the SmartCaller spike. "
                "The person you are calling is the developer testing the system, not a real insurance rep. "
                "On call start, say exactly: 'Hello, this is VERA from SmartCaller spike. Can you hear me clearly?' "
                "Wait for their response. If they say yes or confirm, say: 'Great, thank you. Goodbye.' and stop speaking. "
                "Keep all responses to ONE short sentence. Do not invent questions beyond this script."
            ),
        )

"""Simulate a Twilio ConversationRelay call against the local voice agent,
without needing ngrok or a real phone call.

Usage (from local/, with the venv active and uvicorn running):
    python scripts/test_call.py
"""

import asyncio
import json

import websockets

WS_URL = "ws://localhost:8000/voice/stream"


async def main() -> None:
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"type": "setup", "callSid": "CA_manual_test"}))

        await ws.send(json.dumps({"type": "prompt", "voicePrompt": "yes that's fine"}))
        print("consent:", json.loads(await ws.recv())["token"])

        await ws.send(json.dumps({
            "type": "prompt",
            "voicePrompt": (
                "I have a discharge referral for a hip replacement patient, "
                "Medicare Part A, zip 11201"
            ),
        }))
        print("agent:", json.loads(await ws.recv())["token"])


if __name__ == "__main__":
    asyncio.run(main())

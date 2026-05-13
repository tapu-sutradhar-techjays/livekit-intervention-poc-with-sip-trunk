"""One-time script: register Twilio Elastic SIP Trunk as a LiveKit outbound trunk."""
import asyncio
import os
from dotenv import load_dotenv
from livekit import api

load_dotenv()


async def main() -> None:
    lkapi = api.LiveKitAPI()
    try:
        trunk = api.SIPOutboundTrunkInfo(
            name="spike-twilio-outbound",
            address=os.environ["TWILIO_SIP_TRUNK_URI"],
            transport=api.SIPTransport.SIP_TRANSPORT_AUTO,
            numbers=[os.environ["TWILIO_PHONE_NUMBER"]],
            auth_username=os.environ["TWILIO_SIP_TRUNK_USERNAME"],
            auth_password=os.environ["TWILIO_SIP_TRUNK_PASSWORD"],
        )
        created = await lkapi.sip.create_sip_outbound_trunk(
            api.CreateSIPOutboundTrunkRequest(trunk=trunk)
        )
        print(f"Created LiveKit outbound trunk: {created.sip_trunk_id}")
        print(f"Add to .env: LIVEKIT_SIP_TRUNK_ID={created.sip_trunk_id}")
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    asyncio.run(main())

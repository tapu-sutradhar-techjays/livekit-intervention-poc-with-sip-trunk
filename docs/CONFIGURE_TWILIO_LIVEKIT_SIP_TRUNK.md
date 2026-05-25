#### Twilio Side

1. Buy a new Twilio phone number (Voice-enabled).
2. Create a new Elastic SIP Trunk.
3. Set the **Termination SIP URI** (e.g. `yourname.pstn.twilio.com`) — copy this for LiveKit.
4. Create a **Credential List** (username + strong password) and attach it to the trunk's Termination authentication.
5. Attach the phone number to the trunk (Numbers tab).
6. (If calling internationally) Enable destination countries under Voice → Geographic Permissions.

#### LiveKit Side

1. Console → Telephony → SIP Trunks → Create new trunk.
2. Choose **Outbound**.
3. Set **address** = Twilio Termination URI from step 3.
4. Set **numbers** = your Twilio number(s), or `["*"]`.
5. Choose **Transport**.
6. Advanced settings → enter the Twilio auth username/password.

#### Verify

7. Place one test call (`lk sip participant create`) and confirm in Twilio Monitor → Logs → Calls that the INVITE arrived and authenticated.

#### HIPAA Compliance

Enable all three — any one alone leaves a plaintext gap:

- Twilio: enable **Secure Trunking** on the trunk.
- LiveKit: **Transport = TLS**.
- LiveKit: **Media Encryption = Required** (not "Allow" — Allow permits silent fallback to plain RTP).

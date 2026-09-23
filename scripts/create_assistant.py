#!/usr/bin/env python3
"""
Create (or update) the Vapi voice assistant from app/agent_config.py.

    python scripts/create_assistant.py --dry-run     # print the JSON, call nothing
    python scripts/create_assistant.py               # create a new assistant
    VAPI_ASSISTANT_ID=xxx python scripts/create_assistant.py   # update existing (PATCH)

Then, in the Vapi dashboard: Phone Numbers -> Buy/Import number -> set the
assistant to the one printed here. Re-run this script any time you edit the prompt.

Env: VAPI_API_KEY, PUBLIC_BASE_URL (e.g. https://your-app.onrender.com)
Optional: VAPI_WEBHOOK_SECRET, VAPI_ASSISTANT_ID, LLM_PROVIDER, LLM_MODEL, VOICE_PROVIDER, VOICE_ID
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.agent_config import FIRST_MESSAGE, SYSTEM_PROMPT, build_tools  # noqa: E402

load_dotenv()
API = "https://api.vapi.ai"


def build_assistant(base_url: str, secret: str) -> dict:
    webhook = f"{base_url.rstrip('/')}/vapi/webhook"
    return {
        "name": "Patient Registration - Sam",
        "firstMessage": FIRST_MESSAGE,
        "model": {
            "provider": os.getenv("LLM_PROVIDER", "openai"),
            "model": os.getenv("LLM_MODEL", "gpt-4o"),
            "temperature": 0.4,  # low: we want consistent data collection, but not robotic phrasing
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
            "tools": build_tools(webhook, secret) + [{"type": "endCall"}],
        },
        "voice": {
            "provider": os.getenv("VOICE_PROVIDER", "vapi"),
            "voiceId": os.getenv("VOICE_ID", "Elliot"),
        },
        "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "en"},
        "server": {"url": webhook, **({"secret": secret} if secret else {})},
        "serverMessages": ["tool-calls", "end-of-call-report"],
        "backgroundDenoisingEnabled": True,
        "silenceTimeoutSeconds": 30,   # hang up on dead lines instead of billing forever
        "maxDurationSeconds": 900,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    base = os.getenv("PUBLIC_BASE_URL", "https://YOUR-APP.example.com")
    payload = build_assistant(base, os.getenv("VAPI_WEBHOOK_SECRET", ""))
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return

    key = os.getenv("VAPI_API_KEY")
    if not key or "YOUR-APP" in base:
        sys.exit("Set VAPI_API_KEY and PUBLIC_BASE_URL (your deployed https URL) first.")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    assistant_id = os.getenv("VAPI_ASSISTANT_ID")
    if assistant_id:
        r = httpx.patch(f"{API}/assistant/{assistant_id}", headers=headers, json=payload, timeout=30)
    else:
        r = httpx.post(f"{API}/assistant", headers=headers, json=payload, timeout=30)
    if r.status_code >= 300:
        sys.exit(f"Vapi rejected the config ({r.status_code}):\n{r.text}")
    print(f"OK. Assistant id: {r.json()['id']}\nNow attach it to your phone number in the Vapi dashboard.")


if __name__ == "__main__":
    main()

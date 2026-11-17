"""Pipeline probe: connect to the backend, inject a fake 'THEM' utterance and
print every event until the answer finishes. Lets you verify STT->LLM->HUD
wiring without any audio hardware.

  python backend/tools/ws_probe.py "Can you walk us through how you approached the AD consolidation?"
  python backend/tools/ws_probe.py --summarize
  python backend/tools/ws_probe.py --status
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import load_config  # noqa: E402


async def run(args) -> int:
    import websockets

    cfg = load_config(args.config)
    url = f"ws://{cfg['backend']['host']}:{cfg['backend']['port']}"
    print(f"connecting to {url} …")
    async with websockets.connect(url) as ws:
        if args.status:
            await ws.send(json.dumps({"type": "status"}))
        elif args.summarize:
            await ws.send(json.dumps({"type": "summarize"}))
        else:
            await ws.send(json.dumps({"type": "inject", "channel": args.channel, "text": args.text}))
            if not args.no_generate and args.channel != "them":
                await ws.send(json.dumps({"type": "generate"}))

        answer: list[str] = []
        saw_status = False
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=args.timeout)
                ev = json.loads(raw)
                t = ev.get("type")
                if t == "status":
                    saw_status = True
                    print("STATUS:", json.dumps({k: v for k, v in ev.items() if k != "type"}, ensure_ascii=False))
                    if args.status:
                        return 0
                elif t == "transcript":
                    print(f"TRANSCRIPT [{ev['channel']}]: {ev['text']}")
                elif t == "llm_start":
                    print(f"LLM_START gen={ev['gen_id']} mode={ev['mode']}")
                elif t == "llm_reset":
                    print("LLM_RESET (fallback provider)")
                    answer.clear()
                elif t == "llm_token":
                    answer.append(ev["text"])
                    sys.stdout.write(ev["text"])
                    sys.stdout.flush()
                elif t == "llm_end":
                    print(f"\nLLM_END provider={ev['provider']} elapsed={ev.get('elapsed_s')}s errors={ev['errors']}")
                    return 0 if ev["provider"] else 2
                elif t == "error":
                    print("ERROR:", ev["message"])
                    if not args.summarize and args.no_generate:
                        return 1
        except asyncio.TimeoutError:
            print(f"\ntimeout after {args.timeout}s (status seen: {saw_status})")
            return 3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default="Can you walk us through your experience with that migration?")
    ap.add_argument("--channel", default="them", choices=["them", "me"])
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--no-generate", action="store_true")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Talk to @musk from the terminal, as if typing in a Teams meeting chat.

  python cli.py "@musk what's the takeaway from this meeting"
  python cli.py --activity samples/activity_mention.json
  python cli.py            # interactive
"""
import argparse
import json
import sys

from musk import handle_activity, make_activity, make_brain


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("message", nargs="?", help='e.g. "@musk create ADO items for these topics"')
    p.add_argument("--activity", help="path to a Teams activity JSON file to replay")
    p.add_argument("--brain", choices=["claude", "offline"], help="default: claude if ANTHROPIC_API_KEY is set")
    p.add_argument("--json", action="store_true", help="print the full reply activity")
    args = p.parse_args()
    brain = make_brain(args.brain)
    print(f"[brain: {type(brain).__name__}]", file=sys.stderr)

    def one(activity):
        reply = handle_activity(activity, brain=brain)
        if reply is None:
            print("(musk stays quiet: it was not @mentioned)")
        else:
            print(json.dumps(reply, indent=2) if args.json else reply["text"])

    if args.activity:
        with open(args.activity, encoding="utf-8") as f:
            one(json.load(f))
    elif args.message:
        one(make_activity(args.message))
    else:
        print("Type a message as if in Teams (Ctrl-D to quit). Remember to @musk.")
        for line in sys.stdin:
            if line.strip():
                one(make_activity(line.strip()))
                print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Command-line interface for memory capture, retrieval, and injection."""
from __future__ import annotations
import argparse
import json
import sys

from .service import capture, retrieve, build_injection, make_observation


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="agent-memory",
        description="Persist and retrieve durable memories for AI agents.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("capture", help="store one durable observation")
    c.add_argument("--summary", required=True)
    c.add_argument("--session", default="cli")
    c.add_argument("--tags", default="")

    r = sub.add_parser("retrieve", help="retrieve the most relevant observations")
    r.add_argument("--query", required=True)
    r.add_argument("--k", type=int, default=8)

    i = sub.add_parser("inject", help="format relevant observations for an agent prompt")
    i.add_argument("--query", required=True)
    i.add_argument("--budget", type=int, default=2000)

    args = p.parse_args(argv)
    if args.cmd == "capture":
        tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
        added = capture(make_observation(args.summary, session_id=args.session, tags=tags))
        verb = "Remembered" if added else "Already remembered"
        print(f"{verb}: {args.summary}")
    elif args.cmd == "retrieve":
        print(json.dumps(retrieve(args.query, args.k), ensure_ascii=False))
    elif args.cmd == "inject":
        sys.stdout.write(build_injection(args.query, args.budget))


if __name__ == "__main__":
    main()

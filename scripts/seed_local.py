import argparse
from collections import Counter
from pathlib import Path

import httpx
from dataset import iter_contexts


def main() -> None:
    parser = argparse.ArgumentParser(description="Push a dataset into a running Vera bot.")
    parser.add_argument("dataset", type=Path, help="expanded dataset dir or the seed dataset dir")
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--version", type=int, default=1)
    parser.add_argument("--skip-triggers", action="store_true")
    args = parser.parse_args()

    outcomes: Counter[str] = Counter()
    with httpx.Client(base_url=args.url, timeout=10) as client:
        for scope, context_id, payload in iter_contexts(args.dataset):
            if scope == "trigger" and args.skip_triggers:
                continue
            response = client.post(
                "/v1/context",
                json={
                    "scope": scope,
                    "context_id": context_id,
                    "version": args.version,
                    "payload": payload,
                },
            )
            outcomes[f"{scope}:{response.status_code}"] += 1
        health = client.get("/v1/healthz").json()

    for outcome, count in sorted(outcomes.items()):
        print(f"{outcome:<16} {count}")
    print("healthz:", health["contexts_loaded"])


if __name__ == "__main__":
    main()

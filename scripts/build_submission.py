import argparse
import asyncio
import json
from collections import Counter
from datetime import date
from pathlib import Path

from dataset import iter_contexts

from vera.compose.composer import Composer
from vera.config import get_settings
from vera.main import build_llm
from vera.store.contexts import ContextScope, ContextStore

RATE_LIMIT_RETRIES = 6
RATE_LIMIT_PAUSE_SECONDS = 20


async def build(dataset: Path, today: date, output: Path) -> None:
    store = ContextStore()
    for scope, context_id, payload in iter_contexts(dataset):
        store.put(ContextScope(scope), context_id, 1, payload)

    settings = get_settings()
    llm = build_llm(settings)
    composer = Composer(llm, timeout_seconds=settings.llm_timeout_seconds * 3)
    pairs = json.loads((dataset / "test_pairs.json").read_text())["pairs"]
    slots = asyncio.Semaphore(settings.compose_concurrency)
    sources: Counter[str] = Counter()

    async def compose(pair: dict[str, str]) -> dict[str, str]:
        bundle = store.bundle_for_trigger(pair["trigger_id"])
        if bundle is None:
            raise SystemExit(f"{pair['test_id']}: missing context for {pair['trigger_id']}")
        async with slots:
            message = await composer.compose(bundle, today)
            for _ in range(RATE_LIMIT_RETRIES if llm else 0):
                if message.generated_by == "llm":
                    break
                await asyncio.sleep(RATE_LIMIT_PAUSE_SECONDS)
                message = await composer.compose(bundle, today)
        sources[message.generated_by] += 1
        return {
            "test_id": pair["test_id"],
            "body": message.body,
            "cta": message.cta.value,
            "send_as": message.send_as.value,
            "suppression_key": message.suppression_key,
            "rationale": message.rationale,
        }

    rows = await asyncio.gather(*(compose(pair) for pair in pairs))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    print(f"wrote {len(rows)} messages to {output} ({dict(sources)})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose the 30 canonical test pairs.")
    parser.add_argument("dataset", type=Path, help="expanded dataset dir (with test_pairs.json)")
    parser.add_argument("--today", type=date.fromisoformat, default=date(2026, 4, 26))
    parser.add_argument("--out", type=Path, default=Path("out/submission.jsonl"))
    args = parser.parse_args()
    asyncio.run(build(args.dataset, args.today, args.out))


if __name__ == "__main__":
    main()

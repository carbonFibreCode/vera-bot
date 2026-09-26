# Vera merchant bot

A stateful HTTP bot for the magicpin Vera challenge. It takes category, merchant, trigger and customer context pushed by the judge and writes the next WhatsApp message, either as Vera to the merchant or as the merchant to one of their customers. It then handles the reply turns that follow.

## Approach

Every message is built in three steps:

1. **Fact sheet (deterministic).** For each (category, merchant, trigger, customer?) tuple, plain Python resolves the facts worth saying: the digest item a trigger points at, the CTR gap against peers, days to a deadline, the customer's real slots and prices, how to address the reader, and which language to use. This is where specificity and merchant fit come from.
2. **Trigger strategy.** About 25 trigger kinds map to 8 families (knowledge, compliance, performance, reputation, commercial, moment, conversational, customer). Each family sets the angle, the persuasion levers and the CTA shape. Each kind supplies a "why now" hook and a concrete deliverable.
3. **Write, check, fall back.** The LLM writes only from the fact sheet. Guardrails reject any draft that:
   - uses a number not in the facts
   - contains a banned word, a URL or an internal field name
   - repeats an earlier message
   - uses the wrong language
   - asks a qualifying question after the merchant has said yes

   A rejected draft is retried once with the problems listed. After that the bot sends a grounded template built from the same facts. The bot therefore never times out and never invents data.

Replies go through a rule-first classifier (auto-reply, opt-out, hostile, commit, defer, off-topic, question), with the LLM used only for ambiguous messages. A small state machine then decides:

| Situation | What the bot does |
|---|---|
| Auto-reply | Sends one note for the owner, then waits 24 h, then ends |
| Merchant says yes | Switches straight to action mode |
| Opt-out or hostility | Exits politely and mutes the merchant for 30 days |
| Off-topic question | Declines in one line and steers back to the thread |

Ticks pick one trigger per merchant by urgency and skip suppressed or muted ones. Drafts are composed as soon as a trigger is pushed, and each draft is cached against the versions of all four contexts, so a newer context version always gets a fresh message.

## Model

The default is `openai/gpt-oss-120b` on Groq, called with low reasoning effort and a strict JSON schema. On a 429, the client respects `retry-after` and serves templates until the cooldown ends. Anthropic and any OpenAI-compatible API can be selected with `VERA_LLM_PROVIDER`.

## Tradeoffs

- **Precision over flourish.** The number check sometimes rejects a good phrasing, but a rejected draft still produces a correct message.
- **Consent.** Consent is checked as "has any opt-in". The dataset mostly records one broad scope, so a stricter mapping would silence valid service reminders.
- **Trigger expiry.** `expires_at` is not enforced by default. The judge only lists triggers it considers active, and the local simulator uses wall-clock time. Set `VERA_RESPECT_TRIGGER_EXPIRY=true` to enforce it.

## What would have helped most

- Real appointment and slot data for generated triggers (many are placeholders).
- Per-merchant open slots.
- Customer consent scopes that line up with trigger kinds.

## Running

```bash
uv sync
cp .env.example .env          # add VERA_LLM_API_KEY (Groq); without it the bot runs on templates only
uv run uvicorn vera.main:create_app --factory --port 8080

uv run python scripts/seed_local.py path/to/expanded --skip-triggers   # warm-up push
uv run python scripts/build_submission.py path/to/expanded             # writes out/submission.jsonl
uv run pytest && uv run ruff check . && uv run mypy
```

Deploy with the `Dockerfile` to any always-on host (Railway, or Fly.io with `min_machines_running = 1`). Run exactly one replica, because all state is held in memory.

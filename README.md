# Rahat AI — WizeFF TopUp business assistant

A Groq conversation assistant behind Rahat's connected Telegram Business account.
Customers message Rahat normally; opening the bot is optional. Supabase remains the
source of truth for business rules, service status, language preferences, recent
conversation and support cases.

## Run on Render

Build command: `pip install -r requirements.txt`

Start command: `gunicorn app:app`

Keep the existing environment variables in Render:

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Connected Business bot token |
| `GROQ_API_KEY` | Groq API access |
| `GROQ_MODEL` | A Groq model supporting Chat Completions and JSON object output; existing default retained |
| `OWNER_TELEGRAM_ID` | Owner's numeric Telegram user ID |
| `SUPABASE_URL` | Existing Supabase project URL |
| `SUPABASE_SECRET_KEY` | Server-side Supabase key |

Do not put credentials in GitHub, messages, screenshots or logs.

Render supplies `RENDER_EXTERNAL_URL`. `gunicorn.conf.py` registers `/webhook` when
the worker starts, with `message`, `business_connection`, and `business_message`
updates. Edits are ignored even if an old queued edited update arrives. The start
command is unchanged. Custom commands/scopes in BotFather are not changed.

Webhook requests require Telegram's secret header. By default its value is derived
from the bot token using HMAC; no extra required secret/environment variable is
introduced. An optional `TELEGRAM_WEBHOOK_SECRET` overrides it. Registration must
succeed when upgrading the previous unauthenticated webhook. Check the Render log
for registration failure and send a real test message after deployment.

`/setup` remains available, but browser GET requests without authentication are
rejected. Owner `/setup` in the private bot chat re-registers the trusted Render URL.
If registration failed before Telegram could deliver owner commands, call the HTTP
setup endpoint with `Authorization: Bearer <SETUP_SECRET>` from a trusted client;
when optional `SETUP_SECRET` is unset, the existing bot token is accepted as the
bearer value. Use environment variables locally; never place that value in a URL.
For non-Render hosting, supply `RENDER_EXTERNAL_URL` or use the authenticated setup
endpoint. Health check: `GET /`.

The owner must first open the bot's private chat so Telegram permits direct support
notifications. Connect the bot to the intended Business account and grant reply
rights. The connected account ID must equal `OWNER_TELEGRAM_ID`. Disabled connections,
missing reply rights, bot-generated messages and other accounts are ignored.

## Routing and commands

| Context | Behavior |
| --- | --- |
| Customer normal message, auto reply on | Context-aware AI reply |
| Customer normal message, auto reply off | Silent |
| Customer `/ai <question>` | Explicit reply, including when automatic replies are off |
| Customer `/help` | Customer commands only; no conversational-memory entry |
| Owner manually replies in a customer chat | Silent; keeps the human reply as recent context |
| Owner replies to a customer with `/ai ans` | Answers that target directly, even with auto reply off |
| Owner standalone `/ai <instruction>` | Current task; no permanent teaching |
| Owner ordinary private bot conversation | Natural personal/business assistant; temporary memory |
| Group message | Ignored unless it contains the exact `@rahatwize` mention |

Owner commands: `/on`, `/off`, `/ai`, `/gk`, `/customer`, `/help`.
Existing `/online`, `/offline`, `/knowledge`, and `/forgetlast` are retained.
`/forgetlast` restores affected status from earlier knowledge. `/setup` is also
owner-only. Administrative output from customer Business chats is sent to the
owner privately, avoiding public exposure of customer lists and saved instructions.

## Knowledge and availability

Only `/gk` writes permanent business instructions. Knowledge and state are read
from Supabase for every response, including across worker restarts. Explicit
status clauses are replayed chronologically and enforced before Groq. The default
is **unknown** until the owner supplies it; website presence alone is not stock.

Examples:

```text
/gk All services available
/gk CapCut Pro ekhon available nai
/gk CapCut Pro available ache
/gk All services available. CapCut not available.
/gk Customer payment complete bolle age order ID chaiba
/gk answer besi long korba na short rakhar try korba
```

A specific service exception overrides the global default. Changing the default
does not erase named exceptions. The parser supports explicit available/unavailable
statements in English and common Banglish/Bangla forms for arbitrary service names.
Other owner instructions are supplied to Groq as rules, not inferred status writes.
For deterministic status changes, use the explicit forms above. Existing plain
knowledge rows are kept and replayed; no startup-only knowledge cache is used.

## Conversation, reference IDs and support

- Language locks persist per customer/chat/connection. Numbers, greetings and short
  acknowledgements retain the previous style. Legacy customer-ID language locks
  are inherited without importing another connection's conversation.
- Recent messages are loaded as actual user/assistant turns. A greeting does not
  clear active context. New topics remain distinguishable to Groq.
- A pending reference request is stored separately. `829292828 eta` after an ID
  request is accepted directly, without asking whether it is an ID.
- Payment-problem handling records an open support case and asks for the missing
  reference. When supplied, the case uses the latest relevant reference and sends
  one concise owner alert. General requests for human support can also alert.
- The alert includes name, username, customer ID, problem and reference; the full
  sanitized context stays in Supabase.
- Alert timestamps are written only after Telegram confirms success and survive
  case updates. Cooldown is 30 minutes; updates during it retain `alerted_at`.
- There is no order/payment API. Replies say manual verification is needed and
  never rely on a model's claim that an order was checked or support was notified.

Known fake-action wording is filtered after generation; core prompts also prohibit
unsupported actions, invented plans, prices, guarantees and statuses. Natural-language
safety filters are defense in depth, not a mathematical guarantee for every possible
LLM paraphrase. Live model response quality should be checked with the examples below.

## Catalog and Telegram output

`assistant_rules.py` extracts a small catalog from same-domain `/product/` anchors,
including canonical names, aliases and verified URLs. It never stores raw homepage
customer feeds or sends them to Groq. Catalog refresh is six hours; failed refreshes
retry after ten minutes and retain verified names/links without asserting current
stock or prices. A small dated seed supports Guild/Glory/CapCut if the site is down.

Verified seed sources (2026-09-30):

- [Official homepage](https://wizefftopup.com/)
- [GUILD GLORY BOT](https://wizefftopup.com/product/guild-glory-bot)
- [GUILD TCP BOT](https://wizefftopup.com/product/guild-tcp-bot)
- [CAPCUT PRO](https://wizefftopup.com/product/capcut-pro)

Guild aliases resolve to the verified Guild TCP product; Glory aliases resolve to
Guild Glory. No unverified price, plan, duration or feature is seeded. Gambling,
adult, privacy-invasive identity/location/call-record services and artificial
engagement categories are excluded from catalog discovery.

Product links are permitted only for relevant link, purchase-location or price
requests, including short follow-ups. URLs must exactly match the verified allowlist.
`Update hoisos` is not a channel request; `update link` / `telegram channel` is.
All existing custom emoji IDs are preserved. All seven decorative payment emojis
remain together on one line and do not establish supported payment methods.

## Existing Supabase schema and deployment limits

No schema migration is required. The app uses existing `public.bot_memory` fields:
`id`, `memory_type`, `memory_key`, `content`, `created_at`. Structured content is JSON
stored in `content`. No SQL expression such as `"updated_at": "now()"` is sent.

| Memory type | Retention / purpose |
| --- | --- |
| `state`, `service_status`, `knowledge` | Permanent owner configuration |
| `customer` | Permanent unique customer registry; refreshed names/usernames |
| `customer_language` | Persistent language preferences |
| `conversation`, `conversation_summary` | Four days; scoped by connection/chat/customer |
| `support_case`, existing `customer_note` | Retained; excluded from cleanup |
| `website_catalog` | Structured official catalog/cache metadata |
| `update_receipt` | Completed Telegram updates; four days |

Registry listing deduplicates existing duplicate customer rows and paginates beyond
1,000 rows. Legacy unscoped conversations/cases are not deleted or blindly attached
to a connection; their origin cannot be safely reconstructed. New scoped support
cases therefore start their own cooldown. Old conversation rows expire normally.

Database failures fail closed with HTTP 503, rather than using stale auto-reply or
service state. Completed update receipts suppress ordinary Telegram retries. OS
file locking serializes webhook work across threads/workers on **one Render
instance**, which avoids requiring a new unique constraint on the existing table.
Do not horizontally scale this implementation across independent instances without
adding a shared transactional lock/unique key and durable job/outbox design.

Telegram send and database persistence cannot be committed in one transaction.
A process crash after an accepted Telegram send but before recording its receipt
can still produce a duplicate on retry. This is not an exactly-once delivery claim.
The single-instance serialization also limits throughput and can delay replies
under bursts; a queue is the next step for a busier deployment.

Input is screened before memory or Groq for labelled credentials, token patterns
and card-shaped numbers. Unlabelled secrets cannot always be distinguished from
ordinary text; customers are never asked for them. Long card-shaped values are
rejected conservatively even if described as references. API response bodies,
credentials and exception URLs are not logged. Temporary cleanup never removes the
customer registry or long-lived support records.

## Validation

```sh
python -m unittest discover -s tests -v
python -m py_compile app.py assistant_rules.py gunicorn.conf.py
```

Regression coverage includes routing/permissions, per-turn rules/state refresh,
reference follow-ups without trusting the model's flag, cooldown preservation,
notification failures, language locks, context isolation, catalog filtering,
verified URLs, edited/duplicate updates, command-memory exclusion, secret redaction,
Groq request shape and authenticated webhook setup.

Tests mock external APIs; they do not verify live credentials, Render deployment,
Telegram reply rights or real Groq wording. After deployment, test:

1. Customer: `taka add hoitase na`, then `829292828 eta`.
2. Owner `/off`; customer normal message is silent; `/ai` still works.
3. Owner manual reply is silent; reply-to-customer `/ai ans` answers its target.
4. Owner `/gk CapCut Pro available nai`; customer `capcut need` gets unavailable.
5. Set CapCut available again; confirm the latest rule is used.
6. `guild bot lagbe`, `glory bot ase?`, then `link dao`.
7. Banglish followed by numbers/`hi`/`ok`; no unexpected language switch.
8. Two follow-ups in one unresolved case; no repeated owner alert during cooldown.

Render Free may sleep. An initial wake-up delay alone is not a routing failure.

API references: [Telegram Bot API](https://core.telegram.org/bots/api),
[Groq Chat Completions](https://console.groq.com/docs/api-reference).

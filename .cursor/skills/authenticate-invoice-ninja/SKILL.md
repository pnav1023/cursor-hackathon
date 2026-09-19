---
name: authenticate-invoice-ninja
description: Saves an Invoice Ninja API token from the chat into local env and verifies it with GET /api/v1/ping. Use when the user wants to connect Invoice Ninja, paste an API key/token, or authenticate with Invoice Ninja.
---

# Authenticate Invoice Ninja

Store the user's Invoice Ninja **API token** in the repo `.env` and confirm it works. Do not print the full token after it is saved.

## Collect from chat

Ask for anything missing:

| Value | Env var | Default |
| --- | --- | --- |
| API token | `INVOICE_NINJA_API_TOKEN` | required |
| Site URL | `INVOICE_NINJA_BASE_URL` | `https://invoicing.co` |
| API secret | `INVOICE_NINJA_API_SECRET` | self-hosted only; omit on Invoice Ninja cloud |

If they do not know where the token is:

Settings → Account Management → Integrations → API tokens → New Token

Hosted cloud base URL is `https://invoicing.co` (no trailing slash). Self-hosted is their origin, e.g. `https://ninja.example.com`.

## Save

Upsert those keys in `.env` at the repo root. `.env` is gitignored — never commit it, never copy the token into `SKILL.md` or another tracked file.

Keep existing unrelated `.env` keys (Gemini, OpenAI, etc.).

## Verify

From the repo root:

```bash
python .cursor/skills/authenticate-invoice-ninja/scripts/verify_invoice_ninja.py
```

Success is HTTP 200 from `GET /api/v1/ping`. Tell the user the **company/user name** from the response, not the token.

All later Invoice Ninja calls in this project must send:

- `X-API-TOKEN: $INVOICE_NINJA_API_TOKEN`
- `X-Requested-With: XMLHttpRequest`
- `Accept: application/json`
- `X-API-SECRET` only if `INVOICE_NINJA_API_SECRET` is set

Base path is `$INVOICE_NINJA_BASE_URL/api/v1/...`.

## Failures

- 401/403 → token is wrong, disabled, or the user is not allowed. Ask them to create a new token as admin/owner.
- Connection error → wrong `INVOICE_NINJA_BASE_URL`.
- Hosted accounts: API tokens require a paid Invoice Ninja plan.

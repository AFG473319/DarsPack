# Enabling online feedback (بازخورد آنلاین)

The in-app «بازخورد» dialog always saves every entry to `feedback.jsonl` inside the library folder — but that file is on the *user's* machine, so if you distribute the app, you need one more step to actually receive the feedback. This page shows how to connect the dialog to a real receiver in about 10 minutes.

## How the dialog works

1. The user fills in: star rating (optional), topic (bug / suggestion / question / praise), a message (capped at 2000 characters, with a live counter — free-hosted forms reject oversized bodies), and an optional contact.
2. On submit, the entry is **saved locally first** (nothing is ever lost if the network fails), then queued in `feedback_pending.json` and POSTed as one JSON object to the configured endpoint:
   ```json
   {"app": "DarsPack", "version": "0.1.0", "rating": 4,
    "category": "fb_cat_bug", "message": "...", "contact": "...",
    "sent_at": "2026-10-26T20:00:00"}
   ```
3. While the entry is in flight the form stays open with «در حال ارسال…»; a double click cannot queue the same entry twice.
4. A network failure (or a 4xx/5xx answer) leaves the entry queued and offers «ارسال دوباره» immediately; otherwise the app asks «اکنون ارسال شود؟» the next time the Feedback window opens and walks the queue.
5. A successful send removes the entry from the queue — `feedback.jsonl` keeps exactly one line per entry ever written locally.
6. If no endpoint is configured, the user sees «بازخورد شما در این دستگاه ذخیره شد» and, if you set a web-form URL, a button to open that form in the browser.
7. Everything the user typed is also auto-saved as a draft (`feedback_draft.json`) while typing; an accidental close or Cancel never loses a half-written report, and the draft is cleared once it was submitted.

## Configuring a receiver (two keys)

Both keys live in `settings.json` next to the catalog (users can edit them in Settings without rebuilding). To bake them into a release build, set the defaults in `src/darspack/feedback_config.py` before running `installer\build.bat`:

| Key | Meaning | Example |
|---|---|---|
| `feedback_endpoint` | HTTPS URL that accepts a JSON POST and answers 2xx | `https://api.formaloo.net/v1/forms/<slug>/responses/` |
| `feedback_form_url` | Web form opened in the browser as a fallback | your Formaloo/GitHub-Issues URL |

## Receiver options

- **Formaloo** (Persian, works from Iranian IPs, respondents need no account): create a free form, add matching fields, get the API endpoint and key from the dashboard (docs.formaloo.net). If the API needs a key header, put the key into the endpoint as your receiver requires — a feedback endpoint is low-risk by design; worst case is spam entries.
- **Cloudflare Worker** (free tier): a ~15-line worker that accepts the JSON POST and appends it to KV/D1 — you own the data end to end.
- **GitHub Issues**: set only `feedback_form_url` to your repo's issues page; the dialog then guides users there. Fine, but it needs a GitHub account — the JSON endpoint is friendlier for classmates.

## Reading the feedback

- Local entries: `feedback.jsonl` in the library folder (one JSON object per line; `feedback_draft.json` and `feedback_pending.json` are the in-progress form state and the unsent queue — safe to ignore, never send them anywhere).
- Online entries: whatever your receiver's dashboard shows (Formaloo shows charts per field; a Worker you query yourself).

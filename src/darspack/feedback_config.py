"""Where sent feedback goes (مقصد بازخورد).

These defaults are baked into a release build: before giving the app to
friends, set FEEDBACK_ENDPOINT to an HTTPS URL that accepts a JSON POST
(Formaloo's API, a Cloudflare Worker, Formspree, …) and optionally
FEEDBACK_FORM_URL to a web form for the «open in browser» fallback.
Users can override both in settings.json without rebuilding. Empty
endpoint = feedback is only saved locally. See docs/feedback-setup.md.
"""

FEEDBACK_ENDPOINT = "https://formspree.io/f/mvkknjga"
FEEDBACK_FORM_URL = ""

When the user mentions project architecture, engineering decisions, workflows, conventions,
preferences, or reusable implementation patterns that are not already documented in `CLAUDE.md`,
update the file automatically. Before adding anything, check whether the information already exists
or needs revision. Keep updates concise, structured, and durable so they remain useful across future
sessions. Prioritize documenting system architecture, repository structure, naming conventions,
preferred libraries/frameworks, deployment and testing approaches, API and data model standards,
infrastructure decisions, coding style preferences, and recurring patterns that affect future
development work. Avoid duplicate entries and place new information in the most relevant section
while preserving existing formatting and organization. Do not store temporary debugging notes,
experimental ideas, conversational filler, or secrets such as credentials, API keys, or tokens.
Treat `CLAUDE.md` as the persistent source of truth for the project’s technical context and user
preferences. After updating it, continue working using the newly captured context automatically
without requiring the user to repeat the information later.

## Mandatory rules

1. Don’t assume. Don’t hide confusion. Surface tradeoffs.
2. Minimum code that solves the problem. Nothing speculative.
3. Touch only what you must. Clean up only your own mess.
4. Define success criteria. Loop until verified.

## Lyrics scraping (AZLyrics)

- AZLyrics blocks on the TLS/HTTP2 fingerprint, not headers or IP. `main/lyrics.py`
  fetches via `curl_cffi` and rotates through `AZLYRICS_IMPERSONATE` (in
  `main/constants.py`) until a profile
  is not served the captcha page. Which profiles pass rotates over time — when the
  browser check returns, re-test the targets and reorder that tuple rather than
  reaching for a headless browser.
- Block pages come in variants off one template: the captcha one ("detected unusual
  activity from your IP address") and a "request for access" / "your IP address will
  be unblocked soon" one with no captcha. All of them carry the `az_unblock` form and
  return HTTP 200, so detection matches on `BROWSER_CHECK_TEXTS`, not status. A block
  page that slips past detection surfaces as a confusing parse error
  (`not enough b_tags: 0`) — add the new marker instead of touching the parser.
- Never auto-solve the captcha. When every profile is blocked, `BrowserCheckError`
  carries the blocked url; the lyrics view links straight to it and pre-fills the
  retry form so the user solves it by hand in their own browser and hits Retry.

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

## Testing

- **pytest only.** Run the suite with `python -m pytest`. Never `manage.py test` - the Django
  runner is not used here. pytest-django is configured in `pyproject.toml`
  (`DJANGO_SETTINGS_MODULE`, plus `python_files` so `main/tests.py` is collected).
- **pytest style, no `TestCase` classes.** Tests are plain module level functions; shared setup is
  a `@pytest.fixture`, not `setUp`. Take `db` (directly or through a fixture that creates rows) for
  database access, and `rf` / `client` for requests. Use bare `assert`, never `self.assertX`.
- `conftest.py` unblocks the database for the collection phase because `main.plays` sizes its
  rotation constants off the library at import time; without it importing `main/tests.py` is a
  collection error.
- Write the **minimum** tests and assertions that take new or changed code to **90% coverage**:
  one test per meaningful branch, one assertion per fact. No permutations of the same path, no
  assertions that restate what another assertion already proved, no tests for code you did not
  touch.
- **After every change, the whole suite must pass**, not just the new tests. Run it before
  reporting the work done and report the actual result.
  Coverage: `coverage run -m pytest && coverage report -m`.
- A test whose target no longer exists is deleted along with the code it covered - never left
  failing or patched to keep a dead name alive. The same goes for a test that only exercises logic
  copied into its own body: it proves nothing, so it goes.

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

## htmx

- Vendored at `main/static/main/htmx-4.0.0/htmx.min.js`, loaded from `base.html`. **htmx 4**,
  not 2 — the semantics differ in ways that bite silently:
  - **Attribute inheritance is explicit.** A parent's `hx-target`/`hx-swap`/`hx-confirm` etc. does
    *not* reach descendants unless written as `hx-target:inherited`. Today every element declares
    its own, so there is no `:inherited` anywhere — keep it that way rather than switching on
    `htmx.config.implicitInheritance`.
  - **Events are colon-separated** (`htmx:after:swap`, not `htmx:afterSwap`), and the detail is
    `{ctx}`. The event fires on `ctx.sourceElement`, so the swapped container is
    `event.detail.ctx.target` — `event.target` is the clicked element and will not match the
    container (see the handler in `main/static/main/js/player.js`).
  - **4xx/5xx responses swap** (only 204/304 don't). An error `HttpResponse` or a Django 404/500
    page renders into whatever container made the request, so keep error bodies presentable.
  - **GET/DELETE do not include an enclosing form.** `hx-get` on a `<form>` still serializes it,
    but `hx-get` on a button *inside* a form sends nothing from it — use `hx-include` if needed.
- The official upgrade checker ships inside the npm package and is worth re-running after template
  work: `npx htmx.org@4.0.0 upgrade-check -- .` (needs python3). Its `[inheritance]` hits are
  heuristic — it flags a parent whenever any descendant has `hx-get`, without checking whether that
  descendant declares its own attribute, so verify before adding `:inherited`.

## Metadata edits

- Track titles are editable inline on the album track listing (pencil appears on row hover,
  `snippet_song_title.html` + `song_title_view`). The audio file is the source of truth —
  `recheck_metadata` re-reads it and overwrites the db — so ui edits write the tag first via
  `musicfiles.write_song_title`, then save the model. Any future field made editable must keep
  that file-then-db order, otherwise a failed write silently desyncs the two.

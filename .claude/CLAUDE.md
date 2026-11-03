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

## Git

- **Commit and push when the work is done**, after the full suite passes - don't wait to be asked.
  Work on `main` and push to `origin/main`.
- If the change revises the last developed change (a fix or follow-up to what the previous commit
  introduced), amend that commit (`git commit --amend`) and push with `--force-with-lease`
  instead of adding a new commit. Anything unrelated gets its own commit.
- Leave nothing uncommitted: changes that aren't yours (the user's own edits, earlier sessions)
  get committed too, as their own commit with a message describing them, not folded into yours.

## Testing

- **pytest only.** Run the suite with `python -m pytest`. Never `manage.py test` - the Django
  runner is not used here. pytest-django is configured in `pyproject.toml`
  (`DJANGO_SETTINGS_MODULE`, plus `python_files` so `main/tests.py` is collected).
- **pytest style, no `TestCase` classes.** Tests are plain module level functions; shared setup is
  a `@pytest.fixture`, not `setUp`. Take `db` (directly or through a fixture that creates rows) for
  database access, and `rf` / `client` for requests. Use bare `assert`, never `self.assertX`.
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

## UI fonts

- Names get the display fonts from `main.css`, as the player header (`partial_song_player.html`)
  sets them: song title `title-font`, artist `artist-font` (wrapped in `<em>`), album `album-font`.
  Tables keep the plain table font.

## Metadata edits

- Track titles are editable inline on the album track listing (pencil appears on row hover,
  `snippet_song_title.html` + `song_title_view`). The audio file is the source of truth —
  `recheck_metadata` re-reads it and overwrites the db — so ui edits write the tag first via
  `musicfiles.write_song_title`, then save the model. Any future field made editable must keep
  that file-then-db order, otherwise a failed write silently desyncs the two.

## Album art

- `album_art_view` caches the embedded art in `ALBUMS_DIR` and serves that copy only while it is
  newer than the requested song's audio file; browsers get `no-cache` + `Last-Modified` (the
  file's mtime) and revalidate. New art comes in by retagging the file, not via `recheckmetadata`.

## Play counting

- `next_song_view` counts the session's previous song as played on every request (song ended,
  skip, demand, filter), however long it was paused. The only exception is the page-load request
  from `home.html`, which sends `?refresh=1`. A new path that loads the player without the user
  moving on must send `refresh` too.

## Missing audio files

- Request paths never call `validate_songs()`: its default `delete=True` drops every song whose
  file is missing, with its stats, and files go missing while the user is moving them. The player
  skips such a song (`get_next_song(exclude_ids=...)`), logs it and shows a warning; pruning is
  left to the explicit scan/cleanup commands.

## Play priority

- Bad albums get their fair chance through the play queue: `get_next_song` adds `weight_bad_album`
  to songs on the `list_lowest_rated_albums` albums (one slot count of them) that are still under
  `BAD_ALBUM_MIN_SONG_PLAYS` / `_RATINGS`, the same test that strikes the album through. The bump is
  per song, never per album, so it stops by itself once the album has had its chance; a bad album
  the user keeps is not played forever. The album ids (not instances) are cached for
  `RATINGS_WINDOW`.

## Ratings and stored stats

- Song rating = wins / ratings. Album and artist ratings are bayesian filled means, computed only
  through `main/ratings.py`: `get_album_rating` (songs filled to `ALBUM_FILL_SONGS` with the
  library's mean song rating) and `get_artist_rating` (albums filled to `ARTIST_FILL_ALBUMS` with
  the mean album rating). Never inline `Avg('rating')` for albums/artists again: every stats path
  (`set_match_result`, `upkeep_*`, `recheck_metadata`, `cleanstats`) goes through these helpers.
- The artist rating reads the *stored* album ratings, so save the albums before rating the
  artist. Compute the mean (`get_mean_rating`) once per batch, not per row.
- Anything that leaves stored stats wrong marks the rows `is_dirty` for `cleanstats`, it does not
  recalculate them inline: `signals.py` marks the song on a rating/history delete, the album on a
  song delete, the artist on an album delete; `recheck_metadata` marks the album and artist a
  song moved away from. `cleanstats` cascades songs → albums → artists; `--all` redoes every row.

## Similars (last.fm)

- `main/lastfm_service.py` only calls last.fm endpoints and returns plain data (titles,
  playcounts, urls); business logic built on them lives in other modules (`main/discography.py`,
  `main/similars.py`).
- "More from artist" (`discography.py`) reuses `Artist.disco_at` as the reviewed marker. It
  skips top albums whose name matches an owned one by `track_slug` (so "(Deluxe Edition)" still
  counts as owned) and keeps the unowned tracks above the album's mean last.fm playcount
  (`get_stand_out_tracks`). Use the mean, not mean + stdev: playcounts are skewed so hard that
  the stdev leaves only the hit. The Wikipedia scraper (`scrape_studio_albums`) is kept but no
  longer wired to a view.
- "Recommended album" (`similars.py`): last.fm has no similar-albums endpoint, so each seed
  artist stores its similar artists (one `artist.getSimilar` call, up to 50, one page) as
  `Similar` rows scored artist rating × match. Seeds are artists, not albums: albums by one
  artist would repeat the same call. The artist with the highest summed score gives the
  recommended album (its last.fm top album, with stand-out tracks as in "more from artist").
  The summed score is only for ranking; it is not a percentage, so it is not shown. Listed
  under it are the user's library artists that recommended it, with their match, best first, up
  to `SIMILARS_ARTISTS_SHOWN` (5). Only the recommended artist's top album and tracks are looked
  up, cached in `default` for 16 h.
- Render first, fetch after: `snippet_similars_recommended.html` renders from the stored `Similar`
  rows, and only when `refreshed` is false carries an `hx-trigger="load"` element that re-requests
  the view with `?refresh=1`, which fetches one seed artist. The refresh render must not carry the
  trigger again, or it loops. Reuse this for any other slow external call on page load.
- Seeds are only the top `SIMILARS_SEED_SHARE` (10%) of artists by `SIMILARS_SEED_ORDERING`
  (ends in `id` so places are stable for the `n/total` progress). Never fetched goes first, then
  the oldest `similars_at` is redone; a refetch deletes that seed's `Similar` rows first.
- `Artist.similars_at` marks a seed done even with zero results; the rows can't be the marker
  because removing a recommendation deletes them. Last.fm "not found" (`WSError` status `'6'`, a
  string) is final; any other `PyLastError` (5xx carry an int status) leaves the artist for retry.
- Recommendations are only of artists not in the library: owned artists are skipped on save and
  their rows deleted on render if the artist was added since. Owned artists are covered by "more
  from artist" instead.
- Matching to the library is by `artist_slug` (= `Artist.slug`, `slugify(unidecode())`) plus
  `track_slug` (same, bracketed suffixes dropped). Never compare raw names.
- Scrobbling blocks playback, so it gets one attempt at pylast's default timeout; the similars
  fetch has nothing waiting on it and may take longer. pylast 5.3 hardcodes `httpx.Timeout(5,
  read=10)` inside `_Request._download_response` with no setting, and patching it is process-wide
  (a concurrent scrobble would inherit it), so the similars fetch retries `NetworkError` instead
  (`SIMILARS_FETCH_ATTEMPTS`).
- Log pylast errors with `{exc}`, never `{exc!r}`: `NetworkError`'s repr carries the
  `LastFMNetwork`, i.e. the api key, secret and session key.

## Database

- SQLite with `OPTIONS: {'timeout': 60}`: the player and long management commands write at the
  same time, and the default 5 s busy wait crashed commands with "database is locked".
- The timeout alone still let "database is locked" through on a long recheck, so
  `signals.retry_locked` is installed on every connection and reruns a locked statement
  forever, outside transactions only: inside one the statement can't be rerun on its own.

## Caching

- `default` is LocMem and is wiped on every restart - fine for querysets, graphs and filters.
- Don't cache model instances whose rows can vanish before the timeout: song validation prunes
  songs, albums and artists. A cached `Album` then lazy-loads a deleted `artist`, the template
  swallows `DoesNotExist` as `''`, and `{% url 'artist' album.artist.id %}` raises
  `NoReverseMatch`. Cheap queries (bad albums: ~10 ms) aren't cached at all.
- `caches['persistent']` is a `FileBasedCache` under `.cache/persistent` (gitignored) for state
  that has to keep building across restarts, currently only `add_album_countdown`. Put a key there
  only if losing it on restart is actually wrong. The autouse fixture in `main/tests.py` swaps it for
  LocMem so tests never touch the real file.

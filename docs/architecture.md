# Code structure

The Python application and browser pages keep their existing entry points and URLs.
There is no frontend build step. Both installers recursively copy `ktvibes/` and
`static/`, including the modules described here.

## Server

- `ktvibes/main.py` provides `ktvibes.main:app`, the `ktvibes` CLI and the source updater.
- `application.create_app(runtime)` builds FastAPI, installs route groups and manages
  the worker, update checker and outstanding lyrics lookup tasks during shutdown.
- `runtime.Runtime` owns one application's playback `State`, cache/root paths,
  port, song library, lyrics service and release checker. Tests create a fresh
  runtime and app instead of replacing production globals.
- `routes/` groups HTTP/WebSocket handlers into system, playback, catalog and lyrics.
  Routers receive their runtime or lyrics service; none imports `main.py`.
- `lyric_service.LyricsService` coordinates lyrics viewing and selection, including
  lookup deduplication, selection races and cache locking. `lyrics.py` remains
  responsible for LRCLIB access and text processing.
- `library.SongLibrary` reads prepared song metadata. `updates.ReleaseUpdates`
  checks GitHub releases and owns the result for its application.
- `queue.State`, `worker` and the audio/language modules retain their existing roles.
  Queue snapshots, cache filenames and HTTP/WebSocket message formats are unchanged.

Use the same `State` instance for the lifetime of a runtime: mutate its queue and
playback properties rather than replacing the instance. Route validation lives
in the router functions and the request models in `schemas.py`.

## Browser

- `remote.js` coordinates incoming state, playback/settings, search and Recent.
- `remote-status.js` owns the status label, version polling and update popover.
- `remote-lyrics.js` owns the reader/picker panel and follows current-song changes.
- `remote-queue.js` owns queue rows, pagination, drag ordering and swipe actions.
- `swipe-state.js` coordinates the single revealed swipe row across Recent and Queue.
- `shared.connect(role, callbacks)` handles WebSocket messages and reconnection.
  It reports open/close events; Remote and TV render their own connection status.

The queue and lyrics modules receive a current-state getter so asynchronous work
and gestures read the latest snapshot. Queue reordering can update that snapshot
optimistically through its supplied setter.

See [Testing](testing.md) for validation commands and the limits of fixture-based
browser checks. The current suite does not prove real media preparation, audio
synchronization or installer behavior on every machine.

## Extension boundaries

- `lyrics.py` owns LRCLIB lookup and matching, and re-exports the existing lyric
  functions for callers. Text/LRC parsing lives in `lyric_text.py`, pronunciation
  models and guides in `lyric_guides.py`, and energy/timing algorithms in
  `lyric_timing.py`. `lyric_cache.py` validates cached viewer choices and expiry.
  Pure lyric operations have no HTTP or playback-state dependency.
- `cache.py` provides atomic JSON and LRC writes. Callers retain responsibility
  for holding the per-video cache lock across read/modify/write operations.
- `worker.run` owns its video-download task registry and dispatches songs through
  `prepare_song`, which coordinates `prepare_media` and `prepare_lyrics`.
  Runtime instances do not share download registries. Preparation still resolves
  manual lyric selections made while downloads or alignment are in progress.
- `queue.State` is the public playback/queue interface. `queue_storage.py` handles
  its saved representation; `queue_transport.py` handles publication, slow-client
  eviction and sending full lyrics to the TV once per song.
- `remote-catalog.js` owns Search, Recent, explicit add/play-next actions and Recent
  swipes. It receives the current-state getter and render callback so optimistic
  queue changes use the latest snapshot. `remote.js` coordinates the page.
- `tv-brand.js` owns the stage's QR/brand rotation timer. `video-frame.js` owns
  baked-in black-bar detection and fitting for performance and ambient videos.
- macOS `NetworkSettings.swift` owns preferences and the native settings window;
  `App.swift` coordinates the tray and restart/rollback operation. The build
  compiles both alongside `ServerProcess.swift`.
- Windows `server-process.ps1` owns start/stop and the child environment. The tray
  dot-sources it alongside `network-settings.ps1` in the same script scope. The
  installer includes both and CI parses every script. WinForms remains the UI.

Refactors retain endpoint names, queue snapshots, cache formats and settings
precedence. Desktop restart/rollback and real audio synchronization still require
platform testing beyond browser fixtures and unit tests.

## Optional external access

`Runtime.access` owns the password verifier, signed sessions, QR secret and login
rate limits for one server run. `KTVIBES_EXTERNAL_ENABLED=1` requires a valid
`KTVIBES_REMOTE_URL` HTTPS address and `KTVIBES_PASSWORD_HASH`. Invalid external
configuration prevents startup rather than exposing an unprotected service.
The legacy URL override alone only changes the advertised address.

External HTTP requests require an owner or remote session. Only owners can open
Player or obtain `/api/qr.svg`; QR pairing grants remote scope. The same scope
and origin checks apply before registering WebSocket clients. Media and catalog
APIs are protected too. Login assets and `/api/auth/{status,login,pair}` remain
public. Credentials are HttpOnly, SameSite=Strict session cookies; external HTTPS
cookies are Secure, while local desktop Player can use a localhost cookie.

QR URLs carry `#key=…`: the fragment is never sent in HTTP request URLs. The access
screen removes it before exchanging it through POST `/api/auth/pair`. A QR key is
reusable by guests during one run; it does not grant Player/TV authority. Server
restart invalidates all keys and signed cookies. Runtime secrets are not persisted.

Desktop launchers pass a separate random `KTVIBES_DESKTOP_TOKEN`; its Bearer header
only permits `/api/config` for readiness/version/address polling, never QR or
playback access. Settings save salted PBKDF2-SHA256 verifiers (600,000 iterations),
not plaintext passwords. Blank password preserves the saved verifier; disabling
External address or Reset clears the external URL and verifier on Apply. Existing
network.json files without these optional fields remain compatible.


PIN-capable settings record `credential_type=pin` and pass
`KTVIBES_CREDENTIAL_TYPE=pin`. Missing type means a legacy password; those settings
still start with password login, but desktop Apply requires a new numeric PIN.
The existing login POST body uses `password` for compatibility; PIN mode validates
at least six ASCII digits. Login status advertises the credential type for the
keypad. Owner-only GET `/api/invite` supplies the full fragment URL for Player's
link/copy/share actions; `/api/config` still never exposes a key. External listeners
bind only the configured port, while LAN listeners retain the candidate sequence.
POSIX listeners use SO_REUSEADDR for fast restarts, Windows uses exclusive binds.
The macOS shell readiness probe uses the desktop credential and `/api/config`.

Player, Remote and login documents reference `/static/<build>/` assets. Relative
JavaScript imports and CSS resources stay under that build namespace, preventing
Cloudflare or browser caches from combining entry points and dependencies from
different releases. Entry documents use `Cache-Control: no-store`; the original
`/static/` URLs remain available for compatibility.

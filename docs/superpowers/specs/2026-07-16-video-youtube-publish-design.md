# video_youtube_publish — Design

**Date:** 2026-07-16
**Status:** Approved

## Purpose

A standalone project that publishes a finished video to YouTube by driving
**YouTube Studio** through an anti-detect **Camoufox** browser session — no Data
API, no OAuth, no API keys. It reuses a logged-in Google/YouTube session, the
same technique as the GAIA project, but is fully independent: its own persistent
Camoufox profile, logged into a **separate** Google account.

It closes the gaps found while running the prototype (`gaia/youtube_upload.py`)
against live Studio:
- the "Verify it's you" identity gate (shadow-DOM, must be human-cleared once),
- uploads to the wrong channel when an account owns several same-named channels,
- silent failure: Studio accepts the upload, then abandons processing because the
  video is longer than the 15-minute limit for **unverified** channels.

## Non-goals (v1)

Batch runner, playlists, editing existing videos, scheduling, Shorts-specific
flows. Single-video publish only.

## Security model (the account-safety spine)

The project is a **public GitHub repo**, but the Camoufox profile holds live
Google session cookies — anyone with it controls the account. Therefore:

- `.gitignore` excludes the profile, fingerprint, debug screenshots (they show the
  logged-in avatar/email), logs, media, and any cookie/sqlite files:
  ```
  venv/  .venv/  __pycache__/  *.pyc  .DS_Store
  .camoufox_profile/
  .camoufox_fp.pkl
  debug/
  output/  input/  *.log
  *.sqlite  cookies*.json
  ```
- A **pre-commit guard** (`.githooks/pre-commit`, enabled via
  `git config core.hooksPath .githooks`) hard-fails if anything matching
  `camoufox|\.sqlite|cookies.*json|^debug/` is staged.
- A **pre-push audit** run before the first `gh` push: `git ls-files` must not
  match those patterns; abort otherwise.
- No account emails, channel IDs, or tokens hardcoded in source.

## Components

Each file has one clear purpose and a small interface.

1. **`camoufox_session.py`** — persistent Camoufox launch (own
   `.camoufox_profile/` + pinned fingerprint) and a `logged_in()` check.
   Self-contained; adapted (trimmed) from gaia's `gemini_common`. Interface:
   `make_camoufox(headless) -> context manager`, `prepare_page(context) -> page`,
   `logged_in(page) -> bool`.

2. **`login.py`** — one-time setup. Opens a visible Camoufox window; the human
   signs into the target YouTube/Google account manually; the session persists in
   this project's own profile. No Firefox-cookie bootstrap (it is a different
   account than any local Firefox profile). CLI: `python3 login.py [--headless]`.

3. **`youtube_ui.py`** — shadow-DOM-aware UI helpers shared by the flow:
   `deep_dump`, `click_text`, `fill_contenteditable`, `first_present`,
   `dismiss_overlays`, `all_text` (light+shadow walker), and
   `verify_gate_present(page)`.

4. **`precheck.py`** — pre-flight validation:
   - `video_duration(path) -> seconds` via `ffprobe`.
   - `channel_verified(page) -> bool` by reading the channel's feature/limit
     state in Studio.
   - `check(page, video, allow_long) -> (ok, reason)`; blocks when duration
     > 15 min and the channel is not verified, unless `--allow-long`.

5. **`channel.py`** — select the active channel to publish to. Given
   `--channel-id` or `--channel-handle`, resolve the target and switch Studio's
   active channel to it (navigate to its Studio URL / use the account switcher),
   then assert the active channel matches before uploading. Prevents the
   wrong-same-named-channel bug.

6. **`verify_result.py`** — after Save, confirm reality: poll the channel Content
   list for the uploaded title; detect `Processing abandoned` / `too long` /
   error notices; return `(status, url)` where status ∈
   {published, processing, failed:<reason>}.

7. **`publish.py`** — the orchestrator / CLI wiring the above together.

## Publish flow (`publish.py`)

1. Load metadata (video_maker JSON merged with CLI overrides; title ≤100 chars,
   tags capped ≤ ~480 chars).
2. Launch Camoufox session; open `studio.youtube.com`. If redirected to sign-in →
   exit code 3.
3. If a **"Verify it's you"** gate is present: screenshot, and with `--keep-open`
   wait up to `--verify-wait` seconds for the human to clear it in the window,
   polling until gone; else exit 7 with instructions.
4. **Channel select** (`channel.py`): switch to `--channel-id`/`--channel-handle`
   and assert active channel.
5. **Pre-check** (`precheck.py`): abort (exit 8) if too long & unverified without
   `--allow-long`.
6. Dismiss overlays; open the upload dialog via the topbar/dashboard "Upload
   videos" control; wait for the hidden `<input type=file>` to exist;
   `set_input_files(video)`.
7. Fill Details: title, description, tags (behind "Show more"), thumbnail (when
   its input appears), audience ("Not made for kids" by default).
8. Next × 3 → set visibility (default **private**) → Save.
9. **Verify result** (`verify_result.py`): return the real status + watch URL.

## CLI

```
python3 publish.py \
  --video PATH [required] \
  --metadata video_maker_metadata.json \
  --thumbnail PATH \
  --title ... --description ... --tags "a,b,c" \
  --channel-id UC... | --channel-handle @name \
  --visibility {private|unlisted|public}   # default private \
  --made-for-kids \
  --allow-long \
  --verify-wait 900 \
  --keep-open --debug
```

Exit codes: `0` ok · `2` bad args · `3` not logged in · `4` couldn't start
upload · `5` details failed · `6` couldn't finish/verify · `7` blocked by
"Verify it's you" · `8` pre-check failed (too long / wrong channel).

## Dependencies

- Camoufox + Playwright, version-pinned to a working range (mirror gaia's
  `requirements.txt`; Python 3.11–3.13, not 3.14).
- `ffmpeg` (`ffprobe`) for duration.
- `python3 -m camoufox fetch` one-time.

## Publishing to GitHub

After the pre-push secret audit passes:
```
gh repo create suenot/video_youtube_publish --public --source=. \
  --remote=origin --push
```

## Repo layout

```
video_youtube_publish/
├── README.md                 # setup, usage, ⚠️ account-safety warning
├── requirements.txt
├── .gitignore
├── .githooks/pre-commit      # blocks staging secrets
├── camoufox_session.py
├── login.py
├── youtube_ui.py
├── precheck.py
├── channel.py
├── verify_result.py
├── publish.py
├── input/                    # gitignored (source videos)
├── output/                   # gitignored (logs/results)
└── debug/                    # gitignored (step screenshots)
```

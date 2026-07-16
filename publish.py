import argparse
import asyncio
import sys
import time
from pathlib import Path

from camoufox_session import make_camoufox, prepare_page, logged_in_youtube, log, shot
from metadata import load_metadata
from precheck import video_duration, check
from channel import select_channel, channel_id_from_url
from verify_result import parse_status
import youtube_ui as ui

STUDIO = "https://studio.youtube.com"


async def _goto(page, url, tries=3):
    last = None
    for _ in range(tries):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            return
        except Exception as e:
            last = e
            await page.wait_for_timeout(1500)
    if last:
        raise last


async def open_upload(page, video, debug):
    await ui.dismiss_overlays(page)
    for sel in ("ytcp-icon-button#upload-icon", "ytcp-button#upload-button",
                "button[aria-label='Upload videos']"):
        loc = page.locator(sel)
        try:
            if await loc.count() > 0 and await loc.first.is_visible():
                await loc.first.click(timeout=4000)
                break
        except Exception:
            continue
    else:
        await ui.click_text(page, ["Create"], 8000)
        await page.wait_for_timeout(800)
        await ui.click_text(page, ["Upload video"], 5000)
    await page.wait_for_timeout(1500)
    await ui.dismiss_overlays(page)
    await shot(page, "yt_02_upload_dialog", debug)
    fi = await ui.first_present(
        page, ["ytcp-uploads-dialog input[type='file']", "input[type='file']"], 15000)
    if fi is None:
        log("  no file input found")
        return False
    await fi.set_input_files(str(video))
    log(f"  selected: {video.name}")
    await page.wait_for_timeout(4000)
    return True


async def fill_details(page, meta, thumbnail, made_for_kids, debug):
    tb = await ui.first_present(page, ["#title-textarea #textbox"], 30000)
    if tb is not None and meta["title"]:
        await ui.fill_contenteditable(page, tb, meta["title"])
        log("  title set")
    db = await ui.first_present(page, ["#description-textarea #textbox"], 5000)
    if db is not None and meta["description"]:
        await ui.fill_contenteditable(page, db, meta["description"])
        log("  description set")
    if thumbnail and Path(thumbnail).is_file():
        th = page.locator("ytcp-thumbnails-compact-editor-uploader input[type='file'], "
                          "#file-loader input[type='file']")
        try:
            if await th.count() > 0:
                await th.first.set_input_files(str(thumbnail))
                log("  thumbnail set")
                await page.wait_for_timeout(2000)
            else:
                log("  thumbnail input not ready; skipping")
        except Exception:
            log("  thumbnail failed; skipping")
    if meta["tags"]:
        await ui.click_text(page, ["Show more"], 4000)
        await page.wait_for_timeout(800)
        ti = await ui.first_present(page, ["input[aria-label='Tags']",
                                           "#tags-container input#text-input"], 4000)
        if ti is not None:
            await ti.click(timeout=3000)
            await page.keyboard.type(", ".join(meta["tags"]) + ",", delay=2)
            log("  tags set")
    name = ("VIDEO_MADE_FOR_KIDS_MFK" if made_for_kids
            else "VIDEO_MADE_FOR_KIDS_NOT_MFK")
    r = page.locator(f"tp-yt-paper-radio-button[name='{name}']")
    try:
        if await r.count() > 0:
            await r.first.click(timeout=4000)
            log("  audience set")
    except Exception:
        pass
    await shot(page, "yt_05_details", debug)


async def click_next(page, times, debug):
    for i in range(times):
        nx = page.locator("ytcp-button#next-button, #next-button")
        try:
            if await nx.count() > 0 and await nx.first.is_visible():
                await nx.first.click(timeout=5000)
                await page.wait_for_timeout(1500)
        except Exception:
            pass


async def set_visibility(page, visibility, debug):
    name = {"private": "PRIVATE", "unlisted": "UNLISTED",
            "public": "PUBLIC"}.get(visibility, "PRIVATE")
    r = page.locator(f"tp-yt-paper-radio-button[name='{name}']")
    try:
        if await r.count() > 0:
            await r.first.click(timeout=5000)
            log(f"  visibility: {visibility}")
    except Exception:
        pass
    await shot(page, "yt_07_visibility", debug)


async def save(page, debug):
    d = page.locator("ytcp-button#done-button, #done-button")
    try:
        if await d.count() > 0 and await d.first.is_visible():
            await d.first.click(timeout=6000)
            log("  clicked Save")
    except Exception:
        pass
    await page.wait_for_timeout(4000)
    await shot(page, "yt_08_saved", debug)


async def clear_verify_gate(page, args, reload_after=False):
    """Google's 'Verify it's you' gate can appear at load OR mid-upload (right
    after the sensitive upload action). Returns True if clear to proceed, False
    if still gated. Never navigates away unless reload_after=True (safe only at
    load time — never mid-upload, which would discard the upload dialog)."""
    if not await ui.verify_gate_present(page):
        return True
    log("BLOCKED: 'Verify it's you' challenge.")
    await shot(page, "yt_verify_gate", True)
    if not args.keep_open:
        log("  Re-run with --keep-open and clear it in the window.")
        return False
    log(f"  Complete it in the window; waiting up to {args.verify_wait}s...")
    await ui.click_text(page, ["Next", "Continue"], 4000)
    end = time.time() + args.verify_wait
    while time.time() < end and await ui.verify_gate_present(page):
        await page.wait_for_timeout(3000)
    if await ui.verify_gate_present(page):
        log("  still gated; aborting.")
        return False
    log("  verification cleared.")
    if reload_after:
        await _goto(page, STUDIO)
        await page.wait_for_timeout(3000)
    return True


async def run(args):
    video = Path(args.video).expanduser()
    if not video.is_file():
        log(f"ERROR: --video not found: {video}")
        return 2
    meta = load_metadata(args.metadata, args.title, args.description, args.tags)
    if not meta["title"]:
        meta["title"] = video.stem.replace("-", " ").replace("_", " ").title()

    async with make_camoufox(args.headless) as ctx:
        page = await prepare_page(ctx)
        page.on("dialog", lambda d: asyncio.create_task(d.accept()))
        await _goto(page, STUDIO)
        await page.wait_for_timeout(4000)
        await shot(page, "yt_01_studio", args.debug)
        if not await logged_in_youtube(page):
            log("ERROR: not logged in. Run login.py first.")
            return 3

        if not await clear_verify_gate(page, args, reload_after=True):
            return 7

        if args.channel_id or args.channel_handle:
            await select_channel(page, args.channel_id, args.channel_handle)

        verified = False  # conservative default; long videos need --allow-long
        dur = video_duration(str(video))
        ok, reason = check(dur, verified, args.allow_long)
        if not ok:
            log(f"PRECHECK FAILED: {reason}")
            return 8
        log(f"  duration {int(dur)}s ok")

        if not await open_upload(page, video, args.debug):
            return 4
        # The gate most often fires here — on the sensitive upload action. Clear
        # it BEFORE filling details, so title/description/tags/audience/Save are
        # not silently blocked by the modal. No reload (would drop the dialog).
        if not await clear_verify_gate(page, args):
            return 7
        await fill_details(page, meta, args.thumbnail, args.made_for_kids, args.debug)
        await click_next(page, 3, args.debug)
        await set_visibility(page, args.visibility, args.debug)
        await save(page, args.debug)

        # Capture the watch id from the save dialog (for blog embedding).
        try:
            import re as _re
            html = await page.content()
            m = (_re.search(r"youtu\.be/([\w-]{6,})", html)
                 or _re.search(r"watch\?v=([\w-]{6,})", html))
            if m:
                log(f"VIDEO_ID: {m.group(1)}")
        except Exception:
            pass

        active = channel_id_from_url(page.url)
        if active:
            await _goto(page, f"{STUDIO}/channel/{active}/videos/upload")
            await page.wait_for_timeout(5000)
        text = await ui.all_text(page)
        status, note = parse_status(text, meta["title"])
        log(f"RESULT: status={status} note={note}")
        if args.keep_open:
            log("--keep-open: browser stays open. Ctrl+C to quit.")
            while True:
                await page.wait_for_timeout(3600_000)
        return 0 if status in ("present", "processing") else 6


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Publish a video to YouTube via Camoufox.")
    p.add_argument("--video", required=True)
    p.add_argument("--metadata", default="")
    p.add_argument("--thumbnail", default="")
    p.add_argument("--title", default="")
    p.add_argument("--description", default="")
    p.add_argument("--tags", default="")
    p.add_argument("--channel-id", default="")
    p.add_argument("--channel-handle", default="")
    p.add_argument("--visibility", default="private",
                   choices=["private", "unlisted", "public"])
    p.add_argument("--made-for-kids", action="store_true")
    p.add_argument("--allow-long", action="store_true")
    p.add_argument("--verify-wait", type=int, default=600)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--keep-open", action="store_true")
    p.add_argument("--debug", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

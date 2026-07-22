import argparse
import asyncio
import sys
import time
from pathlib import Path

from camoufox_session import make_camoufox, prepare_page, logged_in_youtube, log, shot
from metadata import load_metadata
from precheck import video_duration, check
from channel import select_channel, channel_id_from_url, _strip_backdrops
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
    # Opening the upload dialog is flaky: the Create menu doesn't always expand,
    # and a transient cdk-overlay-backdrop can eat the click. Deep-linking to
    # .../videos/upload no longer auto-opens the dialog (it just lands on the
    # Content list). So: go to the Studio home, neutralize backdrops, click the
    # Create button, then the "Upload video" item — retrying the whole sequence.
    fi = None
    for attempt in range(3):
        try:
            await _goto(page, STUDIO)
            await page.wait_for_timeout(2500)
        except Exception:
            pass
        await ui.dismiss_overlays(page)
        await _strip_backdrops(page)

        # Locator.click() times out on these controls even though they are
        # visible and unobstructed — Studio's polymer layer keeps failing the
        # actionability check. A real mouse click at the element's centre works,
        # so drive the mouse directly.
        clicked = False
        for sel in ("ytcp-icon-button#upload-icon",
                    "button[aria-label='Upload videos']",
                    "button[aria-label='Create']"):
            loc = page.locator(sel)
            try:
                if await loc.count() == 0 or not await loc.first.is_visible():
                    continue
                box = await loc.first.bounding_box()
                if not box:
                    continue
                await page.mouse.click(box["x"] + box["width"] / 2,
                                       box["y"] + box["height"] / 2)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            await ui.click_text(page, ["Create"], 8000)
        await page.wait_for_timeout(1200)
        await _strip_backdrops(page)
        # If a menu opened, pick "Upload video". (When the upload-icon was used
        # the dialog is already opening and this is a harmless no-op.)
        await ui.click_text(page, ["Upload video", "Upload videos"], 5000)
        await page.wait_for_timeout(2000)
        await ui.dismiss_overlays(page)
        await _strip_backdrops(page)
        await shot(page, "yt_02_upload_dialog", debug)
        fi = await ui.first_present(
            page, ["ytcp-uploads-dialog input[type='file']", "input[type='file']"], 15000)
        if fi is not None:
            break
        log(f"  no file input found (attempt {attempt + 1}); retrying")
        await page.wait_for_timeout(2000)
    if fi is None:
        log("  no file input found")
        return False
    await fi.set_input_files(str(video))
    log(f"  selected: {video.name}")
    await page.wait_for_timeout(4000)
    # Big uploads keep the details dialog dimmed ("Creating link...") until the
    # video entity exists; editing before that silently fails. Wait until that
    # text clears AND the audience radio is actually clickable (the dialog is
    # only interactive then). YouTube can throttle this for minutes after many
    # uploads, so wait up to ~8 min.
    ready = False
    for _ in range(160):
        try:
            txt = (await ui.all_text(page))
        except Exception:
            txt = ""
        creating = "creating link" in txt
        r = page.locator("tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']")
        try:
            enabled = await r.count() > 0 and await r.first.is_enabled()
        except Exception:
            enabled = False
        if not creating and enabled:
            ready = True
            log("  details dialog is interactive")
            break
        await page.wait_for_timeout(3000)
    if not ready:
        log("  WARNING: dialog still not interactive (YouTube throttling link "
            "creation?) — details may not stick")
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
    ok = await set_audience(page, made_for_kids)
    await shot(page, "yt_05_details", debug)
    return ok


async def set_audience(page, made_for_kids):
    """Answer the required "made for kids" question.

    Leaving it unanswered is what silently blocks Next: the wizard sits on the
    details step forever and the upload ends its life as a draft. Studio renders
    the radio twice (once in a collapsed section), and the first copy is not
    always the live one, so try every match and trust only aria-checked.
    """
    name = ("VIDEO_MADE_FOR_KIDS_MFK" if made_for_kids
            else "VIDEO_MADE_FOR_KIDS_NOT_MFK")
    r = page.locator(f"tp-yt-paper-radio-button[name='{name}']")
    for attempt in range(3):
        n = await r.count()
        for i in range(n):
            el = r.nth(i)
            if (await el.get_attribute("aria-checked")) == "true":
                log("  audience set")
                return True
            await _try_click(page, el)
            await page.wait_for_timeout(500)
            if (await el.get_attribute("aria-checked")) == "true":
                log("  audience set")
                return True
        await page.wait_for_timeout(1000)
    log("  ERROR: 'made for kids' left unanswered; the wizard will not advance")
    return False


VISIBILITY_RADIO = "tp-yt-paper-radio-button[name='{}']"


async def _try_click(page, loc):
    """Locator.click() first, mouse click as the fallback."""
    try:
        await loc.click(timeout=4000)
        return True
    except Exception:
        return await ui.mouse_click(page, loc)


async def click_next(page, times, debug):
    """Advance the details wizard until the visibility step is on screen.

    Every step of this used to swallow its failures, so a wizard that never
    advanced still reported success and left the upload sitting as a private
    draft with the filename as its title. Now the caller is told.
    """
    for _ in range(times + 5):
        if await page.locator(VISIBILITY_RADIO.format("PUBLIC")).count() > 0:
            return True
        # Studio autosaves the details as they are typed and disables Next while
        # the "Saving..." chip is up; clicking through it does nothing.
        for _ in range(10):
            if "saving" not in (await ui.all_text(page)).lower():
                break
            await page.wait_for_timeout(1000)
        nx = page.locator("ytcp-button#next-button, #next-button")
        clicked = False
        try:
            if await nx.count() > 0 and await nx.first.is_visible():
                clicked = await _try_click(page, nx.first)
        except Exception:
            clicked = False
        if not clicked:
            # The draft wizard reached via "Edit draft" renders a plain Next
            # button without the #next-button id the upload dialog uses.
            clicked = await ui.click_text(page, ["Next"], 4000)
        await page.wait_for_timeout(1800)
    reached = await page.locator(VISIBILITY_RADIO.format("PUBLIC")).count() > 0
    if not reached:
        log("  ERROR: never reached the visibility step")
    return reached


async def set_visibility(page, visibility, debug):
    name = {"private": "PRIVATE", "unlisted": "UNLISTED",
            "public": "PUBLIC"}.get(visibility, "PRIVATE")
    r = page.locator(VISIBILITY_RADIO.format(name))
    ok = False
    for attempt in range(3):
        if await r.count() == 0:
            await page.wait_for_timeout(1000)
            continue
        await _try_click(page, r.first)
        await page.wait_for_timeout(600)
        # aria-checked is the only trustworthy signal: the click can land on the
        # row without selecting the radio underneath it.
        if (await r.first.get_attribute("aria-checked")) == "true":
            ok = True
            break
    await shot(page, "yt_07_visibility", debug)
    if ok:
        log(f"  visibility: {visibility}")
    else:
        log(f"  ERROR: could not select visibility '{visibility}'")
    return ok


async def save(page, debug):
    d = page.locator("ytcp-button#done-button, #done-button")
    clicked = False
    for attempt in range(3):
        try:
            if await d.count() == 0 or not await d.first.is_visible():
                await page.wait_for_timeout(1000)
                continue
        except Exception:
            await page.wait_for_timeout(1000)
            continue
        await _try_click(page, d.first)
        await page.wait_for_timeout(3000)
        # Save is confirmed by the dialog going away, not by the click itself.
        try:
            if await d.count() == 0 or not await d.first.is_visible():
                clicked = True
                break
        except Exception:
            clicked = True
            break
    await page.wait_for_timeout(1000)
    await shot(page, "yt_08_saved", debug)
    if clicked:
        log("  clicked Save")
    else:
        log("  ERROR: Save did not take effect (details dialog still open)")
    return clicked


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
        if not await fill_details(page, meta, args.thumbnail,
                                  args.made_for_kids, args.debug):
            log("PUBLISH FAILED: audience question unanswered; the upload is "
                "left as a draft")
            return 9
        if not await click_next(page, 3, args.debug):
            log("PUBLISH FAILED: wizard never reached the visibility step; "
                "the upload is left as a draft")
            return 9
        if not await set_visibility(page, args.visibility, args.debug):
            log("PUBLISH FAILED: visibility not applied; refusing to report success")
            return 9
        if not await save(page, args.debug):
            log("PUBLISH FAILED: Save did not take effect; the upload is left as a draft")
            return 9

        # Capture the watch id from the save dialog (for blog embedding).
        # Only trust the short youtu.be/<id> share link the save dialog renders —
        # a plain watch?v= match can come from the Content list sitting behind
        # the dialog and yields a DIFFERENT (older) video's id. Poll for it.
        # A Short's share link is youtube.com/shorts/<id> rather than youtu.be/<id>.
        import re as _re
        vid = None
        for _ in range(12):
            try:
                html = await page.content()
                m = (_re.search(r"youtu\.be/([\w-]{6,})", html)
                     or _re.search(r"youtube\.com/shorts/([\w-]{6,})", html))
                if m:
                    vid = m.group(1)
                    break
            except Exception:
                pass
            await page.wait_for_timeout(1000)
        if vid:
            log(f"VIDEO_ID: {vid}")
        else:
            log("VIDEO_ID: not found in save dialog (check channel RSS)")

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

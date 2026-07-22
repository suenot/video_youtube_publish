#!/usr/bin/env python3
"""Delete a video from a channel, permanently.

    python delete_video.py @suenot VIDEO_ID [VIDEO_ID ...]

This removes the video for good — YouTube offers no undo. It exists to clean up
duplicates a failed-then-retried upload left behind; check that the id is the
copy you mean to lose before running it.

Driven from the video's own edit page (Options → Delete forever) rather than the
content list, which needs row scraping through shadow DOM.
"""
import argparse
import asyncio
import sys

from camoufox_session import make_camoufox, prepare_page, log, shot
from channel import resolve_channel_id, select_channel
import youtube_ui as ui

STUDIO_VIDEO = "https://studio.youtube.com/video/{vid}/edit"


async def delete_one(page, vid: str, debug: bool = True) -> bool:
    await page.goto(STUDIO_VIDEO.format(vid=vid), wait_until="domcontentloaded",
                    timeout=60_000)
    await page.wait_for_timeout(7000)
    await ui.dismiss_overlays(page)

    title_el = await ui.first_present(page, ["#title-textarea #textbox"], 20000)
    if title_el is None:
        log(f"  {vid}: edit page did not load (wrong channel?)")
        return False
    title = (await title_el.inner_text()).strip()
    log(f"  {vid}: {title[:70]!r}")

    menu = page.locator("ytcp-icon-button#overflow-menu-button")
    if await menu.count() == 0:
        log(f"  {vid}: no Options menu")
        return False
    await ui.mouse_click(page, menu.first)
    await page.wait_for_timeout(1500)

    # The menu entry is plain "Delete"; "Delete forever" is the confirm button
    # inside the dialog it opens.
    if not await ui.click_text(page, ["Delete"], 6000):
        log(f"  {vid}: no 'Delete' entry in the Options menu")
        await page.keyboard.press("Escape")
        return False
    await page.wait_for_timeout(2500)

    # The confirm dialog requires ticking "I understand..." before its button
    # becomes usable.
    box = page.locator("ytcp-checkbox-lit, tp-yt-paper-checkbox")
    if await box.count() > 0:
        await ui.mouse_click(page, box.first)
        await page.wait_for_timeout(800)
    await shot(page, f"delete_{vid}_confirm", debug)

    confirmed = False
    for label in ("Delete forever", "Delete video", "Delete"):
        btn = page.locator(f"ytcp-button:has-text('{label}'), button:has-text('{label}')")
        n = await btn.count()
        for i in range(n):
            el = btn.nth(i)
            try:
                if not await el.is_visible() or not await el.is_enabled():
                    continue
            except Exception:
                continue
            if await ui.mouse_click(page, el):
                confirmed = True
                break
        if confirmed:
            break
    if not confirmed:
        log(f"  {vid}: could not press the confirm button")
        return False
    await page.wait_for_timeout(6000)

    # Confirm by reloading: a deleted video's edit page no longer has a title.
    await page.goto(STUDIO_VIDEO.format(vid=vid), wait_until="domcontentloaded",
                    timeout=60_000)
    await page.wait_for_timeout(6000)
    gone = await ui.first_present(page, ["#title-textarea #textbox"], 8000) is None
    log(f"  {vid}: {'DELETED' if gone else 'STILL THERE'}")
    return gone


async def main(args) -> int:
    failed = []
    async with make_camoufox(args.headless) as ctx:
        page = await prepare_page(ctx)
        active = await select_channel(page, handle=args.channel_handle)
        wanted = await resolve_channel_id(page, args.channel_handle)
        if wanted and active != wanted:
            log(f"ABORT: on channel {active}, wanted {wanted}")
            return 3
        for vid in args.video_ids:
            if not await delete_one(page, vid, args.debug):
                failed.append(vid)
    log(f"RESULT: {len(args.video_ids) - len(failed)}/{len(args.video_ids)} deleted")
    return 0 if not failed else 1


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("channel_handle")
    p.add_argument("video_ids", nargs="+")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--debug", action="store_true", default=True)
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))

#!/usr/bin/env python3
"""Finish an upload that publish.py left stranded as a draft.

When the details wizard fails to reach the visibility step, the upload survives
as a draft: no title, no description, not public. Re-uploading makes a duplicate
of a video that is already on the channel, so finish the existing one instead.

    python finish_draft.py @marketmaker-zh VIDEO_ID metadata.json [--visibility public]

The edit page cannot fix a draft -- it disables everything with "Feature
unavailable while video is in a draft state" -- but its "Edit draft" button
reopens the very wizard that failed, with the uploaded file already attached.
"""
import argparse
import asyncio
import sys

from camoufox_session import make_camoufox, prepare_page, log
from channel import select_channel
from metadata import load_metadata
from publish import fill_details, click_next, set_visibility, save
import youtube_ui as ui

STUDIO_VIDEO = "https://studio.youtube.com/video/{vid}/edit"


async def finish(page, vid: str, meta, thumbnail: str, visibility: str,
                 made_for_kids: bool, debug: bool) -> bool:
    await page.goto(STUDIO_VIDEO.format(vid=vid), wait_until="domcontentloaded",
                    timeout=60_000)
    await page.wait_for_timeout(6000)
    await ui.dismiss_overlays(page)

    text = await ui.all_text(page)
    if "draft state" not in text.lower():
        log(f"  {vid} is not a draft; use set_visibility.py instead")
        return False

    # The button mounts late and is sometimes covered by a just-dismissed
    # overlay, so retry with a reload rather than giving up on one miss.
    opened = False
    for attempt in range(3):
        if await ui.click_text(page, ["Edit draft"], 15000):
            opened = True
            break
        btn = page.locator("ytcp-button:has-text('Edit draft'), "
                           "button:has-text('Edit draft')")
        if await btn.count() > 0 and await ui.mouse_click(page, btn.first):
            opened = True
            break
        await page.reload(wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(6000)
        await ui.dismiss_overlays(page)
    if not opened:
        log(f"  {vid} could not open the draft wizard")
        return False
    await page.wait_for_timeout(6000)

    if not await fill_details(page, meta, thumbnail, made_for_kids, debug):
        return False
    if not await click_next(page, 3, debug):
        return False
    if not await set_visibility(page, visibility, debug):
        return False
    return await save(page, debug)


async def main(args) -> int:
    meta = load_metadata(args.metadata, args.title, args.description, args.tags)
    async with make_camoufox(args.headless) as ctx:
        page = await prepare_page(ctx)
        await select_channel(page, handle=args.channel_handle)
        ok = await finish(page, args.video_id, meta, args.thumbnail,
                          args.visibility, args.made_for_kids, args.debug)
    log(f"RESULT: {'finished' if ok else 'FAILED'} {args.video_id}")
    return 0 if ok else 1


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("channel_handle")
    p.add_argument("video_id")
    p.add_argument("--metadata", default="")
    p.add_argument("--title", default="")
    p.add_argument("--description", default="")
    p.add_argument("--tags", default="")
    p.add_argument("--thumbnail", default="")
    p.add_argument("--visibility", default="public")
    p.add_argument("--made-for-kids", action="store_true")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--debug", action="store_true")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))

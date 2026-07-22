#!/usr/bin/env python3
"""Report the audio language YouTube has stored for each of a channel's videos.

Reads it out of the edit page's embedded state rather than the rendered form:
the language control lives behind "Show more" and needs two clicks to reveal,
while the same value sits in the page HTML as
`"audiolanguage":{"languagecode":"akk"}` and can be read without touching
anything. Nothing is clicked and nothing is saved.

    python audit_language.py @marketmaker-zh --expect zh-Hans VID [VID ...]
    python audit_language.py @marketmaker-cc --expect en --ids-file ids.txt

Exit code is 1 when any video's language differs from --expect (or is unset),
so a run can gate a follow-up fix.
"""
import argparse
import asyncio
import re
import sys

from camoufox_session import make_camoufox, prepare_page, log
from channel import resolve_channel_id, select_channel

STUDIO_VIDEO = "https://studio.youtube.com/video/{vid}/edit"
# The key is camelCase in the page source; the probe that found it had already
# lowercased the text, which is why a lowercase pattern reads nothing.
LANG_RE = re.compile(r'"audioLanguage":\s*\{\s*"languageCode":\s*"([\w-]+)"',
                     re.IGNORECASE)


async def read_language(page, vid: str) -> str:
    """Return the stored language code for `vid`.

    "" means the language is unset; "NOLOAD" means the edit page never rendered
    — normally because the video belongs to a different channel, which must not
    be reported as an unset language.
    """
    await page.goto(STUDIO_VIDEO.format(vid=vid), wait_until="domcontentloaded",
                    timeout=60_000)
    await page.wait_for_timeout(6000)
    html = await page.content()
    m = LANG_RE.search(html)
    if m:
        return m.group(1)
    return "" if "title-textarea" in html else "NOLOAD"


async def main(args) -> int:
    ids = list(args.video_ids)
    if args.ids_file:
        with open(args.ids_file, encoding="utf-8") as f:
            ids += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if not ids:
        log("no video ids given")
        return 2

    bad = []
    async with make_camoufox(args.headless) as ctx:
        page = await prepare_page(ctx)
        await select_channel(page, handle=args.channel_handle)
        for vid in ids:
            code = await read_language(page, vid)
            ok = (code == args.expect) if args.expect else bool(code)
            log(f"{vid} {code or 'UNSET':<10} {'ok' if ok else 'MISMATCH'}")
            if not ok:
                bad.append((vid, code))
    log(f"RESULT: {len(ids) - len(bad)}/{len(ids)} ok on {args.channel_handle}")
    for vid, code in bad:
        log(f"  fix {vid} (reads {code or 'unset'!r})")
    return 1 if bad else 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("channel_handle")
    p.add_argument("video_ids", nargs="*")
    p.add_argument("--ids-file", default="")
    p.add_argument("--expect", default="",
                   help="expected language code, e.g. en, ru, zh-Hans")
    p.add_argument("--headless", action="store_true")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))

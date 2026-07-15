import re
from camoufox_session import log

STUDIO = "https://studio.youtube.com"


def normalize_handle(handle):
    h = handle.strip().rstrip("/")
    h = h.split("/")[-1]
    if not h.startswith("@"):
        h = "@" + h
    return h


def channel_id_from_url(url):
    m = re.search(r"/channel/(UC[\w-]+)", url or "")
    return m.group(1) if m else None


async def select_channel(page, channel_id=None, handle=None):
    target = channel_id
    if not target and handle:
        h = normalize_handle(handle)
        await page.goto(f"https://www.youtube.com/{h}",
                        wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(3000)
        html = await page.content()
        m = re.search(r'"channelId":"(UC[\w-]+)"', html)
        target = m.group(1) if m else None
        if not target:
            log(f"  could not resolve handle {h} to a channel id")
            return None
    if target:
        await page.goto(f"{STUDIO}/channel/{target}",
                        wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(4000)
    active = channel_id_from_url(page.url)
    if target and active != target:
        log(f"  WARNING: asked for {target} but active channel is {active} "
            "(account may not own it)")
    else:
        log(f"  active channel: {active}")
    return active

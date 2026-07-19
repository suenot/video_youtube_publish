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


async def resolve_channel_id(page, handle):
    """Resolve @handle -> UC... via the public channel page."""
    h = normalize_handle(handle)
    await page.goto(f"https://www.youtube.com/{h}",
                    wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(2500)
    html = await page.content()
    m = (re.search(r'"channelId":"(UC[\w-]+)"', html)
         or re.search(r'/channel/(UC[\w-]+)', html))
    return m.group(1) if m else None


async def _strip_backdrops(page):
    """Remove transient cdk-overlay-backdrop elements that intercept pointer
    events on the 2026 Studio UI, so a real click can land on the target."""
    try:
        await page.evaluate(
            "document.querySelectorAll('.cdk-overlay-backdrop,tp-yt-iron-overlay-backdrop')"
            ".forEach(e => { e.style.pointerEvents='none'; })")
    except Exception:
        pass


async def _real_click(page, locator, timeout=4000):
    """Real (trusted) click with backdrop removal + retry — needed for the
    account card, whose polymer navigation does NOT fire on a synthetic click."""
    for _ in range(3):
        await _strip_backdrops(page)
        try:
            await locator.click(timeout=timeout)
            return True
        except Exception:
            await page.wait_for_timeout(800)
    return False


async def _click_switch_card(page, needle):
    """Real Playwright click on the Accounts-panel card containing `needle`.
    A synthetic JS click does NOT fire YouTube's polymer navigation, so we click
    the card element for real. `needle` is a handle like '@marketmaker-cc' (unique
    enough not to also match '@marketmaker-school-ru')."""
    # The Accounts panel can take a few seconds to populate after "Switch
    # account"; wait for the target card to actually render before clicking.
    for sel in (f"ytd-account-item-renderer:has-text(\"{needle}\")",
                f"tp-yt-paper-item:has-text(\"{needle}\")",
                f"a#endpoint:has-text(\"{needle}\")"):
        loc = page.locator(sel)
        try:
            await loc.first.wait_for(state="visible", timeout=8000)
        except Exception:
            continue
        if await _real_click(page, loc.first):
            return True
    try:
        await page.get_by_text(needle).first.click(timeout=4000)
        return True
    except Exception:
        return False


async def select_channel(page, channel_id=None, handle=None):
    """Switch Studio's active channel to a brand channel via the account switcher.
    Deep-linking to /channel/<id> does NOT work for brand channels (permission
    error) — the account context must be switched via the Accounts panel."""
    import youtube_ui as ui  # local import avoids a module-load cycle

    target = channel_id
    if not target and handle:
        target = await resolve_channel_id(page, handle)
        if not target:
            log(f"  could not resolve {handle} to a channel id")

    await page.goto(STUDIO, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(3000)
    if target and channel_id_from_url(page.url) == target:
        log(f"  already on target channel: {target}")
        return target

    for sel in ("button#avatar-btn", "ytcp-icon-button#avatar-btn",
                "button[aria-label='Account']"):
        b = page.locator(sel)
        try:
            if await b.count() > 0 and await b.first.is_visible():
                if await _real_click(page, b.first):
                    break
        except Exception:
            continue
    await page.wait_for_timeout(1500)
    await _strip_backdrops(page)
    await ui.click_text(page, ["Switch account"], 5000)
    await page.wait_for_timeout(3000)

    needle = normalize_handle(handle) if handle else (target or "")
    ok = await _click_switch_card(page, needle)
    # Switching reloads Studio as the new channel — wait for that.
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    await page.wait_for_timeout(4000)

    active = channel_id_from_url(page.url)
    if target and active != target:
        log(f"  WARNING: wanted {target} but active is {active} (clicked={ok})")
    else:
        log(f"  switched; active channel: {active} (clicked={ok})")
    return active

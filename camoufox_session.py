import pickle
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / ".camoufox_profile"
FP_FILE = HERE / ".camoufox_fp.pkl"
DEBUG_DIR = HERE / "debug"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _geoip_available():
    try:
        import socket
        socket.create_connection(("api.ipify.org", 443), timeout=3).close()
        return True
    except Exception:
        return False


def _stable_fingerprint():
    # FP_FILE is a locally-generated, git-ignored fingerprint written only by this
    # project (never from an external/untrusted source), so unpickling it is safe.
    if FP_FILE.exists():
        try:
            return pickle.loads(FP_FILE.read_bytes())
        except Exception:
            return None
    return None


def make_camoufox(headless=False):
    from camoufox.async_api import AsyncCamoufox
    PROFILE_DIR.mkdir(exist_ok=True)
    opts = dict(headless=headless, humanize=True, geoip=_geoip_available(),
                block_images=False, persistent_context=True,
                user_data_dir=str(PROFILE_DIR), window=(1440, 900))
    fp = _stable_fingerprint()
    if fp is not None:
        opts["fingerprint"] = fp
    else:
        opts["os"] = "macos"
    return AsyncCamoufox(**opts)


async def prepare_page(context):
    return context.pages[0] if context.pages else await context.new_page()


async def logged_in_youtube(page):
    try:
        cks = await page.context.cookies("https://www.youtube.com")
        return any(c["name"] in ("__Secure-1PSID", "SID") for c in cks)
    except Exception:
        return False


async def shot(page, name, enabled=True):
    if not enabled:
        return
    DEBUG_DIR.mkdir(exist_ok=True)
    try:
        await page.screenshot(path=str(DEBUG_DIR / f"{name}.png"), full_page=False)
        log(f"  screenshot -> debug/{name}.png")
    except Exception as e:
        log(f"  (screenshot {name} failed: {e})")

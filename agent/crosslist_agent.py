"""VINTED.BOT local agent: publishes on Subito and Facebook Marketplace from your PC.

Usage:
  python crosslist_agent.py setup --server https://your-bot.example.com --token <token from Settings>
  python crosslist_agent.py login          # log into Subito and Facebook once, in the agent's browser
  python crosslist_agent.py run            # wait for jobs and execute them

The agent asks the bot for jobs every few seconds, opens the listing form in its
own Chrome profile (where you are logged in), fills it in and publishes. If a step
cannot be done automatically it shows a yellow banner and waits for you.
"""
import argparse
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

import sites

HOME = Path.home() / ".vintedbot-agent"
CONFIG = HOME / "config.json"
PROFILE = HOME / "profile"

log = logging.getLogger("agent")


def load_config() -> dict:
    if not CONFIG.exists():
        sys.exit("Configura prima l'agente: python crosslist_agent.py setup --server URL --token TOKEN")
    return json.loads(CONFIG.read_text())


async def open_browser(pw, headless: bool):
    PROFILE.mkdir(parents=True, exist_ok=True)
    kwargs = dict(headless=headless, slow_mo=80, viewport=None, locale="it-IT",
                  args=["--start-maximized"])
    try:
        # The real Chrome install behaves exactly like the browser you use every day.
        return await pw.chromium.launch_persistent_context(str(PROFILE), channel="chrome", **kwargs)
    except Exception:
        return await pw.chromium.launch_persistent_context(str(PROFILE), **kwargs)


class Api:
    def __init__(self, server: str, token: str):
        self.server = server.rstrip("/")
        self.http = httpx.AsyncClient(timeout=60, headers={"X-Agent-Token": token})

    async def claim(self):
        r = await self.http.post(f"{self.server}/api/crosslist/agent/jobs/claim")
        if r.status_code == 401:
            sys.exit("Token agente non valido: generane uno nuovo in Settings → Agente PC")
        r.raise_for_status()
        return r.json().get("job")

    async def result(self, job_id: str, success: bool, url: str = "", error: str = ""):
        r = await self.http.post(f"{self.server}/api/crosslist/agent/jobs/{job_id}/result",
                                 json={"success": success, "url": url, "error": error[:500]})
        r.raise_for_status()

    async def download(self, paths, folder: Path):
        files = []
        for i, p in enumerate(paths):
            r = await self.http.get(f"{self.server}{p}")
            r.raise_for_status()
            f = folder / f"{i:02d}{Path(p).suffix}"
            f.write_bytes(r.content)
            files.append(str(f))
        return files


async def execute(job: dict, page, api: Api, human_timeout: int) -> None:
    listing = job["listing"]
    platform, action = job["platform"], job["action"]
    log.info("→ %s %s: %s", action, platform, listing["title"])
    try:
        if action == "publish":
            with tempfile.TemporaryDirectory() as tmp:
                photos = await api.download(listing["photo_paths"], Path(tmp))
                if platform == "subito":
                    url = await sites.subito_publish(page, listing, photos, human_timeout)
                else:
                    url = await sites.facebook_publish(page, listing, photos, human_timeout)
            await api.result(job["id"], True, url=url)
            log.info("✓ pubblicato su %s %s", platform, url)
        else:
            if platform == "subito":
                await sites.subito_delete(page, job["url"], human_timeout)
            else:
                await sites.facebook_delete(page, job["url"], listing["title"], human_timeout)
            await api.result(job["id"], True)
            log.info("✓ rimosso da %s", platform)
    except Exception as e:
        log.warning("✗ %s %s: %s", action, platform, e)
        await api.result(job["id"], False, error=str(e) or e.__class__.__name__)


async def run(args) -> None:
    cfg = load_config()
    api = Api(cfg["server"], cfg["token"])
    async with async_playwright() as pw:
        ctx = await open_browser(pw, args.headless)
        ctx.set_default_timeout(15000)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        log.info("Agente avviato, in attesa di annunci da pubblicare (Ctrl+C per uscire)")
        while True:
            try:
                job = await api.claim()
            except httpx.HTTPError as e:
                log.warning("server non raggiungibile: %s", e)
                job = None
            if job:
                await execute(job, page, api, args.human_timeout)
                continue
            if args.once:
                break
            await asyncio.sleep(args.interval)
        await ctx.close()


async def login(args) -> None:
    async with async_playwright() as pw:
        ctx = await open_browser(pw, headless=False)
        p1 = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await p1.goto("https://www.subito.it/")
        p2 = await ctx.new_page()
        await p2.goto("https://www.facebook.com/marketplace/")
        print("Accedi a Subito e Facebook nelle due schede, poi torna qui e premi Invio.")
        await asyncio.get_event_loop().run_in_executor(None, input)
        await ctx.close()
    print("Login salvati nel profilo dell'agente.")


def setup(args) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({"server": args.server.rstrip("/"), "token": args.token}))
    CONFIG.chmod(0o600)
    print(f"Configurazione salvata in {CONFIG}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--server", required=True)
    s.add_argument("--token", required=True)
    sub.add_parser("login")
    r = sub.add_parser("run")
    r.add_argument("--interval", type=float, default=10, help="secondi tra un controllo e l'altro")
    r.add_argument("--human-timeout", type=int, default=600,
                   help="secondi di attesa quando serve il tuo intervento (0 = non aspettare)")
    r.add_argument("--headless", action="store_true", help="browser invisibile (sconsigliato)")
    r.add_argument("--once", action="store_true", help="esegue i lavori in coda e termina")
    args = ap.parse_args()
    if args.cmd == "setup":
        setup(args)
    elif args.cmd == "login":
        asyncio.run(login(args))
    else:
        try:
            asyncio.run(run(args))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

"""Play every guided tour in the built docs demos and check their layout in a real browser.

Usage: `just docs-demos`, which builds the site and runs this against it.

At a phone and a desktop viewport, every demo page is checked on load, at every tour stop and
after each run: the page must not scroll sideways, the coach card must sit fully on screen, the
tour must reach every stop it announces, and the page must raise no errors.
"""

import asyncio
import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.async_api import Browser, Locator, Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


VIEWPORTS = {"phone": {"width": 375, "height": 740}, "desktop": {"width": 1280, "height": 800}}
STOP_TIMEOUT_MS = 20_000

MEASURE_JS = """(coach) => {
  const de = document.documentElement;
  const out = { scrollWidth: de.scrollWidth, clientWidth: de.clientWidth };
  if (coach) {
    const r = coach.getBoundingClientRect();
    out.coach = [r.left, r.top, r.right, r.bottom].map(Math.round);
    out.viewport = [innerWidth, innerHeight];
  }
  return out;
}"""

SETTLE_JS = """(el) => new Promise((resolve) => {
  let last = '', same = 0, frames = 0;
  const tick = () => {
    const r = el.getBoundingClientRect();
    const key = [r.left, r.top, scrollY].map(Math.round).join();
    same = key === last ? same + 1 : 0;
    last = key;
    if (same >= 5 || ++frames > 180) resolve(); else requestAnimationFrame(tick);
  };
  tick();
})"""


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def _serve(site: Path) -> http.server.ThreadingHTTPServer:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_QuietHandler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def _measure(page: Page, coach: Locator | None, where: str) -> list[str]:
    handle = await coach.element_handle() if coach else None
    m = await page.evaluate(MEASURE_JS, handle)
    problems = []
    if m["scrollWidth"] > m["clientWidth"]:
        problems.append(f"{where}: page scrolls sideways (scrollWidth {m['scrollWidth']} > {m['clientWidth']})")
    if coach:
        left, top, right, bottom = m["coach"]
        width, height = m["viewport"]
        if left < 0 or top < 0 or right > width or bottom > height:
            problems.append(f"{where}: coach at {m['coach']} is not inside the {width}x{height} viewport")
    return problems


async def _play_tour(page: Page, demo: str, play: str, where: str) -> list[str]:
    coach = page.locator(f"{demo} .coach")
    problems: list[str] = []
    seen, total = 0, None
    await page.click(play)
    while total is None or seen < total:
        try:
            await page.locator(f"{demo} .coach.show").wait_for(timeout=STOP_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            break
        seen += 1
        step = await coach.locator(".step").inner_text()
        total = int(step.rsplit(" ", 1)[1])
        await coach.evaluate(SETTLE_JS)
        problems += await _measure(page, coach, f"{where} stop {seen}/{total}")
        await coach.locator(".go").dispatch_event("click")
    if total is None or seen < total:
        problems.append(f"{where}: tour stalled after {seen} of {total or '?'} stops")
    await page.wait_for_timeout(500)
    problems += await _measure(page, None, f"{where} after the run")
    return problems


async def _check_page(browser: Browser, base: str, name: str, viewport: str) -> list[str]:
    context = await browser.new_context(viewport=VIEWPORTS[viewport])
    page = await context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    await page.goto(f"{base}/demos/{name}/")
    await page.wait_for_selector(".hw-demo .play, .hw-demo [data-el=hplay]")
    where = f"{name} @ {viewport}"
    problems = await _measure(page, None, f"{where} on load")
    for demo_id in await page.eval_on_selector_all(".hw-demo[id]", "els => els.map(e => e.id)"):
        demo = f"#{demo_id}"
        if await page.locator(f"{demo} [data-el=hplay]").count():
            problems += await _play_tour(page, demo, f"{demo} [data-el=hplay]", f"{where} {demo}")
            continue
        buttons = page.locator(f"{demo} .scenario-btn")
        for i in range(await buttons.count()):
            await buttons.nth(i).click()
            label = await buttons.nth(i).inner_text()
            problems += await _play_tour(page, demo, f"{demo} [data-el=play]", f"{where} {demo} '{label}'")
    problems += [f"{where}: page error: {e}" for e in errors]
    await context.close()
    return problems


def _demo_pages(site: Path) -> list[str]:
    return sorted(p.parent.name for p in site.glob("demos/*/index.html") if 'class="hw-demo"' in p.read_text())


async def _main(site: Path, pages: list[str]) -> int:
    server = _serve(site)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        jobs = [(n, v) for n in pages for v in VIEWPORTS]
        results = await asyncio.gather(*(_check_page(browser, base, n, v) for n, v in jobs), return_exceptions=True)
        await browser.close()
    server.shutdown()
    problems = []
    for (name, viewport), result in zip(jobs, results, strict=True):
        if isinstance(result, BaseException):
            problems.append(f"{name} @ {viewport}: check crashed: {str(result).splitlines()[0]}")
        else:
            problems += result
    for problem in problems:
        sys.stdout.write(f"FAIL {problem}\n")
    sys.stdout.write(f"{len(pages)} pages x {len(VIEWPORTS)} viewports checked, {len(problems)} problems\n")
    return 1 if problems or not pages else 0


if __name__ == "__main__":
    site = Path(sys.argv[1])
    sys.exit(asyncio.run(_main(site, _demo_pages(site))))

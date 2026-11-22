"""The browser of the browser tests, and what they leave behind when a test fails (the CI uploads it).

LCA_WRENCH_BROWSER: chrome (default, the installed Google Chrome), chromium (Playwright's own) or webkit (the
engine of Safari; `python -m playwright install webkit`).
LCA_WRENCH_CHROME=<path>: a Chromium at this path, e.g. on Linux without Google Chrome.
LCA_WRENCH_ARTIFACTS=<folder>: each browser window records a Playwright trace and a video; when a test in it failed,
they are kept there with a screenshot of each page (open a trace with `python -m playwright show-trace <file>`).
"""

import os
import re
from pathlib import Path


def artifacts() -> Path | None:
    out = os.environ.get("LCA_WRENCH_ARTIFACTS")
    if not out:
        return None
    Path(out).mkdir(parents=True, exist_ok=True)
    return Path(out)


def launch(p):
    kind = os.environ.get("LCA_WRENCH_BROWSER", "chrome")
    if kind == "webkit":
        return p.webkit.launch()
    chrome = os.environ.get("LCA_WRENCH_CHROME")
    if chrome:
        return p.chromium.launch(executable_path=chrome)
    return p.chromium.launch() if kind == "chromium" else p.chromium.launch(channel="chrome")


def new_context(browser, name: str, **options):
    """A browser window (context) that records what happened, if LCA_WRENCH_ARTIFACTS is set."""
    out = artifacts()
    name = re.sub(r"[^\w.-]+", "_", name).strip("_")
    if out:
        options["record_video_dir"] = str(out / "videos")
    ctx = browser.new_context(**options)
    ctx.lca_name = name
    if out:
        ctx.tracing.start(screenshots=True, snapshots=True)
    return ctx


def finish(ctx, failed: bool) -> None:
    """Close the window; after a failure keep its trace, video and a screenshot of each page."""
    out = artifacts()
    if not out:
        ctx.close()
        return
    if failed:
        for i, page in enumerate(ctx.pages):
            try:
                page.screenshot(path=str(out / f"{ctx.lca_name}-{i}.png"), full_page=True)
            except Exception:  # a page that crashed: the trace still shows it
                pass
        ctx.tracing.stop(path=str(out / f"{ctx.lca_name}-trace.zip"))
    else:
        ctx.tracing.stop()
    videos = [page.video for page in ctx.pages if page.video]
    ctx.close()  # the video files are complete only now
    for i, video in enumerate(videos):
        if failed:
            video.save_as(str(out / f"{ctx.lca_name}-{i}.webm"))
        video.delete()

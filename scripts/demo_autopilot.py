"""Demo autopilot (SPEC §14.4): drives the running app through Flows 1–3 and the Evidence Center,
records a 1920×1080 video with captions, and saves the named screenshots used by the docs and deck.

Prerequisites (dev only, not in the Docker image):
  pip install playwright==1.48.0 && python -m playwright install chromium
  the app running at --base-url (e.g. `docker compose up` or `make serve`)

Usage:
  python scripts/demo_autopilot.py [--base-url http://localhost:8000] [--headed] [--pace 1.0] [--no-video]

Outputs: evidence/video/bridge_demo.webm (+ .mp4 if ffmpeg is installed), evidence/screenshots/NN_*.png,
copied to docs/img/. It waits on cards, not fixed timeouts, so real-LLM latency does not break it.
The submitted video must be recorded with a real LLM; the model badge is visible in every frame.
"""
from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
EVIDENCE = ROOT / "evidence"
SHOTS = EVIDENCE / "screenshots"
VIDEO = EVIDENCE / "video"
DOCS_IMG = ROOT / "docs" / "img"
LONG = 180_000  # ms; generous for real-LLM latency
FF_SPEED = 4         # agent-waiting stretches are sped up this much in the edited video (badge shown on screen)
TYPE_DELAY_MS = 75   # per Latin character, multiplied by --pace
CJK_FACTOR = 2.6     # Chinese characters are typed slower so viewers can read them
TYPE_HOLD_S = 1.6    # seconds the finished message stays in the box before sending (× pace)


FF_BADGE_JS = """on => {
  let b = document.getElementById('ff-badge');
  if (!on) { if (b) b.remove(); return; }
  if (!b) {
    b = document.createElement('div');
    b.id = 'ff-badge';
    b.textContent = '⏩ Agent working — sped up %dx';
    b.style.cssText = 'position:fixed;top:96px;left:50%%;transform:translateX(-50%%);z-index:9999;' +
      'background:#16202e;color:#f6f3ec;padding:10px 22px;border-radius:999px;font:600 20px "IBM Plex Sans",sans-serif;' +
      'box-shadow:0 8px 24px rgba(0,0,0,.25)';
    document.body.appendChild(b);
  }
}""" % (FF_SPEED, )


class Autopilot:
    def __init__(self, page, base: str, pace: float):
        self.page = page
        self.base = base.rstrip("/")
        self.pace = pace
        self.t0 = time.monotonic()  # the video starts when the page is created
        self.segments: list[tuple[float, float]] = []  # agent waiting time, sped up in the edit

    @contextmanager
    def fast_forward(self):
        """Mark a stretch where the viewer only waits for the model; it is sped up FF_SPEED× in the edit,
        and a visible badge says so."""
        self.page.evaluate(FF_BADGE_JS, True)
        start = time.monotonic() - self.t0
        try:
            yield
        finally:
            end = time.monotonic() - self.t0
            self.page.evaluate(FF_BADGE_JS, False)
            if end - start >= 2.0:
                self.segments.append((start + 0.2, end - 0.1))

    # ------------------------------------------------------------------ primitives
    def tid(self, name: str):
        return self.page.locator(f'[data-testid="{name}"]')

    def caption(self, text: str, seconds: float = 2.8) -> None:
        print(f"  ▸ {text}")
        self.page.evaluate("t => window.__demoCaption && window.__demoCaption(t)", text)
        self.page.wait_for_timeout(int(seconds * 1000 * self.pace))

    def pause(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000 * self.pace))

    def shot(self, name: str) -> None:
        SHOTS.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(SHOTS / f"{name}.png"))

    def count(self, testid: str) -> int:
        return self.tid(testid).count()

    def wait_more(self, testid: str, before: int) -> None:
        self.page.wait_for_function(
            "([sel, n]) => document.querySelectorAll(sel).length > n",
            arg=[f'[data-testid="{testid}"]', before], timeout=LONG)

    def focus(self, locator) -> None:
        locator.evaluate("e => e.scrollIntoView({behavior: 'smooth', block: 'center'})")
        self.pause(0.8)

    def consent_if_asked(self) -> None:
        try:
            self.tid("consent-accept").wait_for(state="visible", timeout=2500)
            self.pause(0.6)
            self.tid("consent-accept").click()
        except Exception:
            pass

    def type_readably(self, text: str) -> None:
        """Type at a pace a viewer can follow (Chinese characters slower), then hold before sending."""
        box = self.tid("chat-input")
        box.click()
        per_char = TYPE_DELAY_MS * self.pace
        for ch in text:
            box.press_sequentially(ch)
            cp = ord(ch)
            cjk = 0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF
            self.page.wait_for_timeout(int(per_char * (CJK_FACTOR if cjk else 1)))
        self.pause(TYPE_HOLD_S)  # the full message stays on screen before it is sent

    def ask(self, text: str, upload: str | None = None, wait_for: str = "card-intent") -> None:
        """Type a message (and optionally upload a sample with it), then wait for a new card."""
        before = self.count(wait_for)
        self.type_readably(text)
        if upload:
            self.tid("upload-input").set_input_files(str(SAMPLES / upload))
        else:
            self.tid("chat-send").click()
        self.pause(0.8)  # the sent message and the "checking…" bubble appear at normal speed
        with self.fast_forward():
            self.wait_more(wait_for, before)
        self.pause(0.6)

    def persona(self, which: str) -> None:
        self.tid(f"persona-{which}").click()
        self.consent_if_asked()
        self.pause(0.5)

    # ------------------------------------------------------------------ script (SPEC §14.5)
    def run(self) -> None:
        p = self.page
        p.goto(f"{self.base}/intro?demo=1")
        self.tid("intro").wait_for()
        self.caption("Families lose tuition to payment scams and quota mistakes. Bridge pays tuition safely — rules are enforced by code, not by the AI.", 5.5)
        self.shot("01_intro")

        p.goto(f"{self.base}/?demo=1")
        self.consent_if_asked()
        self.caption("Sandbox: fictional university, simulated money. Model shown top-right.", 3.2)

        # Flow 1 — pay tuition
        self.ask("请帮我付这张学费账单。", upload="northbridge_invoice_autumn.pdf", wait_for="card-intent")
        self.focus(self.tid("card-zh-summary").last)
        self.caption("English invoice → Chinese summary")
        self.shot("02_zh_summary")
        self.focus(self.tid("card-payee-check").last)
        self.caption("Payee verified against the registry")
        self.shot("03_payee_verified")
        self.focus(self.tid("card-quota").last)
        self.caption("Mother's personal FX quota")
        self.shot("04_quota")
        self.focus(self.tid("intent-review").last)
        self.tid("intent-review").last.click()
        self.tid("approval-modal").wait_for()
        self.caption("Approval bound to a transaction fingerprint", 3.2)
        self.shot("05_approval_fingerprint")
        self.tid("approve-button").click()
        self.tid("approval-waiting").wait_for(timeout=LONG)
        self.pause(1.6)
        self.tid("approval-close").click()

        self.persona("student")
        self.tid("intent-review").last.wait_for()
        self.tid("intent-review").last.click()
        self.tid("approval-modal").wait_for()
        self.caption("Li Wei confirms the same fingerprint", 3.2)
        self.shot("06_student_confirm")
        before = self.count("card-receipt")
        self.tid("approve-button").click()
        with self.fast_forward():
            self.wait_more("card-receipt", before)
        self.focus(self.tid("card-receipt").last)
        self.caption("Paid in sandbox — receipt + log")
        self.shot("07_receipt")
        self.persona("mother")

        # Flow 2 — attacks
        self.ask("这个可以付吗？", upload="agency_wechat_message.txt", wait_for="card-email-draft")
        self.focus(self.tid("card-refusal").last)
        self.caption("Agency offers 20% off via a personal account → blocked (T4-001)", 3.4)
        self.shot("08_agency_blocked")
        self.focus(self.tid("card-email-draft").last)
        self.caption("Agent drafts a check with the university's official address", 3.2)
        before = self.count("hidden-text")
        self.ask("Can I pay this?", upload="northbridge_invoice_hidden.pdf", wait_for="card-payee-check")
        self.page.wait_for_function("n => document.querySelectorAll('[data-testid=hidden-text]').length > n", arg=before, timeout=LONG)
        self.focus(self.tid("hidden-text").last)
        self.caption("Invoice hides white text → revealed and blocked (T4-006)", 3.6)
        self.shot("09_hidden_text_revealed")

        # Flow 3 — autonomy and a helpful refusal
        self.tid("nav-evidence").click()
        self.tid("tab-controls").click()
        self.tid("advance-clock").wait_for()
        self.pause(0.8)
        self.tid("advance-clock").click()
        self.tid("advance-result").wait_for(timeout=LONG)
        self.caption("Monthly allowance: autonomous, inside limits (T2)", 3.0)
        self.tid("nav-chat").click()
        self.tid("card-receipt").last.wait_for()
        self.focus(self.tid("card-receipt").last)
        self.shot("10_allowance_auto")
        self.ask("Send Li Wei an extra £2,000 now.", wait_for="card-intent")
        self.focus(self.tid("card-intent").last)
        self.caption("Above the cap → needs approval")
        self.shot("11_held_above_cap")
        self.ask("Please pay the accommodation invoice.", upload="northbridge_invoice_accommodation.pdf", wait_for="card-checklist")
        self.focus(self.tid("card-quota").last)
        self.caption("Accommodation invoice exceeds her remaining personal quota", 3.0)
        before = self.count("card-refusal")
        self.ask("用我哥哥的额度付吧", wait_for="card-refusal")
        self.focus(self.tid("card-refusal").last)
        self.caption("'Use my brother's quota' → refused (T4-003), lawful route offered", 3.6)
        self.shot("12_quota_refusal")
        self.tid("card-intent").first.locator("button", has_text="Why?").click()
        self.pause(1.0)
        self.caption("Why panel: every rule check, with its source", 3.0)
        self.shot("13_why_panel")

        # Evidence Center
        self.tid("nav-evidence").click()
        self.tid("tab-audit").click()
        self.tid("verify-chain").wait_for()
        self.pause(0.6)
        self.tid("verify-chain").click()
        self.tid("verify-result").wait_for()
        self.caption("Every step is hash-chained → Verify ✅")
        self.shot("14_chain_valid")
        self.tid("tamper-sim").click()
        self.tid("tamper-result").wait_for()
        self.caption("Tampering is detected ⛔ (on a copy)")
        self.shot("15_tamper_detected")
        self.tid("tab-scenarios").click()
        try:
            self.tid("scenario-summary").wait_for(timeout=4000)
        except Exception:
            self.tid("scenario-run").click()
            self.tid("scenario-summary").wait_for(timeout=LONG)
        rate = self.tid("scenario-summary").inner_text().split("%")[0].strip()
        self.caption(f"Scenario suite: {rate}% pass rate", 3.0)
        self.shot("16_scenario_results")
        self.tid("tab-rules").click()
        self.tid("rules-table").wait_for()
        self.caption("Every rule has a source")
        self.shot("17_rules_sources")
        self.tid("tab-export").click()
        self.tid("export-pack").wait_for()
        with p.expect_download(timeout=LONG) as dl:
            self.tid("export-pack").click()
        (EVIDENCE / "tmp").mkdir(parents=True, exist_ok=True)
        dl.value.save_as(str(EVIDENCE / "tmp" / "pack_during_recording.zip"))  # final pack is fetched after the video is saved
        self.caption("One-click evidence pack")

        p.goto(f"{self.base}/outro?demo=1")
        self.tid("outro").wait_for()
        self.caption("AI proposes. Policy engine decides. Humans approve.", 5.0)
        self.shot("18_outro")


def reset(base: str) -> dict:
    req = urllib.request.Request(f"{base.rstrip('/')}/api/demo/reset", method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        json.loads(r.read())
    with urllib.request.urlopen(f"{base.rstrip('/')}/api/health", timeout=10) as r:
        return json.loads(r.read())


def to_mp4(webm: Path, segments: list[tuple[float, float]] | None = None) -> Path | None:
    """Encode to MP4. Marked agent-waiting segments are sped up FF_SPEED× (the badge is in those frames);
    everything else plays at normal speed. The unedited recording is kept as the .webm."""
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found — keeping the .webm only")
        return None
    mp4 = webm.with_suffix(".mp4")
    total = video_seconds(webm) or 0
    parts, cursor = [], 0.0
    for s, e in sorted(segments or []):
        s, e = max(s, cursor), min(e, total or e)
        if e - s < 1.0:
            continue
        parts.append((cursor, s, 1))
        parts.append((s, e, FF_SPEED))
        cursor = e
    parts.append((cursor, None, 1))
    chains, labels = [], []
    for i, (s, e, speed) in enumerate(parts):
        trim = f"trim=start={s:.3f}" + (f":end={e:.3f}" if e is not None else "")
        chains.append(f"[0:v]{trim},setpts=(PTS-STARTPTS)/{speed}[v{i}]")
        labels.append(f"[v{i}]")
    graph = ";".join(chains) + f";{''.join(labels)}concat=n={len(parts)}:v=1:a=0,fps=25[out]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-filter_complex", graph, "-map", "[out]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24", "-movflags", "+faststart", str(mp4)], check=True)
    return mp4


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--pace", type=float, default=1.0, help="multiply caption and pause durations")
    ap.add_argument("--slow-mo", type=int, default=60)
    ap.add_argument("--no-video", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed: pip install playwright==1.48.0 && python -m playwright install chromium")
        return 2

    health = reset(args.base_url)
    print(f"Sandbox reset. Model: {health['model_label']}")
    if health["model_label"].startswith("MOCK"):
        print("Note: recording with the MOCK model. The submitted video must use a real LLM (set LLM_PROVIDER in .env).")
    for d in (SHOTS, VIDEO):
        d.mkdir(parents=True, exist_ok=True)
    for old in list(SHOTS.glob("*.png")) + list(VIDEO.glob("*.webm")) + list(VIDEO.glob("*.mp4")):
        old.unlink()

    started = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed, slow_mo=args.slow_mo)
        ctx_args = {"viewport": {"width": 1920, "height": 1080}, "device_scale_factor": 1, "accept_downloads": True,
                    "locale": "en-GB"}
        if not args.no_video:
            ctx_args.update(record_video_dir=str(VIDEO), record_video_size={"width": 1920, "height": 1080})
        context = browser.new_context(**ctx_args)
        page = context.new_page()
        pilot = Autopilot(page, args.base_url, args.pace)
        try:
            pilot.run()
        finally:
            video = page.video
            context.close()
            browser.close()
        if video and not args.no_video:
            raw = Path(video.path())
            webm = VIDEO / "bridge_demo_unedited.webm"
            raw.replace(webm)
            waited = sum(e - s for s, e in pilot.segments)
            print(f"Agent waiting time: {waited:.0f}s in {len(pilot.segments)} stretches (sped up {FF_SPEED}x in the MP4)")
            mp4 = to_mp4(webm, pilot.segments)
            if mp4:
                mp4.replace(VIDEO / "bridge_demo.mp4")
                mp4 = VIDEO / "bridge_demo.mp4"
            print(f"Video: {mp4 or webm} (unedited recording: {webm})")

    DOCS_IMG.mkdir(parents=True, exist_ok=True)
    for png in sorted(SHOTS.glob("*.png")):
        shutil.copy2(png, DOCS_IMG / png.name)
    print(f"{len(list(SHOTS.glob('*.png')))} screenshots → {SHOTS} (copied to {DOCS_IMG}); "
          f"run time {time.time() - started:.0f}s")
    duration = video_seconds(VIDEO / "bridge_demo.mp4") or video_seconds(VIDEO / "bridge_demo_unedited.webm")
    if duration:
        print(f"Video length {int(duration // 60)}:{int(duration % 60):02d}" + ("  (over the 5:00 limit!)" if duration > 300 else ""))
    pack = save_pack(args.base_url)
    print(f"Evidence pack of this recorded run: {pack}")
    return 0


def video_seconds(path: Path) -> float | None:
    if not path.exists() or not shutil.which("ffprobe"):
        return None
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def save_pack(base: str) -> Path:
    """Export the evidence pack of the session just recorded (its audit log, receipts, the new video)."""
    with urllib.request.urlopen(f"{base.rstrip('/')}/api/evidence/export", timeout=120) as r:
        data = r.read()
    path = EVIDENCE / f"pack_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    path.write_bytes(data)
    return path


if __name__ == "__main__":
    raise SystemExit(main())

"""
NotebookLMProducer — generates podcast audio via Google NotebookLM Audio Overview.

Flow:
1. Load Google auth cookies from GOOGLE_COOKIES env var
2. Open NotebookLM, create a new notebook
3. Paste research + script as a text source
4. Customize Audio Overview with podcast-specific instructions
5. Wait for generation (3-8 min typically)
6. Download the audio file
7. Convert to MP3 and return path

Auth: requires GOOGLE_COOKIES env var (JSON array of cookie objects).
      Run extract_google_cookies.py locally to generate it.
"""

import os
import json
import time
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

GENERATION_TIMEOUT = 600  # 10 minutes max

INSTRUCTIONS_TEMPLATE = """\
Make this a {length_min}-{length_max} minute podcast episode between two hosts: Alex (confident, sharp, male) and Sarah (curious, warm, female).

Rules:
- Open with the single most shocking fact or statistic — no "Welcome to..." intro
- Hosts speak like smart friends, not news anchors
- Sarah reacts with genuine surprise: "Wait, seriously?", "That's insane.", "No way."
- Alex delivers heavy facts with weight; lighter on wit
- Short punchy exchanges, not long monologues
- Include specific numbers, names, and dates from the sources
- Build to the most surprising twist the audience didn't see coming
- End with a punchy one-liner takeaway

Topic: {topic}
"""


class NotebookLMProducer:
    def __init__(self, channel):
        self.channel = channel
        self._cookies = self._load_cookies()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def produce(self, script: str, research: dict, topic: str, episode_dir: Path) -> str:
        """Generate podcast audio via NotebookLM. Returns path to MP3."""
        from playwright.sync_api import sync_playwright

        episode_dir = Path(episode_dir)
        dl_dir = episode_dir / "notebooklm"
        dl_dir.mkdir(exist_ok=True)

        length_min = self.channel.get("episode_length_min", 7)
        source_text = self._build_source(topic, research, script)
        instructions = INSTRUCTIONS_TEMPLATE.format(
            length_min=length_min,
            length_max=length_min + 3,
            topic=topic,
        ).strip()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                accept_downloads=True,
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            context.add_cookies(self._cookies)
            page = context.new_page()
            try:
                mp3_path = self._automate(page, source_text, instructions, topic, dl_dir)
            finally:
                browser.close()

        return mp3_path

    # ------------------------------------------------------------------
    # Cookie loading
    # ------------------------------------------------------------------

    def _load_cookies(self):
        raw = os.environ.get("GOOGLE_COOKIES", "")
        if not raw:
            raise EnvironmentError(
                "GOOGLE_COOKIES secret not set. "
                "Run extract_google_cookies.py locally and add the output as a GitHub secret."
            )
        try:
            cookies = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"GOOGLE_COOKIES is not valid JSON: {e}")
        # Ensure required fields for Playwright
        cleaned = []
        for c in cookies:
            if not c.get("name") or not c.get("value"):
                continue
            cleaned.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".google.com"),
                "path": c.get("path", "/"),
                "secure": c.get("secure", True),
                "httpOnly": c.get("httpOnly", False),
                "sameSite": c.get("sameSite", "None"),
            })
        return cleaned

    # ------------------------------------------------------------------
    # Source building
    # ------------------------------------------------------------------

    def _build_source(self, topic: str, research: dict, script: str) -> str:
        parts = [f"TOPIC: {topic}\n"]

        claims = research.get("claims", [])
        if claims:
            parts.append("KEY FACTS FROM RESEARCH:")
            for c in claims[:40]:
                if isinstance(c, dict):
                    text = c.get("claim", c.get("text", ""))
                    src = c.get("source", "")
                    parts.append(f"- {text}" + (f"  [Source: {src}]" if src else ""))
                else:
                    parts.append(f"- {c}")

        parts.append("\nSCRIPT STRUCTURE (follow this flow):")
        parts.append(script[:4000])

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Playwright automation
    # ------------------------------------------------------------------

    def _automate(self, page, source_text: str, instructions: str, topic: str, dl_dir: Path) -> str:
        logger.info("NotebookLM: navigating to home page")
        page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        if "accounts.google.com" in page.url or "signin" in page.url.lower():
            raise PermissionError(
                "NotebookLM: Google auth failed — GOOGLE_COOKIES is expired. "
                "Re-run extract_google_cookies.py and update the GitHub secret."
            )

        logger.info("NotebookLM: creating notebook")
        self._create_notebook(page)

        logger.info("NotebookLM: adding source")
        self._add_text_source(page, source_text, topic)

        logger.info("NotebookLM: triggering audio generation")
        self._start_audio_generation(page, instructions)

        logger.info("NotebookLM: waiting for audio to finish generating...")
        audio_path = self._wait_and_download(page, dl_dir)

        return audio_path

    def _create_notebook(self, page):
        created = self._try_click(page, [
            'button:has-text("New notebook")',
            '[aria-label="New notebook"]',
            'button:has-text("Create new")',
            'button:has-text("new notebook")',
            '[data-testid="new-notebook"]',
        ], timeout=8000)
        if not created:
            raise RuntimeError(
                "Could not find 'New notebook' button — NotebookLM UI may have changed. "
                "Screenshot the page and file an issue."
            )
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(3)

    def _add_text_source(self, page, source_text: str, topic: str):
        # Open add source dialog
        self._try_click(page, [
            'button:has-text("Add source")',
            '[aria-label="Add source"]',
            'button[aria-label*="add" i]',
            'button:has-text("Add")',
        ], timeout=8000)
        time.sleep(2)

        # Choose "Copied text" or "Paste text" option
        self._try_click(page, [
            'button:has-text("Copied text")',
            'div:has-text("Copied text")',
            '[aria-label="Copied text"]',
            'button:has-text("Paste text")',
            'li:has-text("Copied text")',
        ], timeout=5000)
        time.sleep(2)

        # Fill title if present
        try:
            title_el = page.locator(
                'input[placeholder*="title" i], input[aria-label*="title" i]'
            ).first
            if title_el.is_visible(timeout=2000):
                title_el.fill(f"Research: {topic[:60]}")
        except Exception:
            pass

        # Fill the text content
        filled = False
        for sel in ['textarea[placeholder*="paste" i]', 'textarea[placeholder*="text" i]',
                    'textarea[aria-label*="source" i]', 'textarea']:
            try:
                el = page.locator(sel).last
                if el.is_visible(timeout=2000):
                    el.fill(source_text[:50000])
                    filled = True
                    break
            except Exception:
                continue

        if not filled:
            raise RuntimeError("Could not find text input area in NotebookLM add-source dialog")

        time.sleep(1)

        # Submit / Insert
        self._try_click(page, [
            'button:has-text("Insert")',
            'button:has-text("Add")',
            'button:has-text("Save")',
            '[aria-label="Insert"]',
        ], timeout=5000)

        # Wait for source to process
        logger.info("NotebookLM: waiting for source to process...")
        time.sleep(8)
        page.wait_for_load_state("networkidle", timeout=30000)

    def _start_audio_generation(self, page, instructions: str):
        time.sleep(2)

        # Open Audio Overview section / tab
        self._try_click(page, [
            'button:has-text("Audio Overview")',
            '[aria-label="Audio Overview"]',
            'div[role="tab"]:has-text("Audio")',
            'button:has-text("Audio")',
        ], timeout=8000)
        time.sleep(2)

        # Click Customize
        customized = self._try_click(page, [
            'button:has-text("Customize")',
            '[aria-label="Customize"]',
            'button:has-text("customize")',
        ], timeout=6000)

        if customized:
            time.sleep(1)
            # Fill instructions
            for sel in ['textarea[placeholder*="instruction" i]', 'textarea[placeholder*="focus" i]',
                        'textarea[aria-label*="instruction" i]', 'textarea']:
                try:
                    el = page.locator(sel).last
                    if el.is_visible(timeout=2000):
                        el.fill(instructions)
                        break
                except Exception:
                    continue
            time.sleep(1)

        # Click Generate
        generated = self._try_click(page, [
            'button:has-text("Generate")',
            '[aria-label="Generate audio"]',
            'button:has-text("Load")',
            'button:has-text("Start")',
        ], timeout=6000)

        if not generated:
            raise RuntimeError(
                "Could not find 'Generate' button for Audio Overview — "
                "NotebookLM UI may have changed."
            )

        logger.info("NotebookLM: generation started")

    def _wait_and_download(self, page, dl_dir: Path) -> str:
        download_selectors = [
            'button[aria-label*="Download" i]',
            'button:has-text("Download")',
            '[data-testid="download-audio"]',
            'a[download]',
        ]

        deadline = time.time() + GENERATION_TIMEOUT
        while time.time() < deadline:
            for sel in download_selectors:
                try:
                    if page.locator(sel).count() > 0:
                        logger.info("NotebookLM: audio ready, downloading")
                        return self._click_download(page, dl_dir, download_selectors)
                except Exception:
                    pass
            elapsed = int(time.time() - (deadline - GENERATION_TIMEOUT))
            logger.info(f"NotebookLM: still generating... ({elapsed}s elapsed)")
            time.sleep(15)

        raise TimeoutError(f"NotebookLM audio generation timed out after {GENERATION_TIMEOUT}s")

    def _click_download(self, page, dl_dir: Path, selectors: list) -> str:
        raw_path = str(dl_dir / "notebooklm_audio")
        with page.expect_download(timeout=120000) as dl_info:
            for sel in selectors:
                try:
                    if page.locator(sel).count() > 0:
                        page.click(sel, timeout=5000)
                        break
                except Exception:
                    continue
        dl = dl_info.value
        # Save with original extension
        suffix = Path(dl.suggested_filename).suffix or ".wav"
        raw_path_with_ext = raw_path + suffix
        dl.save_as(raw_path_with_ext)

        # Convert to MP3
        mp3_path = str(dl_dir / "episode.mp3")
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_path_with_ext,
            "-codec:a", "libmp3lame", "-b:a", "128k", mp3_path
        ], check=True, capture_output=True)

        return mp3_path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _try_click(self, page, selectors: list, timeout: int = 5000) -> bool:
        from playwright.sync_api import TimeoutError as PWTimeout
        for sel in selectors:
            try:
                page.click(sel, timeout=timeout)
                return True
            except (PWTimeout, Exception):
                continue
        return False

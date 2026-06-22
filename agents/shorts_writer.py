"""
ShortsWriter — extracts 2 viral Short clips from a full episode script.

Short 1: Most shocking fact or statistic
Short 2: Most surprising twist or reveal

Each Short is 20-35 seconds of dialogue (3-6 lines max).
"""

import os
import json
import logging

import anthropic

logger = logging.getLogger(__name__)


class ShortsWriter:
    def __init__(self, channel):
        self.channel = channel
        self.claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def write(self, script: str, topic: dict, n: int = 2) -> list:
        """
        Extract n viral Shorts from the episode script.
        Returns list of dicts: {hook, script, index}
        """
        host_male = self.channel.get("host_male", "Alex")
        host_female = self.channel.get("host_female", "Sarah")
        topic_title = topic.get("title", "") if isinstance(topic, dict) else str(topic)

        response = self.claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": (
                    f"You are extracting viral YouTube Shorts from a podcast episode about: {topic_title}\n\n"
                    f"FULL SCRIPT:\n{script}\n\n"
                    f"Extract {n} Shorts. Rules:\n"
                    f"- Short 1: The most shocking fact or statistic in the episode\n"
                    f"- Short 2: The most surprising twist or reveal in the episode\n"
                    f"- Each Short: 3-6 dialogue lines MAX (20-35 seconds when spoken)\n"
                    f"- Keep the exact [{host_male.upper()}]: / [{host_female.upper()}]: format\n"
                    f"- Start with the most grabbing line — no setup, no intro\n"
                    f"- End with a line that makes viewers want the full episode\n\n"
                    f"Output format (exactly):\n"
                    f"===SHORT_1===\n"
                    f"HOOK: [one-line hook for the title, max 60 chars]\n"
                    f"[dialogue lines]\n"
                    f"===SHORT_2===\n"
                    f"HOOK: [one-line hook for the title, max 60 chars]\n"
                    f"[dialogue lines]\n"
                    f"===END==="
                )
            }]
        )

        raw = response.content[0].text.strip()
        return self._parse(raw, n)

    def _parse(self, raw: str, n: int) -> list:
        shorts = []
        try:
            parts = raw.split("===SHORT_")
            for i in range(1, n + 1):
                block = None
                for part in parts:
                    if part.startswith(f"{i}==="):
                        block = part[len(f"{i}==="):].strip()
                        # cut at next marker
                        for end in [f"===SHORT_{i+1}===", "===END==="]:
                            if end in block:
                                block = block[:block.index(end)].strip()
                        break
                if not block:
                    continue

                lines = block.split("\n")
                hook = ""
                dialogue_lines = []
                for line in lines:
                    if line.startswith("HOOK:"):
                        hook = line[5:].strip()
                    elif line.strip():
                        dialogue_lines.append(line.strip())

                if dialogue_lines:
                    shorts.append({
                        "hook": hook or f"Short {i}",
                        "script": "\n".join(dialogue_lines),
                        "index": i,
                    })
        except Exception as e:
            logger.error(f"ShortsWriter parse error: {e}\nRaw:\n{raw[:500]}")

        logger.info(f"ShortsWriter: extracted {len(shorts)} shorts")
        return shorts

import os
import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)
STATE_DIR = Path("state")


class ScriptWriter:
    def __init__(self, channel):
        self.channel = channel
        self.claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def _get_recent_episodes(self, limit=5):
        """Pull recent published episode topics for continuity references."""
        if not STATE_DIR.exists():
            return []
        episodes = []
        for state_file in sorted(STATE_DIR.glob("*.json"), reverse=True)[:limit + 1]:
            try:
                state = json.loads(state_file.read_text())
                if state.get("stage") == "published" and state.get("topic"):
                    date = state.get("episode_id", "").replace("news_daily-", "")
                    episodes.append({
                        "date": date,
                        "title": state["topic"].get("title", ""),
                        "youtube_url": state.get("youtube_url", "")
                    })
            except Exception:
                continue
        return episodes[:limit]

    def write(self, topic, research):
        length_min = self.channel.get("episode_length_min", 7)
        word_count = length_min * 150
        channel_name = self.channel.get("name", "The News Pod")
        host_male = self.channel.get("host_male", "Alex")
        host_female = self.channel.get("host_female", "Sarah")

        claims_text = "\n".join([
            f"- [{c['confidence']}] {c['claim']} (source: {c['source_url']})"
            for c in research["claims"]
        ])

        sources_text = "\n".join([
            f"- {s['title']}: {s['url']}"
            for s in research["sources"]
        ])

        recent = self._get_recent_episodes()
        continuity_block = ""
        if recent:
            recent_str = "\n".join([f"  - {e['date']}: {e['title']}" for e in recent])
            continuity_block = (
                f"\nRecent episodes for continuity (only reference if today's story genuinely connects):\n"
                f"{recent_str}\n"
                f"If relevant, one host should say: "
                f"'If you caught our episode on [date] about [topic], this is a direct continuation...'\n"
            )

        response = self.claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": (
                    f"You are writing a script for \"{channel_name}\", a daily news podcast.\n\n"
                    f"Two hosts:\n"
                    f"- {host_male.upper()}: male, analytical, direct, occasionally skeptical. Delivers hard facts with confidence.\n"
                    f"- {host_female.upper()}: female, curious, warm, reacts with genuine surprise or concern. Brings context and follow-up.\n\n"
                    f"Write a two-host DIALOGUE script. Target: {word_count} words (~{length_min} minutes).\n\n"
                    f"Today's story: {topic['title']}\n\n"
                    f"Verified facts — use ONLY these, never invent details:\n{claims_text}\n\n"
                    f"Sources:\n{sources_text}\n"
                    f"{continuity_block}\n"
                    f"FORMATTING RULES:\n"
                    f"- Every single line must start with [{host_male.upper()}]: or [{host_female.upper()}]: — no exceptions\n"
                    f"- Cite sources naturally in speech: 'according to Reuters...', 'the BBC reports...'\n"
                    f"- Never use em dashes, bullet points, or lists in spoken dialogue\n\n"
                    f"PACING AND DELIVERY (critical — this script goes straight to TTS audio):\n"
                    f"- Write at a slightly faster-than-conversation pace: short, active sentences\n"
                    f"- Regular sentences: 8 to 14 words. Key facts: 4 to 7 words, standalone\n"
                    f"- Good pacing example: 'The number is hard to believe. Four hundred billion dollars. Erased in two days.'\n"
                    f"- For EVERY critical number, statistic, or fact: the OTHER host must echo it immediately\n"
                    f"  Example: [{host_male.upper()}]: The death toll reached twelve thousand.\n"
                    f"           [{host_female.upper()}]: Twelve thousand people. In under a week.\n"
                    f"- Never place two sentences over 18 words in a row — break them with a reaction\n"
                    f"- For key information that must land: split it into three short fragments instead of one long sentence\n\n"
                    f"ENGAGEMENT MECHANICS:\n"
                    f"- Never let one host speak more than 4 sentences without the other reacting\n"
                    f"- Every 60 to 90 seconds: drop a 'wait, what?' moment — contradiction, reversal, or surprising scale\n"
                    f"- Use open loops: tease something intriguing, then delay the payoff by 2 to 3 exchanges\n"
                    f"- Reactions must feel unscripted: 'Hold on.', 'That is actually terrifying.', 'Okay, back up a second.'\n"
                    f"- {host_female}: warm, curious, reacts emotionally to human impact, asks follow-up questions\n"
                    f"- {host_male}: analytical, delivers hard numbers, stays skeptical until forced to concede\n\n"
                    f"Structure:\n"
                    f"HOOK (30s): One host opens cold with ONE shocking fact or contradiction — no greetings, no intro\n"
                    f"INTRO (30s): Both hosts briefly introduce the story and why it matters right now\n"
                    f"STORY (4-5 min): Deep back-and-forth — background, what happened, key reactions, implications\n"
                    f"FORWARD (45s): What to watch for next, what this story could become\n"
                    f"CLOSE (30s): Wrap up cleanly, remind listeners to subscribe, sign off with energy\n\n"
                    f"Start immediately with [{host_male.upper()}]: or [{host_female.upper()}]: — no stage directions, no headers."
                )
            }]
        )

        script = response.content[0].text.strip()
        logger.info(f"Script written: {len(script.split())} words")
        return script

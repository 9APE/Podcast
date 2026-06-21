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
                    f"RULES:\n"
                    f"- Format every single line as [{host_male.upper()}]: or [{host_female.upper()}]: — no exceptions\n"
                    f"- Cite sources naturally in speech: 'according to Reuters...', 'the BBC reports...'\n"
                    f"- Never use em dashes\n"
                    f"- Create genuine back-and-forth: reactions, follow-up questions, moments of surprise\n"
                    f"- Use open loops: tease what is coming before delivering it\n"
                    f"- Land a dopamine moment every 90 seconds: a surprising stat, a contradiction, a revelation\n"
                    f"- Keep sentences short and punchy when delivering key facts\n"
                    f"- Never use bullet points or lists in spoken dialogue\n\n"
                    f"Structure:\n"
                    f"HOOK (30s): One host opens with one striking fact or provocative question — no intro yet\n"
                    f"INTRO (30s): Both hosts briefly introduce the story and why it matters today\n"
                    f"STORY (4-5 min): Deep back-and-forth — background, what happened, key reactions, implications\n"
                    f"FORWARD (45s): What to watch for next, what this story could become\n"
                    f"CLOSE (30s): Wrap up, remind listeners to follow The News Pod, sign off\n\n"
                    f"Start immediately with [{host_male.upper()}]: or [{host_female.upper()}]: — no stage directions, no headers."
                )
            }]
        )

        script = response.content[0].text.strip()
        logger.info(f"Script written: {len(script.split())} words")
        return script

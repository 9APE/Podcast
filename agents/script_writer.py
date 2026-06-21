import os
import logging

import anthropic

logger = logging.getLogger(__name__)


class ScriptWriter:
    def __init__(self, channel):
        self.channel = channel
        self.claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def write(self, topic, research):
        length_min = self.channel.get("episode_length_min", 12)
        word_count = length_min * 150
        channel_name = self.channel.get("name", "The Daily Briefing")

        claims_text = "\n".join([
            f"- [{c['confidence']}] {c['claim']} (source: {c['source_url']})"
            for c in research["claims"]
        ])

        sources_text = "\n".join([
            f"- {s['title']}: {s['url']}"
            for s in research["sources"]
        ])

        response = self.claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": (
                    f'You are the head writer for "{channel_name}", a daily AI-powered news briefing podcast.\n\n'
                    f"Write a complete podcast script for today's episode.\n"
                    f"Target: {word_count} words (~{length_min} minutes at 150 words per minute).\n\n"
                    f"Today's story: {topic['title']}\n\n"
                    f"Verified facts (use ONLY these, do not add any information not listed here):\n"
                    f"{claims_text}\n\n"
                    f"Sources:\n{sources_text}\n\n"
                    f"RULES:\n"
                    f"- Use ONLY the facts listed above. Never invent or add details.\n"
                    f"- Cite sources naturally: 'according to Reuters...', 'The BBC reports...'\n"
                    f"- Never mention confidence ratings in the script\n"
                    f"- Tone: calm, authoritative, clear. Like NPR's Up First, not sensationalist.\n"
                    f"- Write in full spoken sentences, never bullet points\n"
                    f"- Add [PAUSE 0.5s] between paragraphs\n"
                    f"- Add [PAUSE 1s] between major sections\n"
                    f"- Never use em dashes\n\n"
                    f"Structure:\n"
                    f"HOOK: One striking fact or question (30 seconds)\n"
                    f"INTRO: What this episode covers and why it matters (45 seconds)\n"
                    f"STORY: Deep coverage including background, what happened, reactions, implications (8-10 minutes)\n"
                    f"CONTEXT: How this connects to broader trends or history (1-2 minutes)\n"
                    f"OUTRO: Brief summary, what to watch next, sign-off for {channel_name} (30 seconds)\n\n"
                    f"Begin directly with the HOOK. Do not include section headers or any text not meant to be spoken aloud."
                )
            }]
        )

        script = response.content[0].text.strip()
        logger.info(f"Script written: {len(script.split())} words")
        return script

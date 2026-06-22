import os
import json
import logging
import re
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)
STATE_DIR = Path("state")

# ---------------------------------------------------------------------------
# Spoken-language post-processor
# Forces contractions and bans formal written English before TTS.
# ---------------------------------------------------------------------------
CONTRACTION_MAP = [
    (r"\bit is\b", "it's"),
    (r"\bIt is\b", "It's"),
    (r"\bIT IS\b", "IT'S"),
    (r"\bthat is\b", "that's"),
    (r"\bThat is\b", "That's"),
    (r"\bthere is\b", "there's"),
    (r"\bThere is\b", "There's"),
    (r"\bhe is\b", "he's"),
    (r"\bshe is\b", "she's"),
    (r"\bwhat is\b", "what's"),
    (r"\bWhat is\b", "What's"),
    (r"\bwho is\b", "who's"),
    (r"\bWho is\b", "Who's"),
    (r"\bwe are\b", "we're"),
    (r"\bWe are\b", "We're"),
    (r"\bthey are\b", "they're"),
    (r"\bThey are\b", "They're"),
    (r"\byou are\b", "you're"),
    (r"\bYou are\b", "You're"),
    (r"\bI am\b", "I'm"),
    (r"\bcannot\b", "can't"),
    (r"\bCannot\b", "Can't"),
    (r"\bwill not\b", "won't"),
    (r"\bWill not\b", "Won't"),
    (r"\bdo not\b", "don't"),
    (r"\bDo not\b", "Don't"),
    (r"\bdoes not\b", "doesn't"),
    (r"\bDoes not\b", "Doesn't"),
    (r"\bdid not\b", "didn't"),
    (r"\bDid not\b", "Didn't"),
    (r"\bwould not\b", "wouldn't"),
    (r"\bWould not\b", "Wouldn't"),
    (r"\bcould not\b", "couldn't"),
    (r"\bCould not\b", "Couldn't"),
    (r"\bshould not\b", "shouldn't"),
    (r"\bShould not\b", "Shouldn't"),
    (r"\bhave not\b", "haven't"),
    (r"\bhas not\b", "hasn't"),
    (r"\bhad not\b", "hadn't"),
    (r"\bI have\b", "I've"),
    (r"\bwe have\b", "we've"),
    (r"\bthey have\b", "they've"),
    (r"\byou have\b", "you've"),
    (r"\bI would\b", "I'd"),
    (r"\bI will\b", "I'll"),
    (r"\bwe will\b", "we'll"),
    (r"\bthey will\b", "they'll"),
    (r"\byou will\b", "you'll"),
    (r"\bthat will\b", "that'll"),
    (r"\blet us\b", "let's"),
    (r"\bLet us\b", "Let's"),
]


def _spoken_ize(script: str) -> str:
    """Replace formal written forms with spoken contractions throughout the script."""
    for pattern, replacement in CONTRACTION_MAP:
        script = re.sub(pattern, replacement, script)
    return script


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
                f"If relevant, one host says naturally: 'So if you heard our episode about [topic], this is basically the sequel.'\n"
            )

        response = self.claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": (
                    f"You're writing a script for \"{channel_name}\" — a daily news podcast that sounds like two smart friends\n"
                    f"genuinely reacting to the news together. Think Google NotebookLM's Audio Overview style:\n"
                    f"real reactions, interruptions, unfinished thoughts, energy that pulls you in.\n\n"
                    f"Two hosts:\n"
                    f"- {host_male.upper()}: sharp, a bit skeptical, delivers facts with confidence and dry wit.\n"
                    f"  Occasionally says 'hang on' or pushes back before coming around.\n"
                    f"- {host_female.upper()}: genuinely curious, emotionally expressive, reacts fast.\n"
                    f"  Doesn't wait for {host_male} to finish before jumping in with a reaction.\n\n"
                    f"Write a two-host DIALOGUE. Target: {word_count} words (~{length_min} minutes).\n\n"
                    f"Today's story: {topic['title']}\n\n"
                    f"Verified facts — use ONLY these:\n{claims_text}\n\n"
                    f"Sources:\n{sources_text}\n"
                    f"{continuity_block}\n"

                    f"SPOKEN LANGUAGE RULES — these are absolute, no exceptions:\n"
                    f"- ALWAYS use contractions: it's, that's, they're, we're, you're, can't, won't, don't,\n"
                    f"  doesn't, didn't, wouldn't, couldn't, I've, we've, I'd, I'll, let's\n"
                    f"- NEVER write: it is, that is, they are, we are, cannot, will not, do not, does not\n"
                    f"- Write EXACTLY how people talk, not how they write\n"
                    f"- Use filler words where natural: 'okay so', 'right', 'I mean', 'look', 'here's the thing'\n"
                    f"- Incomplete sentences are fine when interrupted: '{host_male}: And what's wild is—'\n"
                    f"  '{host_female}: —wait, stop. Say that number again.'\n\n"

                    f"FORMATTING:\n"
                    f"- Every line starts with [{host_male.upper()}]: or [{host_female.upper()}]: — no exceptions\n"
                    f"- Cite sources naturally: 'Reuters says...', 'according to the BBC...', 'the FT's reporting that...'\n"
                    f"- No em dashes mid-sentence except for interruptions. No bullet points.\n\n"

                    f"PACING (this goes straight to text-to-speech audio):\n"
                    f"- Short punchy sentences: 8-14 words normally, 4-7 words for key facts\n"
                    f"- Good rhythm example: 'The number's hard to believe. Four hundred billion. Gone in two days.'\n"
                    f"- When one host says a shocking number, the OTHER echoes it immediately:\n"
                    f"  [{host_male.upper()}]: The death toll hit twelve thousand.\n"
                    f"  [{host_female.upper()}]: Twelve thousand people. That's — okay.\n"
                    f"- Never two sentences over 18 words in a row. Break them up.\n\n"

                    f"ENERGY AND REACTIONS:\n"
                    f"- No host speaks more than 3-4 sentences before the other jumps in\n"
                    f"- Every 60-90 seconds: a genuine 'wait, what?' moment — a reversal, a contradiction, a scale that doesn't compute\n"
                    f"- {host_female} uses short raw reactions regularly: 'No.', 'Stop.', 'That's insane.', 'Okay but WHY.',\n"
                    f"  'I genuinely didn't know that.', 'Hold on hold on hold on.'\n"
                    f"- {host_male} pushes back at least once then concedes: 'okay yeah, I'll give you that'\n"
                    f"- After a concession: {host_female} escalates, doesn't stay neutral\n"
                    f"- Use open loops: tease something surprising, hold off the payoff for 2-3 exchanges\n"
                    f"- Hosts finish each other's sentences occasionally\n"
                    f"- One genuine moment of dark/dry humor is allowed if it fits the story\n\n"

                    f"STRUCTURE:\n"
                    f"HOOK (30s): One host opens cold with ONE shocking fact or contradiction. No greetings. No intro music cue.\n"
                    f"SETUP (30s): Both hosts briefly frame why this story matters RIGHT NOW\n"
                    f"STORY (4-5 min): Deep back-and-forth — what happened, key reactions, implications, surprising angles\n"
                    f"FORWARD (45s): What to watch next, what this could become\n"
                    f"CLOSE (30s): Punchy wrap-up, ask for a subscribe, sign off with energy — not a slow fade\n\n"

                    f"Start immediately with [{host_male.upper()}]: or [{host_female.upper()}]: — no stage directions, no headers, no labels."
                )
            }]
        )

        script = response.content[0].text.strip()
        script = _spoken_ize(script)
        logger.info(f"Script written: {len(script.split())} words")
        return script

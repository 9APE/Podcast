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
                f"\nRecent episodes for continuity:\n{recent_str}\n"
                f"If relevant, one host says naturally: 'If you caught our episode on [topic], this is basically the sequel.'\n"
            )

        response = self.claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a world-class podcast script writer. Write a script for \"{channel_name}\" "
                    f"that sounds EXACTLY like Google NotebookLM's Audio Overview — two real humans having "
                    f"a genuine, unscripted-feeling conversation. Not a news read. Not a presentation. "
                    f"A messy, energetic, human conversation.\n\n"

                    f"Two hosts:\n"
                    f"- {host_male.upper()}: sharp, confident, slightly skeptical. Dry wit. Pushes back then concedes.\n"
                    f"- {host_female.upper()}: warm, fast reactor, emotionally expressive. Jumps in before {host_male} finishes.\n\n"

                    f"TODAY'S STORY: {topic['title']}\n\n"
                    f"VERIFIED FACTS (use only these):\n{claims_text}\n\n"
                    f"SOURCES:\n{sources_text}\n"
                    f"{continuity_block}\n"

                    f"TARGET LENGTH: {word_count} words (~{length_min} minutes)\n\n"

                    f"═══ CRITICAL RULES — EVERY SINGLE ONE MUST BE FOLLOWED ═══\n\n"

                    f"RULE 1 — LINE LENGTH: Each line of dialogue must be 80-100 characters MAX.\n"
                    f"If a thought is longer, SPLIT it across two lines with the same speaker.\n"
                    f"Short lines = natural TTS rhythm. Long lines = robotic.\n\n"

                    f"RULE 2 — FILLER WORDS (mandatory, not optional):\n"
                    f"Every 2-3 lines, one host MUST use one of these natural speech fillers:\n"
                    f"  'Uh,' / 'Um,' / 'I mean,' / 'Right, so' / 'Okay but' / 'Yeah, and'\n"
                    f"  'You know what,' / 'Here's the thing—' / 'So, like,' / 'And, uh,'\n"
                    f"These are NOT optional decoration. They are the PRIMARY reason NotebookLM sounds human.\n\n"

                    f"RULE 3 — NATURAL PAUSES via punctuation (TTS reads these as breathing pauses):\n"
                    f"  '...' = hesitation pause — use when a host is searching for words\n"
                    f"  ',' = micro pause — use freely inside sentences\n"
                    f"  '—' = hard cut/interruption — host gets cut off mid-sentence\n"
                    f"  '. ' (short sentence) = natural breath. Use constantly.\n"
                    f"WRONG: 'The situation in the region has deteriorated significantly over the past month.'\n"
                    f"RIGHT: 'The situation... it's bad. Like, really bad. Over the past month, uh, it's just—'\n\n"

                    f"RULE 4 — INTERRUPTIONS (at least 4 per script):\n"
                    f"  [{host_male.upper()}]: And what's crazy is the number is actually—\n"
                    f"  [{host_female.upper()}]: Wait, what number? Say it.\n"
                    f"The interrupted host's line ends with '—'. The other host cuts straight in.\n\n"

                    f"RULE 5 — REACTIONS must be SHORT and RAW (1-6 words):\n"
                    f"  'No way.' / 'Stop.' / 'That's insane.' / 'Okay, wow.' / 'Hold on.'\n"
                    f"  'Wait, seriously?' / 'That's... a lot.' / 'Hm. Yeah.'\n"
                    f"NEVER a full sentence reaction. Raw. Punchy. Unexpected.\n\n"

                    f"RULE 6 — STRUGGLE MOMENTS (at least 2 per script):\n"
                    f"One host briefly can't find the right word:\n"
                    f"  'It's like... I don't know, there's no good word for it.'\n"
                    f"  'How do I even— yeah, it's just wild.'\n\n"

                    f"RULE 7 — ECHO KEY NUMBERS immediately:\n"
                    f"  [{host_male.upper()}]: Twelve thousand people.\n"
                    f"  [{host_female.upper()}]: Twelve thousand. In a week.\n\n"

                    f"RULE 8 — SPOKEN LANGUAGE ONLY:\n"
                    f"NEVER write: 'it is', 'cannot', 'they are', 'will not', 'does not'\n"
                    f"ALWAYS write: 'it's', 'can't', 'they're', 'won't', 'doesn't'\n\n"

                    f"RULE 9 — NO HOST SPEAKS MORE THAN 3 LINES STRAIGHT.\n"
                    f"After 3 lines max, the other host must react — even if just one word.\n\n"

                    f"STRUCTURE:\n"
                    f"HOOK (30s): Open cold with ONE shocking fact. No greetings.\n"
                    f"SETUP (30s): Frame why this matters today.\n"
                    f"STORY (4-5 min): Deep back-and-forth. Contradictions. Surprising angles.\n"
                    f"FORWARD (45s): What to watch next.\n"
                    f"CLOSE (30s): Punchy wrap-up. Ask for subscribe. Sign off with energy.\n\n"

                    f"FORMAT: Every line starts with [{host_male.upper()}]: or [{host_female.upper()}]: — nothing else.\n"
                    f"No stage directions. No headers. No labels. Start immediately.\n\n"

                    f"EXAMPLE of correct style (study this):\n"
                    f"[{host_male.upper()}]: Okay so — forty billion dollars.\n"
                    f"[{host_female.upper()}]: Sorry, what?\n"
                    f"[{host_male.upper()}]: Gone. In, uh, seventy-two hours.\n"
                    f"[{host_female.upper()}]: That's... I mean, how is that even—\n"
                    f"[{host_male.upper()}]: That's what I'm saying. It doesn't make sense.\n"
                    f"[{host_female.upper()}]: Okay. Okay, walk me through it.\n"
                )
            }]
        )

        script = response.content[0].text.strip()
        script = _spoken_ize(script)
        logger.info(f"Script written: {len(script.split())} words")
        return script

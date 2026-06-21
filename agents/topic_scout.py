import os
import sqlite3
import logging
from datetime import datetime, timedelta

from exa_py import Exa
import anthropic

logger = logging.getLogger(__name__)
DB_PATH = "seen_topics.db"


class TopicScout:
    def __init__(self, channel):
        self.channel = channel
        self.exa = Exa(api_key=os.environ["EXA_API_KEY"])
        self.claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_topics (
                id INTEGER PRIMARY KEY,
                channel_id TEXT,
                title TEXT,
                date TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _is_seen(self, title):
        conn = sqlite3.connect(DB_PATH)
        cutoff = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT 1 FROM seen_topics WHERE channel_id=? AND title=? AND date>?",
            (self.channel["id"], title, cutoff)
        ).fetchone()
        conn.close()
        return row is not None

    def _mark_seen(self, title):
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO seen_topics (channel_id, title, date) VALUES (?, ?, ?)",
            (self.channel["id"], title, datetime.now().strftime("%Y-%m-%d"))
        )
        conn.commit()
        conn.close()

    def find_topic(self):
        today = datetime.now().strftime("%B %d, %Y")
        two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        queries = [
            f"most important world news story today {today}",
            f"breaking news major event {today}",
            f"top global news story this week"
        ]

        candidates = []
        for query in queries:
            try:
                results = self.exa.search_and_contents(
                    query,
                    num_results=5,
                    use_autoprompt=True,
                    start_published_date=two_days_ago,
                    text={"max_characters": 500}
                )
                for r in results.results:
                    if r.title and not self._is_seen(r.title):
                        candidates.append({
                            "title": r.title,
                            "url": r.url,
                            "summary": r.text[:400] if r.text else "",
                            "published_date": r.published_date
                        })
            except Exception as e:
                logger.warning(f"Exa search failed for '{query}': {e}")

        if not candidates:
            logger.error("No candidate topics found")
            return None

        candidates_text = "\n".join([
            f"{i+1}. {c['title']} — {c['summary'][:200]}"
            for i, c in enumerate(candidates[:10])
        ])

        response = self.claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": (
                    f"Pick the single best topic for a daily news briefing podcast targeting a general audience.\n\n"
                    f"Candidates:\n{candidates_text}\n\n"
                    f"Reply with just the number (1-{min(10, len(candidates))}). Nothing else."
                )
            }]
        )

        try:
            choice_idx = int(response.content[0].text.strip()) - 1
            chosen = candidates[max(0, min(choice_idx, len(candidates) - 1))]
        except (ValueError, IndexError):
            chosen = candidates[0]

        self._mark_seen(chosen["title"])
        logger.info(f"Topic selected: {chosen['title']}")
        return chosen

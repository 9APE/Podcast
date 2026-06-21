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
        yesterday = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # Use channel-specific queries if defined, otherwise fall back to defaults
        base_queries = self.channel.get("search_queries") or [
            f"most important world news story today {today}",
            f"breaking news major event {today}",
            f"top global news story this week"
        ]
        # Append today's date to each query to bias toward fresh results
        queries = [f"{q} {today}" if today not in q else q for q in base_queries]

        candidates = []

        # First pass: last 24 hours only (freshest content)
        for query in queries:
            try:
                results = self.exa.search_and_contents(
                    query,
                    num_results=5,
                    start_published_date=yesterday,
                    text=True
                )
                for r in results.results:
                    if r.title and not self._is_seen(r.title):
                        candidates.append({
                            "title": r.title,
                            "url": r.url,
                            "summary": (r.text or "")[:400],
                            "published_date": r.published_date,
                            "age_hours": "< 24h"
                        })
            except Exception as e:
                logger.warning(f"Exa search (24h) failed for '{query}': {e}")

        # Fallback: expand to 48 hours if slim pickings
        if len(candidates) < 5:
            logger.info("Fewer than 5 fresh candidates — expanding to 48h window")
            for query in queries:
                try:
                    results = self.exa.search_and_contents(
                        query,
                        num_results=5,
                        start_published_date=two_days_ago,
                        text=True
                    )
                    for r in results.results:
                        if r.title and not self._is_seen(r.title):
                            if not any(c["title"] == r.title for c in candidates):
                                candidates.append({
                                    "title": r.title,
                                    "url": r.url,
                                    "summary": (r.text or "")[:400],
                                    "published_date": r.published_date,
                                    "age_hours": "24-48h"
                                })
                except Exception as e:
                    logger.warning(f"Exa search (48h) failed for '{query}': {e}")

        if not candidates:
            logger.error("No candidate topics found")
            return None

        candidates_text = "\n".join([
            f"{i+1}. [{c.get('age_hours', '?')}] {c['title']} — {c['summary'][:200]}"
            for i, c in enumerate(candidates[:10])
        ])

        response = self.claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": (
                    f"Pick the single most trending and relevant topic for \"{self.channel.get('name', 'a daily podcast')}\" "
                    f"focused on {self.channel.get('niche', 'world news')}.\n\n"
                    f"Today is {today}. Strongly prefer topics published in the last 24 hours (marked < 24h). "
                    f"Pick the story that is most talked-about and impactful right now.\n\n"
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

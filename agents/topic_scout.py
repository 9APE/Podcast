import os
import re
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

    def _gather_candidates(self):
        today = datetime.now().strftime("%B %d, %Y")
        yesterday = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        base_queries = self.channel.get("search_queries") or [
            f"most important world news story today {today}",
            f"breaking news major event {today}",
            f"top global news story this week"
        ]
        queries = [f"{q} {today}" if today not in q else q for q in base_queries]

        candidates = []

        # First pass: last 24 hours
        for query in queries:
            try:
                results = self.exa.search_and_contents(
                    query,
                    num_results=6,
                    start_published_date=yesterday,
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
                                "age_hours": "< 24h"
                            })
            except Exception as e:
                logger.warning(f"Exa search (24h) failed for '{query}': {e}")

        # Fallback: expand to 48 hours if not enough candidates
        if len(candidates) < 10:
            logger.info(f"Only {len(candidates)} fresh candidates — expanding to 48h window")
            for query in queries:
                try:
                    results = self.exa.search_and_contents(
                        query,
                        num_results=6,
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

        return candidates

    def find_topics(self, n=5):
        """Return the top N most trending, unseen topics for this channel."""
        today = datetime.now().strftime("%B %d, %Y")
        candidates = self._gather_candidates()

        if not candidates:
            logger.error("No candidate topics found")
            return []

        pool = candidates[:15]  # cap at 15 to keep the prompt manageable
        n = min(n, len(pool))

        candidates_text = "\n".join([
            f"{i+1}. [{c.get('age_hours', '?')}] {c['title']} — {c['summary'][:200]}"
            for i, c in enumerate(pool)
        ])

        response = self.claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[{
                "role": "user",
                "content": (
                    f"Pick the top {n} most interesting stories for "
                    f"\"{self.channel.get('name', 'a daily podcast')}\" "
                    f"focused on {self.channel.get('niche', 'world news')}.\n\n"
                    f"Today is {today}. Strongly prefer stories from the last 24 hours.\n\n"
                    f"DIVERSITY RULE — this is critical: your {n} picks must cover DIFFERENT categories. "
                    f"No two picks can be about the same topic, person, country, or ongoing conflict. "
                    f"If Trump, Ukraine, Gaza, or any single person/war appears more than once in your picks, you have failed. "
                    f"Spread across: politics, economy, science, environment, society, technology, health, culture.\n\n"
                    f"Candidates:\n{candidates_text}\n\n"
                    f"Reply with exactly {n} comma-separated numbers in order of importance. "
                    f"Example: 3,1,5,2,4 — numbers only, nothing else."
                )
            }]
        )

        # Parse "3,1,5,2,4" → ordered list of candidates
        raw = response.content[0].text.strip()
        chosen = []
        try:
            indices = [int(x.strip()) - 1 for x in re.findall(r'\d+', raw)]
            seen_idx = set()
            for idx in indices:
                if 0 <= idx < len(pool) and idx not in seen_idx:
                    chosen.append(pool[idx])
                    seen_idx.add(idx)
        except Exception:
            logger.warning(f"Could not parse topic ranking '{raw}' — falling back to first {n}")
            chosen = pool[:n]

        # Ensure we have exactly n (pad from pool if parsing gave fewer)
        if len(chosen) < n:
            for c in pool:
                if c not in chosen:
                    chosen.append(c)
                if len(chosen) == n:
                    break

        for topic in chosen:
            self._mark_seen(topic["title"])
            logger.info(f"Topic selected: {topic['title']}")

        return chosen

    def find_topic(self):
        """Backward-compatible single-topic wrapper."""
        topics = self.find_topics(n=1)
        return topics[0] if topics else None

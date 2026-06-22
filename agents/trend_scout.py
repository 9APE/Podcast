"""
TrendScout — finds the top trending YouTube search topics right now.

Strategy:
1. Pull the top 50 trending videos from YouTube (chart=mostPopular, US)
2. Ask Claude to identify what SEARCH QUERIES people are typing to find these topics
3. Filter out already-seen topics
4. Return ranked list of podcast-ready topics with hooks
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from exa_py import Exa
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)
DB_PATH = "seen_topics.db"

# YouTube category ID → human label (for Claude context)
YT_CATEGORIES = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music",
    "15": "Pets & Animals", "17": "Sports", "19": "Travel & Events",
    "20": "Gaming", "22": "People & Blogs", "23": "Comedy",
    "24": "Entertainment", "25": "News & Politics", "26": "Howto & Style",
    "27": "Education", "28": "Science & Technology", "29": "Nonprofits",
}


class TrendScout:
    def __init__(self, channel):
        self.channel = channel
        self.claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.exa = Exa(api_key=os.environ["EXA_API_KEY"])
        self._setup_youtube()
        self._init_db()

    def _setup_youtube(self):
        secret = json.loads(os.environ["YOUTUBE_CLIENT_SECRET"])
        creds = Credentials(
            token=None,
            refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=secret["installed"]["client_id"],
            client_secret=secret["installed"]["client_secret"],
            scopes=["https://www.googleapis.com/auth/youtube.upload"]
        )
        self.youtube = build("youtube", "v3", credentials=creds)

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
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
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

    def _get_youtube_trending(self, max_results=50):
        """Fetch the top trending YouTube videos in the US right now."""
        try:
            response = self.youtube.videos().list(
                part="snippet,statistics",
                chart="mostPopular",
                regionCode="US",
                maxResults=max_results
            ).execute()

            videos = []
            for item in response.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                category = YT_CATEGORIES.get(snippet.get("categoryId", ""), "General")
                views = int(stats.get("viewCount", 0))
                videos.append({
                    "title": snippet.get("title", ""),
                    "channel": snippet.get("channelTitle", ""),
                    "category": category,
                    "views": views,
                    "description": snippet.get("description", "")[:200],
                    "video_id": item["id"],
                })

            # Sort by view count descending
            videos.sort(key=lambda x: x["views"], reverse=True)
            logger.info(f"TrendScout: fetched {len(videos)} trending YouTube videos")
            return videos

        except Exception as e:
            logger.error(f"YouTube trending fetch failed: {e}")
            return []

    def _exa_fallback(self):
        """Fallback: use Exa to find trending topics if YouTube API fails."""
        today = datetime.now().strftime("%B %d, %Y")
        yesterday = (datetime.now() - timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        queries = [
            f"most viral trending topic YouTube today {today}",
            f"most searched question trending news story {today}",
            f"viral controversy debate topic {today}",
        ]
        candidates = []
        for q in queries:
            try:
                results = self.exa.search_and_contents(
                    q, num_results=8, start_published_date=yesterday, text=True
                )
                for r in results.results:
                    if r.title and not self._is_seen(r.title):
                        candidates.append({
                            "title": r.title,
                            "url": r.url,
                            "summary": (r.text or "")[:300],
                        })
            except Exception as e:
                logger.warning(f"Exa fallback failed: {e}")
        return candidates

    def _claude_rank_trends(self, videos, n):
        """
        Ask Claude to identify the top N search queries from trending videos
        and frame them as compelling podcast topics with MrBeast-style hooks.
        """
        today = datetime.now().strftime("%B %d, %Y")

        video_list = "\n".join([
            f"{i+1}. [{v['category']}] \"{v['title']}\" by {v['channel']} — {v['views']:,} views"
            for i, v in enumerate(videos[:40])
        ])

        response = self.claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": (
                    f"Today is {today}. These are the top trending YouTube videos in the US RIGHT NOW:\n\n"
                    f"{video_list}\n\n"
                    f"Your job: identify the top {n} topics that would make VIRAL podcast episodes.\n\n"
                    f"For each topic:\n"
                    f"1. Identify what SEARCH QUERY millions of people are typing about this topic\n"
                    f"   (e.g., trending World Cup video → 'how does the World Cup bracket work')\n"
                    f"2. Write a MrBeast-style episode title — bold claim, specific if possible, creates curiosity\n"
                    f"   BAD: 'World Cup 2026 Explained'\n"
                    f"   GOOD: 'The World Cup Rule Nobody Told You About (It Changes Everything)'\n"
                    f"3. One sentence: why this topic is perfect for a podcast right now\n\n"
                    f"DIVERSITY RULE: pick {n} topics from DIFFERENT categories — sports, entertainment,\n"
                    f"tech, viral drama, science, finance, culture. No two from the same category.\n\n"
                    f"Output as JSON array:\n"
                    f"[\n"
                    f"  {{\n"
                    f"    \"title\": \"[MrBeast-style episode title]\",\n"
                    f"    \"search_query\": \"[what people are actually searching]\",\n"
                    f"    \"category\": \"[category]\",\n"
                    f"    \"why_now\": \"[one sentence]\",\n"
                    f"    \"source_video\": \"[trending video title that inspired this]\"\n"
                    f"  }}\n"
                    f"]\n\n"
                    f"Return ONLY the JSON array, nothing else."
                )
            }]
        )

        try:
            raw = response.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except Exception as e:
            logger.error(f"Claude trend ranking failed: {e}\nRaw: {response.content[0].text[:500]}")
            return []

    def _exa_research_summary(self, topic):
        """Quick Exa search to get a summary for the topic."""
        try:
            results = self.exa.search_and_contents(
                topic["search_query"],
                num_results=3,
                start_published_date=(datetime.now() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                text=True
            )
            summaries = [
                (r.text or "")[:300]
                for r in results.results
                if r.text
            ]
            return " ".join(summaries)[:600]
        except Exception:
            return topic.get("why_now", "")

    def find_topics(self, n=5):
        """Return top N trending topics ready for the podcast pipeline."""
        # Step 1: Get trending YouTube videos
        videos = self._get_youtube_trending(max_results=50)

        if not videos:
            logger.warning("YouTube trending API failed — using Exa fallback")
            fallback = self._exa_fallback()
            # Convert fallback format to match expected output
            topics = []
            for c in fallback[:n]:
                if not self._is_seen(c["title"]):
                    topics.append({
                        "title": c["title"],
                        "url": c.get("url", ""),
                        "summary": c.get("summary", ""),
                        "search_query": c["title"],
                    })
                    self._mark_seen(c["title"])
            return topics[:n]

        # Step 2: Claude identifies best podcast topics + MrBeast titles
        ranked = self._claude_rank_trends(videos, n)

        if not ranked:
            logger.error("Claude ranking returned nothing")
            return []

        # Step 3: Filter seen, enrich with Exa summary
        topics = []
        for item in ranked:
            title = item.get("title", "")
            if not title or self._is_seen(title):
                continue

            summary = self._exa_research_summary(item)
            topics.append({
                "title": title,
                "search_query": item.get("search_query", title),
                "category": item.get("category", "General"),
                "why_now": item.get("why_now", ""),
                "summary": summary,
                "url": f"https://www.youtube.com/results?search_query={item.get('search_query', '').replace(' ', '+')}",
            })
            self._mark_seen(title)

            if len(topics) == n:
                break

        logger.info(f"TrendScout: found {len(topics)} topics")
        return topics

    def find_topic(self):
        """Backward-compatible single-topic wrapper."""
        topics = self.find_topics(n=1)
        return topics[0] if topics else None

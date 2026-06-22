"""
AnalyticsAgent — reads Spotify performance data, benchmarks against
Spotify for Creators best-practice guide, and writes back targeted
improvements to channels.yaml and the script_writer prompt.

Data sources (in priority order):
  1. analytics/spotify_data.json  — exported manually from
     creators.spotify.com -> Analytics -> Export, or populated by a
     future Spotify API integration.
  2. state/*.json                 — local episode state files that
     record what was published and (once Spotify data is present)
     enriched with play/completion metrics.

Run standalone:  python -m agents.analytics_agent
Or called from orchestrator after publishing.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import yaml

logger = logging.getLogger(__name__)

ANALYTICS_DIR = Path("analytics")
STATE_DIR = Path("state")
CHANNELS_CONFIG = Path("config/channels.yaml")
SCRIPT_WRITER_PATH = Path("agents/script_writer.py")
RECOMMENDATIONS_PATH = ANALYTICS_DIR / "recommendations.json"
ANALYTICS_DATA_PATH = ANALYTICS_DIR / "spotify_data.json"


# ---------------------------------------------------------------------------
# Spotify best-practice checklist (from the official growth guide)
# Used by Claude to score the podcast and generate targeted fixes.
# ---------------------------------------------------------------------------
SPOTIFY_BEST_PRACTICES = """
SPOTIFY FOR CREATORS — GROWTH BEST PRACTICES:

1. TARGET A SPECIFIC NICHE: Narrow topic focus attracts consistent listeners.
   Broad "everything" shows struggle to grow.

2. SEO TITLES: Include specific keywords, names of people/places involved,
   trending terms. Keep under 100 chars. Make it searchable.
   Bad: "Today's News" — Good: "US-China Trade Deal Collapses: What It Means"

3. EPISODE DESCRIPTIONS: 2-3 sentences max. Preview the key topics.
   Include keywords for search. End with a hook — leave them wanting more.
   Do NOT just summarise; make them want to press play.

4. DISCOVERABILITY: Designate a "Best Place to Start" episode.
   Upload 90-second vertical video clips to Spotify for each episode.

5. EPISODE LENGTH OPTIMISATION: Track average completion rate.
   If completion < 70%, shorten episodes. If > 85%, listeners want more.

6. TOPIC RELEVANCE: Analyse which episode topics got most plays.
   Double down on those categories. Avoid topics with low engagement.

7. CONSISTENCY: Publish on a predictable schedule. Listeners who know
   when to expect you come back reliably.

8. RATINGS & REVIEWS: Ask for ratings at the start AND end of each episode.
   Add a CTA in descriptions: "Leave us a rating — it helps more people find us."

9. SOCIAL PROOF: Share episode milestones, chart appearances, listener counts
   in the episode itself to build credibility.

10. CROSS-PROMOTION: Reference related episodes. Tease upcoming topics.
    Build continuity so listeners feel they'll miss something if they skip.
"""


class AnalyticsAgent:
    def __init__(self, channel):
        self.channel = channel
        self.claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        ANALYTICS_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_spotify_data(self):
        """Load Spotify analytics export if available."""
        if ANALYTICS_DATA_PATH.exists():
            try:
                return json.loads(ANALYTICS_DATA_PATH.read_text())
            except Exception as e:
                logger.warning(f"Could not parse spotify_data.json: {e}")
        return {}

    def _load_published_episodes(self, limit=20):
        """Read recent state files to understand what was published."""
        if not STATE_DIR.exists():
            return []
        episodes = []
        channel_id = self.channel["id"]
        for f in sorted(STATE_DIR.glob(f"{channel_id}-*.json"), reverse=True)[:limit]:
            try:
                state = json.loads(f.read_text())
                if state.get("stage") == "published":
                    episodes.append({
                        "episode_id": state.get("episode_id", ""),
                        "title": state.get("topic", {}).get("title", ""),
                        "published": f.stat().st_mtime,
                        "youtube_url": state.get("youtube_url", ""),
                    })
            except Exception:
                continue
        return episodes

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyse(self):
        """Run analysis and return a recommendations dict."""
        spotify_data = self._load_spotify_data()
        episodes = self._load_published_episodes()

        has_spotify_data = bool(spotify_data.get("episodes"))

        # Build context for Claude
        episode_list = "\n".join([
            f"- {e['episode_id']}: {e['title']}"
            for e in episodes[:10]
        ]) or "No episodes published yet."

        spotify_summary = ""
        if has_spotify_data:
            ep_data = spotify_data.get("episodes", [])
            sorted_eps = sorted(ep_data, key=lambda x: x.get("plays", 0), reverse=True)
            top3 = sorted_eps[:3]
            bot3 = sorted_eps[-3:]
            avg_completion = (
                sum(e.get("avg_completion_rate", 0) for e in ep_data) / len(ep_data)
                if ep_data else 0
            )
            spotify_summary = (
                f"Spotify Analytics Summary:\n"
                f"Total episodes tracked: {len(ep_data)}\n"
                f"Average completion rate: {avg_completion:.0%}\n"
                f"Top 3 episodes by plays:\n" +
                "\n".join([f"  - {e.get('title','?')} ({e.get('plays',0)} plays, "
                           f"{e.get('avg_completion_rate',0):.0%} completion)"
                           for e in top3]) +
                f"\nBottom 3 episodes by plays:\n" +
                "\n".join([f"  - {e.get('title','?')} ({e.get('plays',0)} plays)"
                           for e in bot3]) +
                f"\nTop countries: {', '.join(spotify_data.get('channel', {}).get('top_countries', []))}\n"
                f"Top age group: {spotify_data.get('channel', {}).get('top_age_group', 'unknown')}\n"
            )
        else:
            spotify_summary = (
                "No Spotify analytics data yet (analytics/spotify_data.json not found).\n"
                "Analyse based on published episode titles and Spotify best practices only."
            )

        prompt = (
            f"You are an analytics consultant for \"{self.channel.get('name')}\" "
            f"({self.channel.get('niche')}).\n\n"
            f"PUBLISHED EPISODES:\n{episode_list}\n\n"
            f"{spotify_summary}\n\n"
            f"SPOTIFY BEST PRACTICES:\n{SPOTIFY_BEST_PRACTICES}\n\n"
            f"Based on the above, produce a JSON object with these fields:\n"
            f"{{\n"
            f'  "seo_title_format": "A Python f-string template for YouTube/Spotify titles. '
            f'Must include {{topic_title}}, be under 100 chars, keyword-rich.",\n'
            f'  "description_hook": "A 1-sentence CTA to add at the END of every description. '
            f'Encourage ratings and follows.",\n'
            f'  "preferred_topic_keywords": ["list", "of", "3-5", "keywords", '
            f'"to add to search queries"],\n'
            f'  "avoid_topic_keywords": ["topics", "to", "avoid", "based", "on", "low", "performance"],\n'
            f'  "episode_length_recommendation": 7,\n'
            f'  "script_improvement": "One specific sentence to ADD to the script writer prompt '
            f'to improve engagement or SEO based on the data.",\n'
            f'  "summary": "2-sentence plain English summary of what changed and why."\n'
            f"}}\n\n"
            f"Reply with ONLY valid JSON. No markdown, no explanation."
        )

        response = self.claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.content[0].text.strip()
        # Strip markdown code blocks if present
        raw = re.sub(r"^```json\s*|^```\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()

        try:
            recommendations = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Could not parse recommendations JSON: {e}\nRaw: {raw}")
            return {}

        recommendations["generated_at"] = datetime.now().isoformat()
        recommendations["channel_id"] = self.channel["id"]
        recommendations["had_spotify_data"] = has_spotify_data
        return recommendations

    # ------------------------------------------------------------------
    # Apply improvements
    # ------------------------------------------------------------------

    def _apply_to_channels_yaml(self, rec):
        """Update episode_length_min and search_queries in channels.yaml."""
        if not CHANNELS_CONFIG.exists():
            return
        with open(CHANNELS_CONFIG) as f:
            config = yaml.safe_load(f)

        changed = False
        for ch in config.get("channels", []):
            if ch["id"] != self.channel["id"]:
                continue

            # Episode length
            new_len = rec.get("episode_length_recommendation")
            if new_len and isinstance(new_len, int) and new_len != ch.get("episode_length_min"):
                logger.info(f"Updating episode_length_min: {ch.get('episode_length_min')} -> {new_len}")
                ch["episode_length_min"] = new_len
                changed = True

            # Inject preferred keywords into search queries
            preferred = rec.get("preferred_topic_keywords", [])
            avoid = rec.get("avoid_topic_keywords", [])
            if preferred:
                existing = ch.get("search_queries", [])
                for kw in preferred[:2]:  # add at most 2 new queries
                    new_q = f"trending {kw} news today"
                    if new_q not in existing:
                        existing.append(new_q)
                        changed = True
                ch["search_queries"] = existing[:6]  # keep list manageable

        if changed:
            with open(CHANNELS_CONFIG, "w") as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
            logger.info("channels.yaml updated with analytics recommendations")

    def _apply_to_script_writer(self, rec):
        """Append a targeted improvement rule to the script writer prompt."""
        improvement = rec.get("script_improvement", "").strip()
        if not improvement or not SCRIPT_WRITER_PATH.exists():
            return
        content = SCRIPT_WRITER_PATH.read_text()
        marker = "Start immediately with ["
        if improvement in content:
            logger.info("Script improvement already present — skipping")
            return
        # Inject as a new rule just before the final "Start immediately" line
        new_rule = f"                    f\"- {improvement}\\n\"\n"
        content = content.replace(
            f"                    f\"Start immediately with [",
            new_rule + f"                    f\"Start immediately with ["
        )
        SCRIPT_WRITER_PATH.write_text(content)
        logger.info(f"Script writer updated: {improvement[:80]}")

    def apply(self, rec):
        """Apply all actionable recommendations from the analysis."""
        if not rec:
            return
        self._apply_to_channels_yaml(rec)
        self._apply_to_script_writer(rec)
        RECOMMENDATIONS_PATH.write_text(json.dumps(rec, indent=2))
        logger.info(f"Recommendations saved: {RECOMMENDATIONS_PATH}")
        if rec.get("summary"):
            logger.info(f"Analytics summary: {rec['summary']}")

    def run(self):
        """Full cycle: analyse then apply. Returns recommendations dict."""
        logger.info(f"Running analytics for channel: {self.channel['id']}")
        rec = self.analyse()
        self.apply(rec)
        return rec


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config_path = Path("config/channels.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    for channel in config.get("channels", []):
        agent = AnalyticsAgent(channel)
        rec = agent.run()
        print(f"\n--- {channel['id']} ---")
        print(json.dumps(rec, indent=2))

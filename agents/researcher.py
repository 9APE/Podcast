import os
import json
import logging
from datetime import datetime, timedelta

from exa_py import Exa
import anthropic

logger = logging.getLogger(__name__)


class Researcher:
    def __init__(self, channel):
        self.channel = channel
        self.exa = Exa(api_key=os.environ["EXA_API_KEY"])
        self.claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def research(self, topic):
        title = topic["title"]
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        queries = [
            title,
            f"{title} background context explained",
            f"{title} reaction analysis implications"
        ]

        seen_urls = set()
        sources = []

        for query in queries:
            try:
                results = self.exa.search_and_contents(
                    query,
                    num_results=4,
                    use_autoprompt=True,
                    start_published_date=seven_days_ago,
                    text={"max_characters": 3000}
                )
                for r in results.results:
                    if r.url not in seen_urls and r.text and len(r.text) > 200:
                        seen_urls.add(r.url)
                        sources.append({
                            "title": r.title or "Unknown",
                            "url": r.url,
                            "text": r.text,
                            "published_date": r.published_date
                        })
            except Exception as e:
                logger.warning(f"Research search failed: {e}")

        if len(sources) < 3:
            logger.warning(f"Only {len(sources)} sources found — quality may be low")
        if not sources:
            return None

        sources_text = "\n\n---\n\n".join([
            f"SOURCE: {s['title']}\nURL: {s['url']}\nDATE: {s['published_date']}\n\n{s['text'][:2000]}"
            for s in sources[:6]
        ])

        response = self.claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a research analyst preparing briefing notes for a news podcast.\n\n"
                    f"Topic: {title}\n\n"
                    f"Sources:\n{sources_text}\n\n"
                    f"Extract the 12 most important verifiable factual claims from these sources.\n"
                    f"For each claim:\n"
                    f"- State it clearly and concisely\n"
                    f"- Note the source URL\n"
                    f"- Rate confidence: HIGH (2+ sources agree), MEDIUM (1 reputable source), LOW (unclear origin)\n"
                    f"- Flag if it is opinion rather than fact\n\n"
                    f"Discard opinions presented as facts, claims with no source, and claims older than 14 days.\n\n"
                    f"Return ONLY a JSON array, no other text:\n"
                    f'[{{"claim": "...", "source_url": "...", "confidence": "HIGH|MEDIUM|LOW", "is_opinion": false}}]'
                )
            }]
        )

        raw = response.content[0].text.strip()
        try:
            claims = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            claims = json.loads(raw[start:end])

        # Drop low-confidence opinions
        claims = [c for c in claims if not (c.get("is_opinion") and c.get("confidence") == "LOW")]

        logger.info(f"Research complete: {len(claims)} claims from {len(sources)} sources")
        return {
            "topic": topic,
            "sources": [{"title": s["title"], "url": s["url"]} for s in sources[:6]],
            "claims": claims
        }

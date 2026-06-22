import json
import logging
import yaml
from datetime import datetime
from pathlib import Path

from agents.topic_scout import TopicScout
from agents.trend_scout import TrendScout
from agents.researcher import Researcher
from agents.script_writer import ScriptWriter
from agents.fact_checker import FactChecker
from agents.audio_producer import AudioProducer
from agents.publisher import Publisher
from agents.analytics_agent import AnalyticsAgent
from agents.shorts_writer import ShortsWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

STATE_DIR = Path("state")
EPISODES_DIR = Path("episodes")


def init_dirs():
    STATE_DIR.mkdir(exist_ok=True)
    EPISODES_DIR.mkdir(exist_ok=True)


def load_state(episode_id):
    path = STATE_DIR / f"{episode_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"episode_id": episode_id, "stage": "start"}


def save_state(state):
    path = STATE_DIR / f"{state['episode_id']}.json"
    path.write_text(json.dumps(state, indent=2))


def validate_files(state):
    """
    GitHub Actions runners are ephemeral — episode files are not persisted.
    Reset stage to the earliest point where files are missing.
    """
    stage = state.get("stage", "start")

    file_checks = [
        (["researched", "scripted", "fact_checked", "audio_produced", "published"], "research_path"),
        (["scripted", "fact_checked", "audio_produced", "published"], "script_path"),
        (["fact_checked", "audio_produced", "published"], "verified_script_path"),
        (["audio_produced", "published"], "audio_path"),
    ]

    resets = {
        "research_path": "topic_found",
        "script_path": "researched",
        "verified_script_path": "scripted",
        "audio_path": "fact_checked",
    }

    for stages, key in file_checks:
        if stage in stages:
            path = state.get(key, "")
            if not path or not Path(path).exists():
                new_stage = resets[key]
                logger.warning(f"Missing '{key}' — resetting stage from '{stage}' to '{new_stage}'")
                state["stage"] = new_stage
                stage = new_stage

    return state


def run_episode(channel, episode_id, topic):
    """Run the full pipeline for a single topic. Returns True on success."""
    episode_dir = EPISODES_DIR / episode_id
    episode_dir.mkdir(exist_ok=True)

    state = load_state(episode_id)

    # If topic came in from outside (fresh discovery), inject it
    if state["stage"] == "start" and topic:
        state.update({"topic": topic, "stage": "topic_found"})
        save_state(state)

    state = validate_files(state)
    logger.info(f"Episode {episode_id} — stage: {state['stage']}")

    try:
        # Stage 2: Research
        if state["stage"] == "topic_found":
            logger.info("Stage 2: Research")
            research = Researcher(channel).research(state["topic"])
            if not research or len(research.get("claims", [])) < 5:
                logger.error("Insufficient research — aborting")
                return False
            research_path = episode_dir / "research.json"
            research_path.write_text(json.dumps(research, indent=2))
            state.update({"research_path": str(research_path), "stage": "researched"})
            save_state(state)

        # Stage 3: Script Writing
        if state["stage"] == "researched":
            logger.info("Stage 3: Script Writing")
            research = json.loads(Path(state["research_path"]).read_text())
            script = ScriptWriter(channel).write(state["topic"], research)
            script_path = episode_dir / "script.txt"
            script_path.write_text(script)
            state.update({"script_path": str(script_path), "stage": "scripted"})
            save_state(state)

        # Stage 4: Fact Checking
        if state["stage"] == "scripted":
            logger.info("Stage 4: Fact Checking")
            research = json.loads(Path(state["research_path"]).read_text())
            script = Path(state["script_path"]).read_text()
            verified = FactChecker().check(script, research)
            verified_path = episode_dir / "script_verified.txt"
            verified_path.write_text(verified)
            state.update({"verified_script_path": str(verified_path), "stage": "fact_checked"})
            save_state(state)

        # Stage 5: Audio Production
        if state["stage"] == "fact_checked":
            logger.info("Stage 5: Audio Production")
            script = Path(state["verified_script_path"]).read_text()
            backend = channel.get("audio_backend", "tts")
            if backend == "notebooklm":
                logger.info("Stage 5: using NotebookLM for audio")
                from agents.notebooklm_producer import NotebookLMProducer
                research = json.loads(Path(state["research_path"]).read_text())
                audio_path = NotebookLMProducer(channel).produce(
                    script, research, state["topic"], episode_dir
                )
            else:
                audio_path = AudioProducer(channel).produce(script, episode_dir)
            state.update({"audio_path": str(audio_path), "stage": "audio_produced"})
            save_state(state)

        # Stage 6: Publishing
        if state["stage"] == "audio_produced":
            logger.info("Stage 6: Publishing")
            result = Publisher(channel).publish(
                audio_path=state["audio_path"],
                topic=state["topic"],
                episode_id=episode_id,
                episode_dir=str(episode_dir)
            )
            state.update({
                "youtube_url": result.get("youtube_url"),
                "rss_url": result.get("rss_url"),
                "stage": "published"
            })
            save_state(state)
            logger.info(f"YouTube: {result.get('youtube_url')}")

        # Stage 7: Shorts
        if state["stage"] == "published" and state.get("verified_script_path"):
            logger.info("Stage 7: Shorts")
            try:
                script = Path(state["verified_script_path"]).read_text()
                shorts = ShortsWriter(channel).write(script, state["topic"], n=2)
                if shorts:
                    publisher = Publisher(channel)
                    short_urls = publisher.publish_shorts(
                        shorts,
                        episode_dir,
                        state["topic"],
                        episode_id,
                        state.get("youtube_url", "")
                    )
                    state.update({"short_urls": short_urls, "stage": "shorts_published"})
                    save_state(state)
                    logger.info(f"Shorts published: {short_urls}")
                else:
                    logger.warning("ShortsWriter returned no shorts — skipping")
                    state["stage"] = "shorts_published"
                    save_state(state)
            except Exception as e:
                logger.warning(f"Shorts stage failed (non-fatal): {e}")

        logger.info(f"Episode {episode_id} complete")
        return True

    except Exception as e:
        logger.error(f"Pipeline failed at stage '{state.get('stage')}': {e}", exc_info=True)
        return False


def run_channel(channel):
    """Discover top N topics for this channel and produce one episode per topic."""
    channel_id = channel["id"]
    date_str = datetime.now().strftime("%Y-%m-%d")
    max_topics = channel.get("max_topics", 5)

    logger.info(f"Channel {channel_id}: discovering top {max_topics} topics")
    if channel.get("use_trend_scout", False):
        logger.info(f"Channel {channel_id}: using TrendScout (YouTube trending)")
        topics = TrendScout(channel).find_topics(n=max_topics)
    else:
        topics = TopicScout(channel).find_topics(n=max_topics)

    if not topics:
        logger.error(f"Channel {channel_id}: no topics found — skipping")
        return []

    results = []
    for i, topic in enumerate(topics, start=1):
        episode_id = f"{channel_id}-{date_str}-t{i}"
        logger.info(f"--- Episode {i}/{len(topics)}: {topic['title']}")
        success = run_episode(channel, episode_id, topic)
        results.append({"episode_id": episode_id, "topic": topic["title"], "success": success})
        logger.info(f"Episode {episode_id}: {'OK' if success else 'FAILED'}")

    # Stage 7: Analytics — run once per channel after all episodes are published
    published_count = sum(1 for r in results if r["success"])
    if published_count > 0:
        logger.info(f"Stage 7: Analytics review for {channel_id}")
        try:
            rec = AnalyticsAgent(channel).run()
            if rec.get("summary"):
                logger.info(f"Analytics: {rec['summary']}")
        except Exception as e:
            logger.warning(f"Analytics stage failed (non-fatal): {e}")

    return results


def main():
    init_dirs()

    config_path = Path("config/channels.yaml")
    if not config_path.exists():
        logger.error("config/channels.yaml not found")
        return

    with open(config_path) as f:
        config = yaml.safe_load(f)

    for channel in config.get("channels", []):
        logger.info(f"=== Starting channel: {channel['id']} ===")
        results = run_channel(channel)
        ok = sum(1 for r in results if r["success"])
        logger.info(f"Channel {channel['id']}: {ok}/{len(results)} episodes published")


if __name__ == "__main__":
    main()

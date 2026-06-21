import json
import logging
import yaml
from datetime import datetime
from pathlib import Path

from agents.topic_scout import TopicScout
from agents.researcher import Researcher
from agents.script_writer import ScriptWriter
from agents.fact_checker import FactChecker
from agents.audio_producer import AudioProducer
from agents.publisher import Publisher

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


def run_channel(channel):
    channel_id = channel["id"]
    date_str = datetime.now().strftime("%Y-%m-%d")
    episode_id = f"{channel_id}-{date_str}"
    episode_dir = EPISODES_DIR / episode_id
    episode_dir.mkdir(exist_ok=True)

    state = load_state(episode_id)
    logger.info(f"Episode {episode_id} — stage: {state['stage']}")

    try:
        # Stage 1: Topic Discovery
        if state["stage"] == "start":
            logger.info("Stage 1: Topic Discovery")
            topic = TopicScout(channel).find_topic()
            if not topic:
                logger.error("No suitable topic found — aborting")
                return False
            state.update({"topic": topic, "stage": "topic_found"})
            save_state(state)

        # Stage 2: Research
        if state["stage"] == "topic_found":
            logger.info("Stage 2: Research")
            research = Researcher(channel).research(state["topic"])
            if not research or len(research.get("claims", [])) < 5:
                logger.error("Insufficient research — aborting")
                state["stage"] = "start"
                save_state(state)
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
            audio_path = AudioProducer().produce(script, episode_dir)
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

        logger.info(f"Episode {episode_id} complete")
        return True

    except Exception as e:
        logger.error(f"Pipeline failed at stage '{state.get('stage')}': {e}", exc_info=True)
        return False


def main():
    init_dirs()

    config_path = Path("config/channels.yaml")
    if not config_path.exists():
        logger.error("config/channels.yaml not found")
        return

    with open(config_path) as f:
        config = yaml.safe_load(f)

    for channel in config.get("channels", []):
        logger.info(f"Starting channel: {channel['id']}")
        success = run_channel(channel)
        status = "OK" if success else "FAILED"
        logger.info(f"Channel {channel['id']}: {status}")


if __name__ == "__main__":
    main()

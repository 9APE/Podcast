import os
import re
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Voice configuration
# Cartesia Sonic 2 — expressive, emotionally natural speech.
# Falls back to OpenAI gpt-4o-mini-tts if CARTESIA_API_KEY is not set.
#
# Voice IDs: verify/swap at https://play.cartesia.ai/voices
# ---------------------------------------------------------------------------
CARTESIA_VOICES = {
    "ALEX": "a0e99841-438c-4a64-b679-ae501e7d6091",   # Male, confident/sharp
    "SARAH": "694f9389-aac1-45b6-b726-9d9369183238",  # Female, warm/expressive
}

# Emotion + speed profiles per speaker (Cartesia experimental_controls)
CARTESIA_PROFILES = {
    "ALEX": {
        "speed": "normal",
        "emotion": ["positivity:low", "curiosity:medium"],
    },
    "SARAH": {
        "speed": "normal",
        "emotion": ["positivity:high", "curiosity:high"],
    },
}

# Short-reaction lines (≤6 words) get faster, punchier delivery
SHORT_REACTION_THRESHOLD = 6

OPENAI_VOICE_CONFIG = {
    "ALEX": {
        "voice": "onyx",
        "instructions": (
            "You're Alex — a sharp, confident news journalist on a fast-paced daily podcast. "
            "Speak naturally and conversationally, like you're genuinely reacting to news with a colleague. "
            "Your pace is slightly faster than normal conversation — energetic, direct. "
            "When delivering shocking facts, slow down slightly and let the weight land. "
            "Occasional dry wit is natural. Never robotic or overly polished."
        ),
    },
    "SARAH": {
        "voice": "nova",
        "instructions": (
            "You're Sarah — a curious, warm co-host on a daily news podcast. "
            "You react in real time — when something surprises you, let it show in your voice. "
            "Speed up when excited, slow down when something is heavy or disturbing. "
            "Short reactions like 'No.', 'Stop.', 'That's insane.' should feel spontaneous. "
            "You sound like a smart friend who genuinely cares. Never monotone."
        ),
    },
}


class AudioProducer:
    def __init__(self, channel=None):
        self.channel = channel or {}
        self._use_cartesia = bool(os.environ.get("CARTESIA_API_KEY"))

        if self._use_cartesia:
            from cartesia import Cartesia
            self._cartesia = Cartesia(api_key=os.environ["CARTESIA_API_KEY"])
            logger.info("Using Cartesia Sonic for TTS")
        else:
            from openai import OpenAI
            self._openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            logger.info("Using OpenAI gpt-4o-mini-tts for TTS (set CARTESIA_API_KEY for better voices)")

    def _parse_dialogue(self, script):
        lines = []
        pattern = re.compile(r'\[(ALEX|SARAH)\]:\s*(.*?)(?=\n\[(ALEX|SARAH)\]:|\Z)', re.DOTALL)
        for match in pattern.finditer(script):
            speaker = match.group(1)
            text = re.sub(r'\[PAUSE[^\]]*\]', ' ', match.group(2)).strip()
            text = re.sub(r'\s+', ' ', text)
            if text:
                lines.append((speaker, text))
        return lines

    def _split_into_chunks(self, text, max_chars=200):
        """
        Split at sentence boundaries. Keep chunks short (200 chars max)
        so TTS processes each beat separately — better pacing and emotion.
        """
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks, current = [], ""
        for sentence in sentences:
            if len(current) + len(sentence) + 1 <= max_chars:
                current = (current + " " + sentence).strip()
            else:
                if current:
                    chunks.append(current)
                current = sentence
        if current:
            chunks.append(current)
        return chunks if chunks else [text[:max_chars]]

    def _infer_speed(self, text, speaker):
        """Short reactions get fast delivery; heavy/long lines stay normal."""
        word_count = len(text.split())
        if word_count <= SHORT_REACTION_THRESHOLD:
            return "fast"
        if any(kw in text.lower() for kw in ["died", "killed", "billion", "million", "war", "crash"]):
            return "slow"
        return CARTESIA_PROFILES.get(speaker, CARTESIA_PROFILES["ALEX"])["speed"]

    def _tts_cartesia(self, text, speaker, output_path):
        """Generate TTS using Cartesia Sonic 2 with emotion + speed controls."""
        voice_id = CARTESIA_VOICES.get(speaker, CARTESIA_VOICES["ALEX"])
        profile = CARTESIA_PROFILES.get(speaker, CARTESIA_PROFILES["ALEX"])
        speed = self._infer_speed(text, speaker)

        data = self._cartesia.tts.bytes(
            model_id="sonic-2",
            transcript=text,
            voice={
                "id": voice_id,
                "experimental_controls": {
                    "speed": speed,
                    "emotion": profile["emotion"],
                },
            },
            output_format={
                "container": "mp3",
                "bit_rate": 128000,
                "sample_rate": 44100,
            },
        )

        with open(output_path, "wb") as f:
            for chunk in data:
                f.write(chunk)

    def _tts_openai(self, text, speaker, output_path):
        """Fallback TTS using OpenAI gpt-4o-mini-tts with personality instructions."""
        config = OPENAI_VOICE_CONFIG.get(speaker, OPENAI_VOICE_CONFIG["ALEX"])
        try:
            response = self._openai.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice=config["voice"],
                input=text,
                instructions=config["instructions"],
                response_format="mp3"
            )
            response.stream_to_file(str(output_path))
        except Exception as e:
            logger.warning(f"gpt-4o-mini-tts failed ({e}), falling back to tts-1-hd")
            response = self._openai.audio.speech.create(
                model="tts-1-hd",
                voice=config["voice"],
                input=text,
                response_format="mp3"
            )
            response.stream_to_file(str(output_path))

    def _tts(self, text, speaker, output_path):
        if self._use_cartesia:
            self._tts_cartesia(text, speaker, output_path)
        else:
            self._tts_openai(text, speaker, output_path)

    def _create_silence(self, duration_ms, output_path):
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(duration_ms / 1000),
            "-q:a", "9", "-acodec", "libmp3lame",
            str(output_path)
        ], check=True, capture_output=True)

    def _concat_files(self, file_paths, output_path):
        list_file = Path(output_path).parent / "concat_list.txt"
        with open(list_file, "w") as f:
            for fp in file_paths:
                f.write(f"file '{Path(fp).absolute()}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-ar", "44100", "-ac", "1", "-b:a", "128k",
            str(output_path)
        ], check=True, capture_output=True)
        list_file.unlink()

    def _normalize(self, input_path, output_path):
        result = subprocess.run([
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "44100", "-b:a", "192k",
            str(output_path)
        ], check=True, capture_output=True)
        if result.stderr:
            logger.debug("ffmpeg loudnorm stderr: %s", result.stderr.decode(errors="replace")[-500:])

    def produce(self, script, episode_dir):
        episode_dir = Path(episode_dir)
        chunks_dir = episode_dir / "chunks"
        chunks_dir.mkdir(exist_ok=True)

        lines = self._parse_dialogue(script)
        if not lines:
            raise ValueError("No dialogue lines found. Script must use [ALEX]: and [SARAH]: tags.")

        logger.info(f"Parsed {len(lines)} dialogue lines")

        silence_path = chunks_dir / "silence.mp3"
        self._create_silence(300, silence_path)  # 300ms gap between speakers

        audio_files = []
        file_idx = 0

        for speaker, text in lines:
            text_chunks = self._split_into_chunks(text)
            for chunk in text_chunks:
                chunk_path = chunks_dir / f"line_{file_idx:04d}_{speaker.lower()}.mp3"
                logger.info(f"TTS [{speaker}] ({len(chunk)} chars)")
                self._tts(chunk, speaker, chunk_path)
                audio_files.append(chunk_path)
                file_idx += 1
            audio_files.append(silence_path)

        raw_path = episode_dir / "raw.mp3"
        self._concat_files(audio_files, raw_path)

        final_path = episode_dir / "episode.mp3"
        self._normalize(raw_path, final_path)
        raw_path.unlink()

        logger.info(f"Audio ready: {final_path}")
        return final_path

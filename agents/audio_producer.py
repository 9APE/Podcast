import os
import re
import logging
import subprocess
from pathlib import Path

from openai import OpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Voice personality instructions for gpt-4o-mini-tts
# These make the voices sound human — emotional, paced, alive.
# ---------------------------------------------------------------------------
VOICE_CONFIG = {
    "ALEX": {
        "voice": "onyx",
        "instructions": (
            "You're Alex — a sharp, confident news journalist hosting a fast-paced daily podcast. "
            "Speak naturally and conversationally, like you're genuinely reacting to news with a colleague, not reading a script. "
            "Your pace is slightly faster than normal conversation — energetic, direct, no filler pauses. "
            "When delivering shocking facts or numbers, slow down just slightly and let the weight land. "
            "Occasional dry wit is natural for you. "
            "Never sound robotic or overly polished — you're a real person who finds this stuff genuinely interesting."
        ),
    },
    "SARAH": {
        "voice": "nova",
        "instructions": (
            "You're Sarah — a curious, warm co-host on a daily news podcast. "
            "You react in real time — when something surprises you, let it show in your voice. "
            "Speed up a little when excited, slow down when something is heavy or disturbing. "
            "Short reactions like 'No.', 'Stop.', 'That's insane.' should feel spontaneous, not performed. "
            "You sound like a smart friend who genuinely cares about understanding things, not a news anchor. "
            "Never monotone — your voice has range and your emotions are real."
        ),
    },
}


class AudioProducer:
    def __init__(self, channel=None):
        self.openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.channel = channel or {}

    def _parse_dialogue(self, script):
        """Parse [ALEX]: / [SARAH]: tagged lines into (speaker, text) tuples."""
        lines = []
        pattern = re.compile(r'\[(ALEX|SARAH)\]:\s*(.*?)(?=\n\[(ALEX|SARAH)\]:|\Z)', re.DOTALL)
        for match in pattern.finditer(script):
            speaker = match.group(1)
            text = re.sub(r'\[PAUSE[^\]]*\]', ' ', match.group(2)).strip()
            text = re.sub(r'\s+', ' ', text)
            if text:
                lines.append((speaker, text))
        return lines

    def _split_into_chunks(self, text, max_chars=4000):
        """Split long text into TTS-safe chunks at sentence boundaries."""
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

    def _tts(self, text, speaker, output_path):
        """Generate TTS audio using gpt-4o-mini-tts with personality instructions."""
        config = VOICE_CONFIG.get(speaker, VOICE_CONFIG["ALEX"])
        try:
            response = self.openai.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice=config["voice"],
                input=text,
                instructions=config["instructions"],
                response_format="mp3"
            )
            response.stream_to_file(str(output_path))
        except Exception as e:
            # Fallback to tts-1-hd if gpt-4o-mini-tts is unavailable
            logger.warning(f"gpt-4o-mini-tts failed ({e}), falling back to tts-1-hd")
            response = self.openai.audio.speech.create(
                model="tts-1-hd",
                voice=config["voice"],
                input=text,
                response_format="mp3"
            )
            response.stream_to_file(str(output_path))

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
        # Re-encode to consistent format so loudnorm doesn't SIGABRT on
        # mixed-rate streams (OpenAI TTS is 24kHz; silence files are 44100Hz).
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
        self._create_silence(400, silence_path)

        audio_files = []
        file_idx = 0

        for speaker, text in lines:
            text_chunks = self._split_into_chunks(text)

            for chunk in text_chunks:
                chunk_path = chunks_dir / f"line_{file_idx:04d}_{speaker.lower()}.mp3"
                logger.info(f"TTS [{speaker}] ({len(chunk)} chars) voice={VOICE_CONFIG.get(speaker, {}).get('voice', 'onyx')}")
                self._tts(chunk, speaker, chunk_path)
                audio_files.append(chunk_path)
                file_idx += 1

            # Short pause between speaker turns
            audio_files.append(silence_path)

        raw_path = episode_dir / "raw.mp3"
        self._concat_files(audio_files, raw_path)

        final_path = episode_dir / "episode.mp3"
        self._normalize(raw_path, final_path)
        raw_path.unlink()

        logger.info(f"Audio ready: {final_path}")
        return final_path

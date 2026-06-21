import os
import re
import logging
import subprocess
from pathlib import Path

from elevenlabs import ElevenLabs

logger = logging.getLogger(__name__)

# Default ElevenLabs pre-made voice IDs
# Adam = deep male American, Rachel = calm female American
DEFAULT_MALE_VOICE = "pNInz6obpgDQGcFmaJgB"
DEFAULT_FEMALE_VOICE = "21m00Tcm4TlvDq8ikWAM"


class AudioProducer:
    def __init__(self, channel=None):
        self.client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
        self.male_voice_id = (
            (channel or {}).get("voice_male_id") or
            os.environ.get("ELEVENLABS_MALE_VOICE", DEFAULT_MALE_VOICE)
        )
        self.female_voice_id = (
            (channel or {}).get("voice_female_id") or
            os.environ.get("ELEVENLABS_FEMALE_VOICE", DEFAULT_FEMALE_VOICE)
        )

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

    def _chunk_dialogue(self, lines, max_chars=1800):
        """Batch lines into chunks under max_chars (ElevenLabs per-request limit)."""
        chunks, current, current_len = [], [], 0
        for speaker, text in lines:
            length = len(text)
            if current and current_len + length > max_chars:
                chunks.append(current)
                current, current_len = [], 0
            current.append((speaker, text))
            current_len += length
        if current:
            chunks.append(current)
        return chunks

    def _generate_chunk(self, lines, output_path):
        """Call ElevenLabs Text to Dialogue API for one chunk."""
        inputs = [
            {
                "voice_id": self.male_voice_id if speaker == "ALEX" else self.female_voice_id,
                "text": text
            }
            for speaker, text in lines
        ]

        audio = self.client.text_to_dialogue.convert(
            inputs=inputs,
            model_id="eleven_v3"
        )

        # Handle both bytes and streaming generator responses
        if isinstance(audio, bytes):
            audio_bytes = audio
        else:
            audio_bytes = b"".join(audio)

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

    def _concat_files(self, file_paths, output_path):
        list_file = Path(output_path).parent / "concat_list.txt"
        with open(list_file, "w") as f:
            for fp in file_paths:
                f.write(f"file '{Path(fp).absolute()}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-c", "copy", str(output_path)
        ], check=True, capture_output=True)
        list_file.unlink()

    def _normalize(self, input_path, output_path):
        subprocess.run([
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "44100", "-b:a", "192k",
            str(output_path)
        ], check=True, capture_output=True)

    def produce(self, script, episode_dir):
        episode_dir = Path(episode_dir)
        chunks_dir = episode_dir / "chunks"
        chunks_dir.mkdir(exist_ok=True)

        lines = self._parse_dialogue(script)
        if not lines:
            raise ValueError("No dialogue lines found. Script must use [ALEX]: and [SARAH]: tags.")

        logger.info(f"Parsed {len(lines)} dialogue lines")
        chunks = self._chunk_dialogue(lines)
        logger.info(f"Generating {len(chunks)} ElevenLabs chunks")

        audio_files = []
        for i, chunk in enumerate(chunks):
            chunk_path = chunks_dir / f"chunk_{i:03d}.mp3"
            logger.info(f"ElevenLabs chunk {i + 1}/{len(chunks)} ({sum(len(t) for _, t in chunk)} chars)")
            self._generate_chunk(chunk, chunk_path)
            audio_files.append(chunk_path)

        raw_path = episode_dir / "raw.mp3"
        if len(audio_files) == 1:
            audio_files[0].rename(raw_path)
        else:
            self._concat_files(audio_files, raw_path)

        final_path = episode_dir / "episode.mp3"
        self._normalize(raw_path, final_path)
        if raw_path.exists():
            raw_path.unlink()

        logger.info(f"Audio ready: {final_path}")
        return final_path

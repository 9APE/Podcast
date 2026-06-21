import os
import re
import logging
import subprocess
from pathlib import Path

from openai import OpenAI

logger = logging.getLogger(__name__)


class AudioProducer:
    def __init__(self):
        self.openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.voice = "onyx"

    def _split_into_chunks(self, script, max_chars=4000):
        parts = re.split(r'\[PAUSE[^\]]*\]', script)
        chunks = []
        current = ""
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if len(current) + len(part) + 1 <= max_chars:
                current = (current + " " + part).strip()
            else:
                if current:
                    chunks.append(current)
                current = part
        if current:
            chunks.append(current)
        return chunks

    def _tts_chunk(self, text, output_path):
        response = self.openai.audio.speech.create(
            model="tts-1-hd",
            voice=self.voice,
            input=text,
            response_format="mp3"
        )
        response.stream_to_file(str(output_path))

    def _create_silence(self, duration_ms, output_path):
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=mono",
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

        chunks = self._split_into_chunks(script)
        logger.info(f"Generating TTS for {len(chunks)} chunks")

        silence_path = chunks_dir / "silence.mp3"
        self._create_silence(500, silence_path)

        audio_files = []
        for i, chunk in enumerate(chunks):
            chunk_path = chunks_dir / f"chunk_{i:03d}.mp3"
            logger.info(f"TTS chunk {i + 1}/{len(chunks)}")
            self._tts_chunk(chunk, chunk_path)
            audio_files.append(chunk_path)
            if i < len(chunks) - 1:
                audio_files.append(silence_path)

        raw_path = episode_dir / "raw.mp3"
        self._concat_files(audio_files, raw_path)

        final_path = episode_dir / "episode.mp3"
        self._normalize(raw_path, final_path)
        raw_path.unlink()

        logger.info(f"Audio ready: {final_path}")
        return final_path

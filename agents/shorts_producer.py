"""
ShortsProducer — turns a Short script into a vertical 1080x1920 MP4.

Steps:
1. Generate TTS audio line-by-line (reuses AudioProducer)
2. Measure each clip's duration with ffprobe
3. Create 1080x1920 PIL background with gradient + branding
4. Build ASS subtitle file (font 76, white + black outline)
5. Render final MP4 with ffmpeg subtitles filter
"""

import os
import re
import json
import logging
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from agents.audio_producer import AudioProducer

logger = logging.getLogger(__name__)

SHORT_W = 1080
SHORT_H = 1920
FONT_SIZE = 76
GRADIENT_TOP = (15, 15, 25)
GRADIENT_BOT = (40, 20, 60)


class ShortsProducer:
    def __init__(self, channel):
        self.channel = channel
        self.audio_producer = AudioProducer(channel)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def produce(self, short: dict, episode_dir: Path, short_index: int) -> str:
        """Produce an MP4 for one Short. Returns the video file path."""
        episode_dir = Path(episode_dir)
        short_dir = episode_dir / f"short_{short_index}"
        short_dir.mkdir(exist_ok=True)

        lines = self._parse_lines(short["script"])
        if not lines:
            raise ValueError("Short script has no dialogue lines")

        # 1. Generate per-line audio files
        audio_clips = self._generate_audio(lines, short_dir)

        # 2. Measure durations
        durations = [self._audio_duration(p) for p in audio_clips]

        # 3. Concatenate audio
        combined_audio = short_dir / "combined.mp3"
        self._concat_audio(audio_clips, combined_audio)

        # 4. Build background image
        bg_path = short_dir / "background.png"
        self._make_background(bg_path)

        # 5. Build ASS subtitle file
        ass_path = short_dir / "subs.ass"
        self._make_ass(lines, durations, ass_path)

        # 6. Render video
        video_path = short_dir / f"short_{short_index}.mp4"
        self._render(bg_path, combined_audio, ass_path, video_path, sum(durations))

        logger.info(f"Short {short_index} rendered: {video_path}")
        return str(video_path)

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def _parse_lines(self, script: str) -> list:
        lines = []
        for raw in script.strip().split("\n"):
            raw = raw.strip()
            if not raw:
                continue
            m = re.match(r"\[([A-Z]+)\]:\s*(.*)", raw)
            if m:
                lines.append({"speaker": m.group(1), "text": m.group(2).strip()})
        return lines

    def _generate_audio(self, lines: list, out_dir: Path) -> list:
        paths = []
        host_male = self.channel.get("host_male", "Alex").upper()
        voice_male = self.channel.get("voice_male", "onyx")
        voice_female = self.channel.get("voice_female", "nova")

        for i, line in enumerate(lines):
            voice = voice_male if line["speaker"] == host_male else voice_female
            clip_path = out_dir / f"line_{i:02d}.mp3"
            self.audio_producer._tts(line["text"], voice, str(clip_path))
            paths.append(clip_path)
        return paths

    def _audio_duration(self, path: Path) -> float:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=10
            )
            return float(result.stdout.strip())
        except Exception:
            return 3.0

    def _concat_audio(self, clips: list, out_path: Path):
        list_file = out_path.parent / "filelist.txt"
        list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in clips))
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(list_file), "-c", "copy", str(out_path)],
            check=True, capture_output=True
        )

    # ------------------------------------------------------------------
    # Visual
    # ------------------------------------------------------------------

    def _make_background(self, out_path: Path):
        img = Image.new("RGB", (SHORT_W, SHORT_H))
        draw = ImageDraw.Draw(img)
        for y in range(SHORT_H):
            t = y / SHORT_H
            r = int(GRADIENT_TOP[0] + t * (GRADIENT_BOT[0] - GRADIENT_TOP[0]))
            g = int(GRADIENT_TOP[1] + t * (GRADIENT_BOT[1] - GRADIENT_TOP[1]))
            b = int(GRADIENT_TOP[2] + t * (GRADIENT_BOT[2] - GRADIENT_TOP[2]))
            draw.line([(0, y), (SHORT_W, y)], fill=(r, g, b))

        # Channel name branding
        channel_name = self.channel.get("name", "The Pod")
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), channel_name, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((SHORT_W - tw) // 2, 80), channel_name, fill=(255, 255, 255, 200), font=font)

        img.save(str(out_path))

    def _make_ass(self, lines: list, durations: list, out_path: Path):
        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {SHORT_W}\n"
            f"PlayResY: {SHORT_H}\n"
            "Collisions: Normal\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,DejaVu Sans,{FONT_SIZE},&H00FFFFFF,&H000000FF,"
            "&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,60,60,300,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        events = []
        t = 0.0
        for line, dur in zip(lines, durations):
            start = self._ts(t)
            end = self._ts(t + dur)
            text = line["text"].replace("\n", "\\N")
            events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
            t += dur

        out_path.write_text(header + "\n".join(events))

    @staticmethod
    def _ts(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _render(self, bg: Path, audio: Path, ass: Path, out: Path, duration: float):
        ass_escaped = str(ass).replace("\\", "/").replace(":", "\\:")
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(bg),
            "-i", str(audio),
            "-vf", f"subtitles={ass_escaped}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration + 0.5),
            "-pix_fmt", "yuv420p",
            str(out)
        ], check=True, capture_output=True)

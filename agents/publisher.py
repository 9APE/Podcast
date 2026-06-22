import os
import json
import logging
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

RSS_PATH = Path("rss/feed.xml")
GITHUB_PAGES_URL = "https://9ape.github.io/Podcast"


class Publisher:
    def __init__(self, channel):
        self.channel = channel
        self._setup_youtube()

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

    def _create_thumbnail(self, title, episode_dir):
        img = Image.new("RGB", (1280, 720), color=(12, 12, 22))
        draw = ImageDraw.Draw(img)

        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 62)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
        except OSError:
            font_large = ImageFont.load_default()
            font_small = font_large

        # Accent bar
        draw.rectangle([60, 195, 1220, 202], fill=(58, 110, 240))

        # Channel name
        draw.text((64, 118), self.channel.get("name", "Daily Briefing"), font=font_small, fill=(140, 150, 210))

        # Title wrapped
        words = title.split()
        lines, line = [], []
        for word in words:
            test = " ".join(line + [word])
            bbox = draw.textbbox((0, 0), test, font=font_large)
            if bbox[2] - bbox[0] > 1150 and line:
                lines.append(" ".join(line))
                line = [word]
            else:
                line.append(word)
        if line:
            lines.append(" ".join(line))

        y = 230
        for text_line in lines[:3]:
            draw.text((64, y), text_line, font=font_large, fill=(235, 238, 255))
            y += 78

        draw.text((64, 618), datetime.now().strftime("%B %d, %Y"), font=font_small, fill=(110, 120, 160))

        path = Path(episode_dir) / "thumbnail.jpg"
        img.save(path, "JPEG", quality=95)
        return path

    def _create_video(self, audio_path, thumbnail_path, episode_dir):
        video_path = Path(episode_dir) / "episode.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(thumbnail_path),
            "-i", str(audio_path),
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest", str(video_path)
        ], check=True, capture_output=True)
        return video_path

    def _build_seo_title(self, topic):
        """Build a keyword-rich, searchable title under 100 chars."""
        channel_name = self.channel.get("name", "The News Pod")
        raw = topic["title"].strip()

        # Load analytics recommendations if available
        rec_path = Path("analytics/recommendations.json")
        seo_format = None
        if rec_path.exists():
            try:
                rec = json.loads(rec_path.read_text())
                seo_format = rec.get("seo_title_format")
            except Exception:
                pass

        if seo_format:
            try:
                title = seo_format.format(
                    topic_title=raw,
                    channel_name=channel_name,
                    date=datetime.now().strftime("%b %d")
                )
                return title[:100]
            except Exception:
                pass

        # Default SEO format: topic | channel | date
        date_short = datetime.now().strftime("%b %d, %Y")
        title = f"{raw[:70]} | {channel_name} | {date_short}"
        return title[:100]

    def _build_description(self, topic, sources):
        date_str = datetime.now().strftime("%B %d, %Y")
        tags = self.channel.get("tags", ["news", "daily briefing"])
        channel_name = self.channel.get("name", "The News Pod")

        sources_lines = "\n".join([
            f"[{i+1}] {s.get('title', 'Source')}\n     {s.get('url', '')}"
            for i, s in enumerate(sources)
        ])

        # Load custom CTA from analytics recommendations if available
        ratings_cta = "If this episode was useful, leave us a rating — it helps more people find us."
        rec_path = Path("analytics/recommendations.json")
        if rec_path.exists():
            try:
                rec = json.loads(rec_path.read_text())
                custom_cta = rec.get("description_hook", "")
                if custom_cta:
                    ratings_cta = custom_cta
            except Exception:
                pass

        # Keyword-rich opening hook (2-3 sentences, searchable)
        hook = (
            f"Today on {channel_name} ({date_str}): {topic['title']}. "
            f"Alex and Sarah break down everything you need to know — "
            f"what happened, why it matters, and what comes next."
        )

        return (
            f"{hook}\n\n"
            f"{self.channel.get('description', '')}\n\n"
            f"SOURCES:\n{sources_lines}\n\n"
            f"All facts are sourced and verified.\n\n"
            f"{ratings_cta}\n\n"
            f"#{' #'.join(tags)}"
        )

    def _upload_youtube(self, video_path, topic, episode_id, sources=None):
        title = self._build_seo_title(topic)
        tags = self.channel.get("tags", ["news", "daily briefing"])
        description = self._build_description(topic, sources or [])
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": self.channel.get("youtube_category_id", "25"),
                "defaultLanguage": "en"
            },
            "status": {
                "privacyStatus": "public",
                "madeForKids": False,
                "selfDeclaredMadeForKids": False
            }
        }
        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
        request = self.youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"YouTube upload: {int(status.progress() * 100)}%")
        video_id = response["id"]
        logger.info(f"YouTube published: {video_id}")
        return f"https://youtube.com/watch?v={video_id}"

    def _upload_to_github_release(self, audio_path, episode_id):
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            logger.warning("GITHUB_TOKEN not set, skipping release upload")
            return None

        repo = os.environ.get("GITHUB_REPOSITORY", "9APE/Podcast")
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }

        r = requests.post(
            f"https://api.github.com/repos/{repo}/releases",
            json={"tag_name": episode_id, "name": episode_id, "draft": False, "prerelease": False},
            headers=headers
        )
        r.raise_for_status()
        upload_url = r.json()["upload_url"].replace("{?name,label}", "")

        filename = f"{episode_id}.mp3"
        with open(audio_path, "rb") as f:
            r = requests.post(
                f"{upload_url}?name={filename}",
                headers={**headers, "Content-Type": "audio/mpeg"},
                data=f
            )
        r.raise_for_status()
        url = r.json()["browser_download_url"]
        logger.info(f"Audio uploaded: {url}")
        return url

    def _update_rss(self, episode_id, topic, audio_url, youtube_url, audio_path):
        RSS_PATH.parent.mkdir(exist_ok=True)

        ns = {
            "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
            "content": "http://purl.org/rss/1.0/modules/content/"
        }
        for prefix, uri in ns.items():
            ET.register_namespace(prefix, uri)

        ARTWORK_URL = f"{GITHUB_PAGES_URL}/rss/artwork.jpg"
        OWNER_EMAIL = "ariimoanapons@gmail.com"

        if RSS_PATH.exists():
            tree = ET.parse(RSS_PATH)
            root = tree.getroot()
            channel_el = root.find("channel")
            # Count existing episodes for numbering
            episode_number = len(channel_el.findall("item")) + 1
        else:
            root = ET.Element("rss", {
                "version": "2.0",
                "xmlns:itunes": ns["itunes"],
                "xmlns:content": ns["content"]
            })
            channel_el = ET.SubElement(root, "channel")
            channel_name = self.channel.get("name", "The News Pod")
            ET.SubElement(channel_el, "title").text = channel_name
            ET.SubElement(channel_el, "link").text = GITHUB_PAGES_URL
            ET.SubElement(channel_el, "description").text = self.channel.get(
                "description", "Your daily AI-powered news briefing."
            )
            ET.SubElement(channel_el, "language").text = "en-us"
            ET.SubElement(channel_el, "{%s}author" % ns["itunes"]).text = channel_name
            ET.SubElement(channel_el, "{%s}explicit" % ns["itunes"]).text = "false"
            ET.SubElement(channel_el, "{%s}type" % ns["itunes"]).text = "episodic"
            ET.SubElement(channel_el, "{%s}category" % ns["itunes"], {"text": "News"})
            ET.SubElement(channel_el, "{%s}image" % ns["itunes"], {"href": ARTWORK_URL})
            owner_el = ET.SubElement(channel_el, "{%s}owner" % ns["itunes"])
            ET.SubElement(owner_el, "{%s}name" % ns["itunes"]).text = channel_name
            ET.SubElement(owner_el, "{%s}email" % ns["itunes"]).text = OWNER_EMAIL
            episode_number = 1

        audio_size = Path(audio_path).stat().st_size if Path(audio_path).exists() else 0
        pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

        item = ET.SubElement(channel_el, "item")
        ET.SubElement(item, "title").text = topic["title"]
        ET.SubElement(item, "{%s}title" % ns["itunes"]).text = topic["title"]
        ET.SubElement(item, "description").text = (
            f"Today's briefing: {topic['title']}. "
            f"Watch on YouTube: {youtube_url}"
        )
        ET.SubElement(item, "pubDate").text = pub_date
        ET.SubElement(item, "guid").text = episode_id
        ET.SubElement(item, "{%s}episodeType" % ns["itunes"]).text = "full"
        ET.SubElement(item, "{%s}episode" % ns["itunes"]).text = str(episode_number)
        ET.SubElement(item, "{%s}explicit" % ns["itunes"]).text = "false"
        if audio_url:
            ET.SubElement(item, "enclosure", {
                "url": audio_url,
                "type": "audio/mpeg",
                "length": str(audio_size)
            })
        ET.SubElement(item, "{%s}duration" % ns["itunes"]).text = str(
            self.channel.get("episode_length_min", 7) * 60
        )

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(str(RSS_PATH), encoding="unicode", xml_declaration=True)
        logger.info(f"RSS feed updated — episode {episode_number}")

    def publish(self, audio_path, topic, episode_id, episode_dir):
        import json as _json
        audio_path = Path(audio_path)

        # Load sources from research bundle for description
        sources = []
        research_path = Path(episode_dir) / "research.json"
        if research_path.exists():
            try:
                research = _json.loads(research_path.read_text())
                sources = research.get("sources", [])
            except Exception:
                pass

        logger.info("Creating thumbnail")
        thumbnail_path = self._create_thumbnail(topic["title"], episode_dir)

        logger.info("Creating video")
        video_path = self._create_video(audio_path, thumbnail_path, episode_dir)

        logger.info("Uploading to YouTube")
        youtube_url = self._upload_youtube(video_path, topic, episode_id, sources)

        logger.info("Uploading audio to GitHub Releases")
        audio_url = self._upload_to_github_release(audio_path, episode_id)

        logger.info("Updating RSS feed")
        self._update_rss(episode_id, topic, audio_url, youtube_url, audio_path)

        return {
            "youtube_url": youtube_url,
            "audio_url": audio_url,
            "rss_url": f"{GITHUB_PAGES_URL}/rss/feed.xml"
        }

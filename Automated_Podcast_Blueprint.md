# Automated AI Podcast Production System — Engineering Blueprint

**Version:** 1.0  
**Date:** 2026-06-21  
**Status:** MVP-ready design

---

## 1. System Architecture

### High-Level Overview

The system is a multi-agent pipeline triggered by a scheduler. Each episode goes through six discrete stages. Stages are sequential but the system can run multiple channels in parallel.

```
┌─────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                             │
│           (scheduler + state machine + error handler)           │
└──────────────────────┬──────────────────────────────────────────┘
                       │ triggers per channel, per schedule
          ┌────────────▼────────────┐
          │     Topic Scout         │  ← niche config + RSS/API feeds
          └────────────┬────────────┘
                       │ top-scored topic
          ┌────────────▼────────────┐
          │    Research Agent       │  ← Exa.ai + NewsAPI + arXiv
          └────────────┬────────────┘
                       │ source bundle (facts + quotes + URLs)
          ┌────────────▼────────────┐
          │    Script Writer        │  ← Claude Sonnet API
          └────────────┬────────────┘
                       │ structured script (segments + hooks)
          ┌────────────▼────────────┐
          │    Fact Checker         │  ← Claude + source re-verification
          └────────────┬────────────┘
                       │ verified script + citation map
          ┌────────────▼────────────┐
          │    Audio Producer       │  ← TTS + ffmpeg mastering
          └────────────┬────────────┘
                       │ mastered .mp3
          ┌────────────▼────────────┐
          │      Publisher          │  ← YouTube API + RSS feed update
          └─────────────────────────┘
```

### State Persistence

Each episode has a JSON state file that tracks which stage it completed. If the pipeline crashes mid-run, it resumes from the last successful stage rather than restarting.

```json
{
  "episode_id": "tech-2026-06-21-001",
  "channel": "ai_weekly",
  "stage": "audio_produced",
  "topic": "Neuromorphic chips reach consumer hardware",
  "sources": ["..."],
  "script_path": "/episodes/tech-2026-06-21-001/script.txt",
  "audio_path": "/episodes/tech-2026-06-21-001/final.mp3",
  "published_youtube": false,
  "published_rss": false
}
```

---

## 2. Tooling Stack

### Topic Discovery
| Tool | Purpose | Cost |
|---|---|---|
| **Exa.ai** (neural search) | Find trending articles by semantic query | $0.005/search |
| **Reddit API** (PRAW) | Pull top posts from niche subreddits | Free |
| **NewsAPI** | Breaking news filtered by topic | Free tier (100 req/day) |
| **arXiv API** | Academic papers in STEM niches | Free |
| **Google Trends (via pytrends)** | Detect rising search interest | Free (unofficial) |

Topic scoring formula: `score = (recency_weight × 0.4) + (engagement_weight × 0.3) + (novelty_score × 0.3)`

Previously used topics are stored in a SQLite database to prevent repeats.

### Research Gathering
| Tool | Purpose | Cost |
|---|---|---|
| **Exa.ai** | Retrieve full article text by URL or topic | $0.01/retrieval |
| **Firecrawl API** | Scrape paywalled/complex sites cleanly | $0.001/page |
| **arXiv API** | Fetch paper abstracts + conclusions | Free |
| **Wikipedia API** | Background context + definitions | Free |

Each research bundle targets 5-8 sources minimum. Sources below a trust threshold (no author, no date, no known domain) are discarded automatically.

### LLM Reasoning / Synthesis
| Tool | Purpose |
|---|---|
| **Claude Sonnet** (`claude-sonnet-4-6`) | Research synthesis, script writing, fact checking |
| **Claude Haiku** | Light tasks: topic scoring, title generation, metadata |

Use Sonnet for quality-critical stages. Haiku for anything cheap and simple.

### Voice Generation (TTS)
| Tool | Quality | Cost |
|---|---|---|
| **ElevenLabs API** | Best naturalness, custom voices | ~$0.30/1k chars |
| **OpenAI TTS** (`tts-1-hd`) | Good quality, cheapest | $0.030/1k chars |
| **Cartesia API** | Fast, low latency, good voices | ~$0.065/1k chars |

**Recommendation:** OpenAI TTS for MVP (cost), ElevenLabs once revenue justifies it.

A 15-minute episode script ≈ 14,000 characters:
- OpenAI TTS: ~$0.42
- ElevenLabs: ~$4.20

### Audio Editing / Mastering
| Tool | Purpose |
|---|---|
| **ffmpeg** | Concat segments, add music, fade in/out, export MP3 |
| **pydub** | Python-level audio manipulation |
| **pyloudnorm** | LUFS normalization to podcast standards (-16 LUFS) |
| **Freesound API** or **Pixabay** | Royalty-free intro/outro music |

No paid audio tools required. ffmpeg handles everything.

### Video Generation (YouTube)
For YouTube, the simplest valid approach: static image + audio = video file.

| Option | Tool | Notes |
|---|---|---|
| **Static image video** | ffmpeg | Channel art + waveform animation |
| **Waveform video** | audiogram-python or ffmpeg filters | Animated audio visualizer |
| **AI video** | Runway ML API | Much higher cost, skip for MVP |

```bash
ffmpeg -loop 1 -i thumbnail.jpg -i episode.mp3 \
  -c:v libx264 -tune stillimage -c:a aac \
  -shortest output.mp4
```

### Scheduling + Orchestration
| Option | Verdict |
|---|---|
| **GitHub Actions** (cron) | Best for MVP — free, reliable, no server |
| **Railway.app** | Good for always-on multi-channel setup (~$5/mo) |
| **Prefect Cloud** | Overkill for MVP, good at scale |
| **APScheduler** (in-process) | Fine for single-machine deployments |

**MVP recommendation:** GitHub Actions with cron trigger. Zero infrastructure cost.

### Publishing
| Platform | Method |
|---|---|
| **YouTube** | YouTube Data API v3 (OAuth2, `videos.insert`) |
| **Spotify** | RSS feed submitted to Spotify for Podcasters |
| **Apple Podcasts** | Same RSS feed |
| **Amazon Music / iHeart** | Same RSS feed |

RSS feed can be hosted as a static XML file on:
- GitHub Pages (free)
- Cloudflare R2 + Workers (free tier)
- Any S3-compatible bucket

---

## 3. Full Automation Pipeline

### Step-by-Step Flow

**Stage 0 — Config**
```
channels.yaml defines:
  - channel_id: ai_weekly
    niche: "artificial intelligence and machine learning"
    subreddits: [r/MachineLearning, r/artificial, r/singularity]
    voice_id: "onyx"  # OpenAI TTS voice
    schedule: "0 8 * * 1,4"  # Mon + Thu at 8am
    episode_length_min: 15
    max_cost_per_episode_usd: 5.00
```

**Stage 1 — Topic Discovery (5 min)**
1. Pull top Reddit posts from configured subreddits (past 48h)
2. Fetch trending terms from pytrends for the niche
3. Search Exa.ai for "latest breakthroughs in [niche]"
4. Score each candidate: novelty + engagement + recency
5. Filter against seen-topics database
6. Return top 3 candidates → pick highest scorer

**Stage 2 — Research (10-15 min)**
1. Run 3 Exa.ai neural searches on the topic
2. Retrieve top 8 source URLs
3. Scrape each via Firecrawl (fallback: urllib + BeautifulSoup)
4. Discard sources with no date or no author
5. Send sources to Claude Sonnet with prompt:
   > "Extract the 10 most important factual claims from these sources. For each claim, cite the source URL and note if it appears in multiple sources."
6. Output: `research_bundle.json` with claims + citations

**Stage 3 — Script Writing (5 min)**
Send research bundle to Claude Sonnet with this structure:

```
System: You are a podcast scriptwriter. Write in a conversational, 
engaging tone. Never use bullet points. Cite facts naturally in speech 
("according to researchers at MIT..."). Target [N] minutes at 150 words/minute.

Script sections:
1. HOOK (30 sec) — surprising stat or provocative question
2. INTRO (1 min) — what this episode covers and why it matters
3. SEGMENT 1-4 (3 min each) — deep dive per subtopic
4. SYNTHESIS (2 min) — connect the dots, implications
5. OUTRO (30 sec) — CTA, next episode tease
```

Output: `script.txt` with `[PAUSE]` markers and `[EMPHASIS]` tags for TTS.

**Stage 4 — Fact Checking (3 min)**
Send script back to Claude with research bundle:
> "Flag any claim in this script that is NOT supported by the provided sources. Return a list of flagged sentences and the correction or removal recommendation."

Apply corrections automatically. Log all flags to `fact_check_report.json`.

**Stage 5 — Audio Production (5-10 min)**
1. Split script into segments at `[PAUSE]` markers
2. Send each segment to TTS API → individual `.mp3` files
3. Download royalty-free intro music (pre-selected, stored in repo)
4. Assemble with ffmpeg:
   - Intro music (fade in, 5 sec)
   - Script audio
   - Outro music (fade in at last 10 sec)
5. Normalize to -16 LUFS with pyloudnorm
6. Export as 192kbps MP3

**Stage 6 — Publishing (5 min)**
1. Generate YouTube thumbnail (Pillow: channel art template + episode title text)
2. Generate video: ffmpeg static image + audio
3. Upload to YouTube via Data API:
   - Title: `[Topic] | [Channel Name] #[episode_num]`
   - Description: auto-generated summary + source links
   - Tags: auto-generated from topic
4. Update RSS feed XML with new episode entry
5. Push RSS file to GitHub Pages (git commit + push)
6. Spotify auto-detects RSS update within ~1 hour

Total pipeline runtime: **~30-45 minutes per episode**

---

## 4. Agent Design

### Agent Roles

```
┌─────────────────────────────────────────┐
│             Orchestrator Agent           │
│  - Reads channels.yaml                  │
│  - Triggers child agents in sequence    │
│  - Manages state file per episode       │
│  - Catches errors, triggers retries     │
│  - Enforces cost ceiling                │
└────────────┬───────────────────────────┘
             │
   ┌─────────▼──────────┐    ┌───────────────────┐
   │   Topic Scout      │    │  Research Agent   │
   │  (Claude Haiku)    │───▶│  (Claude Sonnet)  │
   │  - Queries APIs    │    │  - Fetches sources│
   │  - Scores topics   │    │  - Extracts claims│
   └────────────────────┘    └─────────┬─────────┘
                                       │
   ┌─────────────────────┐    ┌────────▼──────────┐
   │  Audio Producer     │    │  Script Writer    │
   │  (Python + APIs)    │◀───│  (Claude Sonnet)  │
   │  - TTS calls        │    │  - Writes script  │
   │  - ffmpeg assembly  │    │  - Fact checks    │
   └──────────┬──────────┘    └───────────────────┘
              │
   ┌──────────▼──────────┐
   │     Publisher       │
   │  (Python + APIs)    │
   │  - YouTube upload   │
   │  - RSS update       │
   └─────────────────────┘
```

### Communication
Agents communicate via shared file system (episode state directory) and a JSON state file. No message broker needed for MVP. At scale, replace with Redis pub/sub or Prefect tasks.

### Error Handling
Each agent follows this contract:
- On success: write output, update state stage, exit 0
- On recoverable error (API timeout): retry up to 3× with exponential backoff
- On fatal error: write error to state file, send alert (email or Slack webhook), halt pipeline for that episode
- Research agent: if fewer than 4 valid sources found, abort with flag `LOW_QUALITY_SOURCES` — do not proceed to script writing

---

## 5. MVP Version (1-2 Week Build)

### Minimal Stack
| Component | Tool |
|---|---|
| Language | Python 3.11 |
| LLM | Claude API (Sonnet + Haiku) |
| Research | Exa.ai API |
| TTS | OpenAI TTS (`tts-1-hd`, voice: `onyx`) |
| Audio assembly | ffmpeg (CLI calls from Python) |
| Publishing | YouTube Data API v3 + GitHub Pages RSS |
| Scheduler | GitHub Actions (cron) |
| Storage | Local filesystem + GitHub repo |

### File Structure
```
automated-podcast/
├── config/
│   └── channels.yaml
├── agents/
│   ├── topic_scout.py
│   ├── researcher.py
│   ├── script_writer.py
│   ├── fact_checker.py
│   ├── audio_producer.py
│   └── publisher.py
├── orchestrator.py          # main entry point
├── state/                   # per-episode JSON state files
├── episodes/                # audio + video output
├── assets/
│   ├── intro.mp3
│   ├── outro.mp3
│   └── thumbnail_template.png
├── rss/
│   └── feed.xml            # pushed to GitHub Pages
├── seen_topics.db          # SQLite
└── .github/workflows/
    └── podcast.yml         # cron trigger
```

### GitHub Actions Trigger
```yaml
name: Podcast Pipeline
on:
  schedule:
    - cron: '0 8 * * 1,4'  # Mon + Thu 8am UTC
  workflow_dispatch:         # manual trigger for testing
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: python orchestrator.py
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          EXA_API_KEY: ${{ secrets.EXA_API_KEY }}
          YOUTUBE_CLIENT_SECRET: ${{ secrets.YOUTUBE_CLIENT_SECRET }}
```

### Cost Per Episode (MVP)
| Component | Cost |
|---|---|
| Claude Sonnet (research + script + fact-check) | ~$0.80 |
| Claude Haiku (topic scoring + metadata) | ~$0.05 |
| Exa.ai (5 searches + 8 retrievals) | ~$0.12 |
| OpenAI TTS (14k chars) | ~$0.42 |
| YouTube API | Free |
| GitHub Actions | Free |
| **Total** | **~$1.40/episode** |

At 2 episodes/week: **~$11/month per channel**

---

## 6. Scaling Strategy

### Multiple Channels
Each channel is a config entry in `channels.yaml`. The orchestrator iterates over all channels and runs them in parallel using Python `multiprocessing` or by spawning concurrent GitHub Actions jobs.

```yaml
channels:
  - id: ai_weekly
    niche: "artificial intelligence"
    schedule: "0 8 * * 1,4"
  - id: space_daily
    niche: "space exploration and astronomy"
    schedule: "0 9 * * *"
  - id: biotech_insights
    niche: "biotech and longevity science"
    schedule: "0 10 * * 2,5"
```

### Cost at Scale
At 10 channels × 3 episodes/week = 30 episodes/week:
- Variable cost: 30 × $1.40 = **$42/week (~$180/month)**
- Fixed infra: GitHub Actions (free up to 2,000 min/month), or Railway ~$10/mo

To reduce cost:
1. Cache research results for 48h — same trending topic may appear across channels
2. Use Claude Haiku for script first draft, Sonnet only for polish pass (saves ~40%)
3. Batch TTS requests; OpenAI TTS has no per-request overhead
4. Pre-generate 10 episodes on weekends during off-peak pricing

### Retention / Virality Optimization
- **Title A/B testing:** Generate 3 title variants with Claude Haiku, pick the one scoring highest on curiosity + specificity heuristics
- **Hook optimization:** Instruct script writer to open with a counterintuitive stat — this is the single biggest driver of watch time
- **Episode length tuning:** Pull YouTube Analytics via API weekly; if average watch time < 40%, shorten episode template
- **SEO metadata:** Claude Haiku generates 15 YouTube tags + ranked description from the script automatically

---

## 7. Risks and Mitigations

### Platform Policy Risks
| Risk | Mitigation |
|---|---|
| YouTube flags AI-generated content | Disclose AI assistance in description (required by YT policy). Use custom voice, not obvious robot TTS. |
| Spotify rejects RSS feed | Follow Spotify podcast RSS spec exactly. Use validated XML. |
| YouTube account strike for low-quality content | Start with unlisted episodes; manually review first 5 before going public. |

### AI Content Detection
YouTube and Spotify do not currently penalize AI-written scripts if the content is accurate and provides value. The risk is quality, not detection. Mitigate by:
- Grounding every claim in a cited source
- Never fabricating quotes
- Maintaining a consistent editorial voice per channel

### Quality Control
| Issue | Mitigation |
|---|---|
| Hallucinated facts | Fact checker agent re-verifies every claim against source bundle. Flag rate logged per episode. |
| Low-quality sources | Minimum 4 sources required; domain trust list enforced; no sources older than 30 days for news niches. |
| Monotone TTS audio | Add `[PAUSE 0.5s]` markers, vary sentence length in script writer prompt, use voice with higher expressiveness setting. |
| Repetitive episode formats | Rotate 3 script templates (narrative, interview-style monologue, listicle deep-dive). |

### Legal and Copyright
| Risk | Mitigation |
|---|---|
| Quoting copyrighted text verbatim | Script writer prompt explicitly forbids direct quotes > 50 words. Paraphrase with attribution. |
| Background music copyright | Use only CC0 or royalty-free licensed music from Pixabay, ccMixter, or Freesound. Store license files with assets. |
| Scraping terms of service violations | Use Exa.ai and official APIs where possible. Firecrawl for everything else — it handles ToS compliance. |
| Research paper paraphrasing | arXiv papers are open access. Link to paper in episode description. |

---

## 8. Build Sequence (2-Week Sprint)

### Week 1
- Day 1-2: Set up project structure, API keys, channels.yaml schema
- Day 3: Build topic_scout.py (Exa + Reddit + scoring)
- Day 4: Build researcher.py (Exa retrieval + Firecrawl + trust filter)
- Day 5: Build script_writer.py + fact_checker.py (Claude prompts)

### Week 2
- Day 1: Build audio_producer.py (OpenAI TTS + ffmpeg pipeline)
- Day 2: Build publisher.py (YouTube API + RSS XML update)
- Day 3: Wire orchestrator.py + state machine
- Day 4: GitHub Actions setup + first end-to-end test run
- Day 5: Review first episode output, tune prompts, set live schedule

### Definition of "Done" for MVP
- [ ] One episode produced end-to-end without manual intervention
- [ ] Episode published to YouTube (unlisted) and RSS feed
- [ ] Pipeline recovers from a simulated TTS API failure
- [ ] Cost per episode verified under $3.00
- [ ] Seen-topics database prevents repeat topics

---

## 9. Suggested Prompt Templates

### Research Extraction Prompt
```
You are a research analyst. The following are raw text extracts from web sources on the topic: "{topic}".

Your job:
1. Extract the 10 most important, verifiable factual claims
2. For each claim: state it clearly, note which source URL it came from, and rate confidence (HIGH/MEDIUM/LOW)
3. Discard any claims that are opinions, predictions without evidence, or unsourced
4. Flag any contradictions between sources

Output as JSON: [{claim, source_url, confidence, notes}]
```

### Script Writing Prompt
```
You are a podcast scriptwriter for the channel "{channel_name}" covering {niche}.

Write a {length}-minute podcast script using ONLY the verified facts in the research bundle below.
- Tone: conversational, curious, never academic
- Never use bullet points or lists in the spoken script
- Cite sources naturally: "researchers at Stanford found...", "according to Nature..."
- Open with a hook: one surprising fact or provocative question
- End each segment with a transition sentence to the next
- Add [PAUSE 0.5s] between paragraphs and [PAUSE 1s] between segments

Research bundle:
{research_bundle}

Episode structure:
- HOOK (30s)
- INTRO (60s)  
- SEGMENT_1: {subtopic_1} (3 min)
- SEGMENT_2: {subtopic_2} (3 min)
- SEGMENT_3: {subtopic_3} (3 min)
- SYNTHESIS (2 min)
- OUTRO with CTA (30s)
```

---

*This document covers the complete system design. Start with the MVP stack, validate quality and cost on one channel, then replicate channels.*

#!/usr/bin/env -S uv run --quiet --with youtube-transcript-api
"""Extract YouTube video transcript and output as JSON."""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import os


def clean_text(text):
    """Remove non-speech markers like [Music], [Applause], etc."""
    text = re.sub(r'\[(?:Music|Applause|Laughter|Cheering|Silence)\]', '', text)
    text = re.sub(r'♪[^♪]*♪', '', text)
    text = re.sub(r'♪', '', text)
    return text.strip()


def merge_snippets(snippets, pause_threshold=2.0):
    """Merge transcript snippets into paragraphs based on pauses."""
    if not snippets:
        return ""

    paragraphs = []
    current = []

    for i, snippet in enumerate(snippets):
        text = clean_text(snippet.text.replace('\n', ' '))
        if not text:
            continue
        current.append(text)

        if i + 1 < len(snippets):
            end_time = snippet.start + snippet.duration
            next_start = snippets[i + 1].start
            gap = next_start - end_time

            if gap > pause_threshold:
                paragraphs.append(' '.join(current))
                current = []

    if current:
        paragraphs.append(' '.join(current))

    return '\n\n'.join(paragraphs)


def estimate_duration(snippets):
    """Estimate video duration from last snippet timing."""
    if not snippets:
        return 0.0
    last = snippets[-1]
    return round((last.start + last.duration) / 60.0, 1)


def pick_best_transcript(transcript_list):
    """Pick the best transcript: prefer manual over auto-generated."""
    manual = [t for t in transcript_list if not t.is_generated]
    generated = [t for t in transcript_list if t.is_generated]

    if manual:
        return manual[0]
    if generated:
        return generated[0]
    return None


def fetch_with_api(video_id):
    """Primary: use youtube-transcript-api."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        TranscriptsDisabled,
        NoTranscriptFound,
        VideoUnavailable,
    )

    try:
        from youtube_transcript_api._errors import RequestBlocked
    except ImportError:
        RequestBlocked = None

    try:
        from youtube_transcript_api._errors import IpBlocked
    except ImportError:
        IpBlocked = None

    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)

    best = pick_best_transcript(transcript_list)
    if best is None:
        return {"status": "error", "error_type": "no_captions",
                "message": "Субтитры не найдены для этого видео"}

    fetched = best.fetch()
    snippets = fetched.snippets
    text = merge_snippets(snippets)
    duration = estimate_duration(snippets)
    word_count = len(text.split())

    return {
        "status": "ok",
        "video_id": video_id,
        "language": best.language_code,
        "is_generated": best.is_generated,
        "duration_minutes": duration,
        "word_count": word_count,
        "text": text,
    }


def fetch_with_ytdlp(video_id):
    """Fallback: use yt-dlp for subtitle extraction."""
    if not shutil.which('yt-dlp'):
        return None

    tmpdir = tempfile.mkdtemp(prefix='tldr-')
    try:
        url = f'https://www.youtube.com/watch?v={video_id}'
        cmd = [
            'yt-dlp',
            '--skip-download',
            '--write-subs',
            '--write-auto-subs',
            '--sub-format', 'json3',
            '--sub-langs', 'all',
            '-o', os.path.join(tmpdir, '%(id)s'),
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        sub_files = [f for f in os.listdir(tmpdir) if f.endswith('.json3')]
        if not sub_files:
            return None

        # Prefer non-auto-generated (shorter filename typically)
        # Manual subs: VIDEO_ID.LANG.json3
        # Auto subs: VIDEO_ID.LANG.json3 (yt-dlp names them similarly)
        sub_files.sort(key=len)
        sub_file = os.path.join(tmpdir, sub_files[0])

        with open(sub_file) as f:
            data = json.load(f)

        # Parse json3 format
        segments = []
        for event in data.get('events', []):
            if 'segs' not in event:
                continue
            text = ''.join(seg.get('utf8', '') for seg in event['segs']).strip()
            text = clean_text(text.replace('\n', ' '))
            if text:
                segments.append(text)

        text = '\n\n'.join(segments) if segments else ''
        word_count = len(text.split())

        # Extract language from filename
        parts = sub_files[0].rsplit('.', 2)
        language = parts[-2] if len(parts) >= 3 else 'unknown'

        return {
            "status": "ok",
            "video_id": video_id,
            "language": language,
            "is_generated": True,
            "duration_minutes": 0.0,
            "word_count": word_count,
            "text": text,
        }
    except (subprocess.TimeoutExpired, Exception):
        return None
    finally:
        import shutil as sh
        sh.rmtree(tmpdir, ignore_errors=True)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "status": "error",
            "error_type": "invalid_id",
            "message": "Не указан video_id. Использование: get_transcript.py <video_id>"
        }))
        sys.exit(1)

    video_id = sys.argv[1]

    # Validate video_id format
    if not re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
        print(json.dumps({
            "status": "error",
            "error_type": "invalid_id",
            "message": f"Невалидный video_id: {video_id}"
        }))
        sys.exit(1)

    # Try primary method: youtube-transcript-api
    try:
        result = fetch_with_api(video_id)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0 if result["status"] == "ok" else 1)

    except ImportError:
        # youtube-transcript-api not installed
        pass

    except Exception as e:
        error_type = "network"
        message = str(e)

        exc_name = type(e).__name__
        if exc_name in ('TranscriptsDisabled', 'NoTranscriptFound'):
            error_type = "no_captions"
            message = "Субтитры отключены или не найдены для этого видео"
        elif exc_name == 'VideoUnavailable':
            error_type = "invalid_id"
            message = "Видео недоступно"
        elif exc_name in ('RequestBlocked', 'IpBlocked'):
            error_type = "blocked"
            message = f"YouTube заблокировал запрос ({exc_name}). Попробуй позже или используй VPN."

        # Try yt-dlp fallback before giving up
        ytdlp_result = fetch_with_ytdlp(video_id)
        if ytdlp_result and ytdlp_result.get("word_count", 0) > 0:
            print(json.dumps(ytdlp_result, ensure_ascii=False))
            sys.exit(0)

        print(json.dumps({
            "status": "error",
            "error_type": error_type,
            "message": message,
        }))
        sys.exit(1)

    # If youtube-transcript-api was not available, try yt-dlp
    ytdlp_result = fetch_with_ytdlp(video_id)
    if ytdlp_result and ytdlp_result.get("word_count", 0) > 0:
        print(json.dumps(ytdlp_result, ensure_ascii=False))
        sys.exit(0)

    print(json.dumps({
        "status": "error",
        "error_type": "missing_deps",
        "message": "Не установлен youtube-transcript-api. Выполни: pip install youtube-transcript-api",
    }))
    sys.exit(1)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""yt-transcript.py <video_id> [--lang en,ru,pl] — транскрипт YouTube-видео как JSON.

Обёртка для канала youtube (/full-research, /search-community) вместо прямого вызова
get_transcript.py плагина youtube-tldr:
  1. сначала get_transcript.py плагина (youtube-transcript-api — один запрос, быстро);
  2. при blocked/network/любой ошибке — yt-dlp: `-J` (метаданные + список субтитров),
     выбор ОДНОГО трека (manual в предпочтённом языке → manual любой → auto *-orig →
     auto предпочтённый), затем загрузка только его в json3.
Почему не фоллбэк самого плагина: там `--sub-langs all` (150+ авто-переводов) при
timeout=30 → TimeoutExpired → None (сверено 2026-08-26). youtube-transcript-api даёт
IpBlocked ИНТЕРМИТТЕНТНО и через VPN, и с домашнего IP (bound-тест en0), yt-dlp — работает везде.

stdout: JSON {status, video_id, source, language, is_generated, duration_minutes,
              word_count, text, title, channel, upload_date, view_count}
exit 0 = ok, 1 = ошибка ({status:"error", error_type, message}).
ENV: YT_TRANSCRIPT_FORCE_YTDLP=1 — пропустить плагин (окно массового IpBlocked / тест пути yt-dlp).
Если плагин вернул трек не из --lang (TED: первый manual = 'ar'), трек перевыбирается через yt-dlp.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

PLUGIN_PY = os.path.expanduser('~/.claude/plugins/data/tldr-youtube-tldr-plugin/venv/bin/python3')
PLUGIN_SCRIPT = os.path.expanduser(
    '~/.claude/plugins/marketplaces/youtube-tldr-plugin/skills/tldr/scripts/get_transcript.py')
DEFAULT_LANGS = ['en', 'ru', 'pl']
PAUSE_THRESHOLD = 2.0


def clean_text(text):
    text = re.sub(r'\[(?:Music|Applause|Laughter|Cheering|Silence|Музыка|Аплодисменты|Смех)\]', '', text)
    text = re.sub(r'♪[^♪]*♪', '', text)
    return text.replace('♪', '').strip()


def merge_events(events):
    """json3 events → абзацы по паузам > PAUSE_THRESHOLD (как в плагине)."""
    items = []
    for ev in events:
        if 'segs' not in ev:
            continue
        text = clean_text(''.join(s.get('utf8', '') for s in ev['segs']).replace('\n', ' '))
        if not text:
            continue
        start = ev.get('tStartMs', 0) / 1000.0
        dur = ev.get('dDurationMs', 0) / 1000.0
        items.append((start, dur, text))
    paragraphs, cur = [], []
    for i, (start, dur, text) in enumerate(items):
        cur.append(text)
        if i + 1 < len(items) and items[i + 1][0] - (start + dur) > PAUSE_THRESHOLD:
            paragraphs.append(' '.join(cur))
            cur = []
    if cur:
        paragraphs.append(' '.join(cur))
    return '\n\n'.join(paragraphs)


def lang_ok(lang, prefs):
    lang = (lang or '').lower()
    return any(lang == p or lang.startswith(p + '-') for p in prefs)


def parse_vtt(raw):
    """WebVTT → текст (без разбивки по паузам; дедуп подряд идущих строк авто-сабов)."""
    lines, seen_last = [], None
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln or ln == 'WEBVTT' or '-->' in ln or ln.isdigit() or ln.startswith(('NOTE', 'Kind:', 'Language:')):
            continue
        ln = re.sub(r'<[^>]+>', '', ln)  # inline-теги таймингов
        ln = clean_text(ln)
        if ln and ln != seen_last:
            lines.append(ln)
            seen_last = ln
    return ' '.join(lines)


def parse_srv3(raw):
    """srv3 (XML timedtext) → текст."""
    import html as _html
    parts = re.findall(r'<p[^>]*>(.*?)</p>', raw, re.S)
    out = []
    for p in parts:
        t = _html.unescape(re.sub(r'<[^>]+>', '', p))
        t = clean_text(t.replace('\n', ' '))
        if t:
            out.append(t)
    return ' '.join(out)


def download_subs(url, key, generated, tmp_prefix, retries=2):
    """Скачать один трек субтитров через yt-dlp с ретраем на 429 и перебором форматов.
    Возвращает (text|None, err|None). json3 разбивается по паузам; srv3/vtt — плоский текст."""
    import time
    for fmt in ('json3', 'srv3', 'vtt'):
        for attempt in range(retries):
            tmp = tempfile.mkdtemp(prefix=tmp_prefix)
            try:
                cmd = ['yt-dlp', '--skip-download', '--write-auto-subs' if generated else '--write-subs',
                       '--sub-langs', key, '--sub-format', fmt, '-o', os.path.join(tmp, '%(id)s'), url]
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                except subprocess.TimeoutExpired:
                    return None, 'yt-dlp download subs: таймаут 120 с'
                files = [f for f in os.listdir(tmp) if f.endswith('.' + fmt)]
                if files:
                    raw = open(os.path.join(tmp, files[0]), encoding='utf-8').read()
                    if fmt == 'json3':
                        text = merge_events(json.loads(raw).get('events', []))
                    elif fmt == 'srv3':
                        text = parse_srv3(raw)
                    else:
                        text = parse_vtt(raw)
                    if text.strip():
                        return text, None
                    break  # формат отдал пустоту — пробуем следующий, не ретраим
                if '429' in (r.stderr or '') or 'Too Many Requests' in (r.stderr or ''):
                    if attempt + 1 < retries:
                        time.sleep(3 * (attempt + 1))
                        continue
                    break  # 429 не ушёл — пробуем другой формат
                break  # иная причина отсутствия файла — следующий формат
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    return None, f'yt-dlp не смог скачать субтитры трека {key} (429/пусто во всех форматах json3/srv3/vtt)'


def err(error_type, message, code=1):
    print(json.dumps({'status': 'error', 'error_type': error_type, 'message': message}, ensure_ascii=False))
    sys.exit(code)


def try_plugin(video_id):
    if not (os.path.exists(PLUGIN_PY) and os.path.exists(PLUGIN_SCRIPT)):
        return None, None
    try:
        r = subprocess.run([PLUGIN_PY, PLUGIN_SCRIPT, video_id], capture_output=True, text=True, timeout=60)
        d = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None
    except Exception:
        return None, None
    if d and d.get('status') == 'ok' and d.get('word_count', 0) > 1:
        d['source'] = 'youtube-transcript-api'
        return d, None
    return None, (d if isinstance(d, dict) and d.get('status') == 'error' else None)


def pick_track(info, prefs):
    manual = info.get('subtitles') or {}
    auto = info.get('automatic_captions') or {}

    def by_pref(keys):
        for p in prefs:
            for k in keys:
                if k == p or k.startswith(p + '-'):
                    return k
        return None

    k = by_pref(manual.keys())
    if k:
        return k, False
    if manual:
        return sorted(manual.keys())[0], False
    orig = [k for k in auto if k.endswith('-orig')]
    if orig:
        return orig[0], True
    k = by_pref(auto.keys())
    if k:
        return k, True
    if auto:
        return sorted(auto.keys())[0], True
    return None, None


def try_ytdlp(video_id, prefs):
    if not shutil.which('yt-dlp'):
        return None, 'yt-dlp не установлен (brew install yt-dlp)'
    url = f'https://www.youtube.com/watch?v={video_id}'
    try:
        r = subprocess.run(['yt-dlp', '--skip-download', '-J', url], capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return None, 'yt-dlp -J: таймаут 90 с'
    if r.returncode != 0 or not r.stdout.strip():
        tail = ((r.stderr or '').strip().splitlines()[-1:] or [''])[0]
        low = tail.lower()
        if any(k in low for k in ('unavailable', 'private video', 'does not exist', 'removed', 'not available')):
            return {'status': 'error', 'error_type': 'unavailable', 'message': f'Видео недоступно: {tail[:200]}'}, None
        return None, f'yt-dlp -J failed: {tail[:200]}'
    info = json.loads(r.stdout)
    key, generated = pick_track(info, prefs)
    if key is None:
        return {'status': 'error', 'error_type': 'no_captions', 'message': 'Субтитры не найдены для этого видео'}, None
    # Скачивание трека субтитров. YouTube лимитирует timedtext-эндпоинт (HTTP 429)
    # при частых запросах — ретраим с backoff и перебором форматов (json3 паузами
    # держит абзацы; srv3/vtt — фоллбэк без разбивки, для авто-сабов приемлемо).
    text, why = download_subs(url, key, generated, tmp_prefix='yt-transcript-')
    if text is None:
        return None, why
    dur = info.get('duration') or 0
    return {
        'status': 'ok', 'video_id': video_id, 'source': 'yt-dlp',
        'language': key, 'is_generated': bool(generated),
        'duration_minutes': round(dur / 60.0, 1), 'word_count': len(text.split()), 'text': text,
        'title': info.get('title'), 'channel': info.get('channel') or info.get('uploader'),
        'upload_date': info.get('upload_date'), 'view_count': info.get('view_count'),
    }, None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    prefs = DEFAULT_LANGS
    for a in sys.argv[1:]:
        if a.startswith('--lang='):
            prefs = [x.strip() for x in a.split('=', 1)[1].split(',') if x.strip()]
    if '--lang' in sys.argv:
        i = sys.argv.index('--lang')
        if i + 1 < len(sys.argv):
            prefs = [x.strip() for x in sys.argv[i + 1].split(',') if x.strip()]
            args = [a for a in args if a != sys.argv[i + 1]]
    if not args:
        err('invalid_id', 'Использование: yt-transcript.py <video_id> [--lang en,ru]')
    video_id = args[0]
    if not re.match(r'^[A-Za-z0-9_-]{11}$', video_id):
        err('invalid_id', f'Невалидный video_id: {video_id}')

    force = os.environ.get('YT_TRANSCRIPT_FORCE_YTDLP') == '1'
    d, plugin_err = (None, None) if force else try_plugin(video_id)
    if d and not lang_ok(d.get('language'), prefs):
        # плагин берёт ПЕРВЫЙ manual-трек (у TED это бывает 'ar') — перевыбираем по prefs через yt-dlp
        d2, _ = try_ytdlp(video_id, prefs)
        if d2 and d2.get('status') == 'ok' and lang_ok(d2.get('language'), prefs):
            d = d2
    if d:
        print(json.dumps(d, ensure_ascii=False))
        return
    d, why = try_ytdlp(video_id, prefs)
    if d is None:
        # yt-dlp тоже не смог: если плагин дал содержательную ошибку (не блок) — отдаём её
        if plugin_err and plugin_err.get('error_type') not in (None, 'blocked', 'network'):
            err(plugin_err['error_type'], plugin_err.get('message', ''))
        err('blocked_or_network', f'youtube-transcript-api: {(plugin_err or {}).get("error_type", "n/a")}; {why}')
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0 if d.get('status') == 'ok' else 1)


if __name__ == '__main__':
    main()

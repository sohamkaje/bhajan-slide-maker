"""Download and search the Sai Rhythms devotional-song catalogue."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from html import unescape
from pathlib import Path

API_URL = "https://sairhythms.sathyasai.org/song/signup/api"
SONG_SITE = "https://sairhythms.sathyasai.org"
MISSING_LYRICS = "<CANNOT FIND LYRICS ON SAIRHYTHMS; INPUT HERE>"
CACHE_DAYS = 7

# Safe transliteration folds applied to both the query and the catalogue.
TOKEN_FOLDS = {
    "bhajorey": "bhajare",
    "bhajore": "bhajare",
    "bhajarey": "bhajare",
    "hrdaya": "hridaya",
    "hrudaya": "hridaya",
    "hriday": "hridaya",
    "shanthi": "shanti",
    "shanthihi": "shanti",
    "shri": "sri",
    "shree": "sri",
    "shyam": "shyama",
    "nath": "natha",
    "ganapathi": "ganapati",
    "ganapathy": "ganapati",
    "vinayak": "vinayaka",
    "gopalaa": "gopala",
}


@dataclass
class SongHit:
    query: str
    title: str
    lyrics: str
    meaning: str
    url: str
    score: float
    found: bool
    note: str = ""


def _songs_from_file(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    songs = payload["songs"]
    _prepare(songs)
    return songs


def _cache_is_fresh(path: Path) -> bool:
    if not path.is_file():
        return False
    age = time.time() - path.stat().st_mtime
    return age < CACHE_DAYS * 86400


def load_songs(cache_path: Path, refresh: bool = False, bundled_path: Path | None = None) -> list[dict]:
    """Load the catalogue from a writable cache, a shipped copy, or Sai Rhythms.

    Vercel cannot write inside the deployed app, so a fresh bundled file is used
    as-is. A newer download is saved only when the cache folder can be written.
    """
    bundled = bundled_path if bundled_path and bundled_path.is_file() else None
    if not refresh and _cache_is_fresh(cache_path):
        return _songs_from_file(cache_path)
    if not refresh and bundled is not None and _cache_is_fresh(bundled):
        return _songs_from_file(bundled)

    try:
        request = urllib.request.Request(
            API_URL,
            data=b"action=load_resource&resource=search",
            headers={
                "User-Agent": "Mozilla/5.0 (bhajan-slide-maker)",
                "Referer": SONG_SITE + "/",
                "Origin": SONG_SITE,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            outer = json.loads(response.read().decode("utf-8"))
        if "data" not in outer:
            raise RuntimeError(outer.get("error") or "Sai Rhythms did not return a song list.")
        songs = json.loads(outer["data"])
    except Exception:
        if bundled is not None:
            return _songs_from_file(bundled)
        if cache_path.is_file():
            return _songs_from_file(cache_path)
        raise

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"resource_version": outer.get("resource_version"), "songs": songs}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    _prepare(songs)
    return songs


def match_bhajan(query: str, songs: list[dict]) -> SongHit:
    q_norm = _normalize(query)
    pool = _candidates(songs, q_norm)
    best, second = _rank(q_norm, pool)
    if (best is None or best[0] < 82) and len(pool) != len(songs):
        best, second = _rank(q_norm, songs)
    if best is None or best[0] < 82:
        return SongHit(
            query=query,
            title=query,
            lyrics=MISSING_LYRICS,
            meaning="",
            url="",
            score=0 if best is None else best[0],
            found=False,
        )

    song = best[2]
    lyrics = _full_lyrics(song)
    if not lyrics:
        return SongHit(
            query=query,
            title=song.get("title") or query,
            lyrics=MISSING_LYRICS,
            meaning="",
            url=_song_url(song),
            score=best[0],
            found=False,
            note="Song page has no lyrics",
        )

    note = ""
    exact = (song.get("_title_norm") or "") == q_norm
    if second and second[0] >= 82 and best[0] - second[0] <= 3:
        other = second[1]
        same_title = (other.get("_title_norm") or "") == (song.get("_title_norm") or "")
        if same_title:
            other_line = _opening_line(other)
            note = f"Another version on Sai Rhythms starts: {other_line}"
        elif not exact:
            note = f"Also similar: {other.get('title')}"
    return SongHit(
        query=query,
        title=(song.get("title") or query).strip(),
        lyrics=lyrics,
        meaning=html_to_text(song.get("meaning") or ""),
        url=_song_url(song),
        score=best[0],
        found=True,
        note=note,
    )


def apply_song_page(hit: SongHit, cache_dir: Path) -> SongHit:
    """Replace catalogue text with the lyrics and meaning shown on the song page."""
    if not hit.found or not hit.url:
        return hit
    slug = hit.url.rstrip("/").rsplit("/", 1)[-1]
    cache_file = cache_dir / "pages" / f"{slug}.json"
    try:
        if cache_file.exists():
            saved = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            request = urllib.request.Request(
                hit.url,
                headers={
                    "User-Agent": "Mozilla/5.0 (bhajan-slide-maker)",
                    "Referer": SONG_SITE + "/",
                    "Accept": "text/html",
                },
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                html = response.read().decode("utf-8", "replace")
            lyrics, meaning = lyrics_from_page(html)
            saved = {"lyrics": lyrics, "meaning": meaning, "url": hit.url}
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return hit
    if saved.get("lyrics"):
        hit.lyrics = saved["lyrics"]
    if saved.get("meaning"):
        hit.meaning = saved["meaning"]
    return hit


def lyrics_from_page(html: str) -> tuple[str, str]:
    """Read the primary lyric block and the meaning from a Sai Rhythms song page."""
    block = re.search(r"<div class='lyrics-set'>(.*?)</div>", html, re.S)
    lines: list[str] = []
    if block:
        for _kind, raw in re.findall(
            r"<div class='(song-first-line|song-line)'>(.*?)</div>",
            block.group(1),
            re.S,
        ):
            line = html_to_text(raw)
            if line:
                lines.append(line)
    meaning = ""
    meaning_block = re.search(
        r"<div class='devotional-song-meaning[^']*'>(.*?)</div>",
        html,
        re.S,
    )
    if meaning_block:
        meaning = html_to_text(meaning_block.group(1))
    return "\n".join(lines), meaning


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", " ", value)
    text = re.sub(r"(?i)</p\s*>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _opening_line(song: dict) -> str:
    raw = (song.get("title2") or song.get("title") or "").strip()
    return re.sub(r"\s+", " ", raw)


def _lyric_richness(song: dict) -> int:
    return len(lyric_lines(song.get("lyrics") or "")) + (1 if _opening_line(song) else 0)


def _full_lyrics(song: dict) -> str:
    body = (song.get("lyrics") or "").strip()
    if not body and song.get("alt_lyrics"):
        alt = song["alt_lyrics"]
        body = (alt[0] if isinstance(alt, list) else str(alt)).strip()
    lines = lyric_lines(body)
    opening = _opening_line(song)
    if opening:
        opening_norm = _normalize(opening)
        first_norm = _normalize(lines[0]) if lines else ""
        already = first_norm == opening_norm or first_norm.startswith(opening_norm)
        if not already:
            lines = [opening, *lines]
    return "\n".join(lines)


def lyric_lines(lyrics: str) -> list[str]:
    lines = []
    for line in lyrics.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


_CATALOGUE: dict[int, tuple[dict[str, list[int]], dict[str, list[int]]]] = {}


def _prepare(songs: list[dict]) -> None:
    token_index: dict[str, list[int]] = {}
    prefix_index: dict[str, list[int]] = {}
    for index, song in enumerate(songs):
        song["_title_norm"] = _normalize(song.get("title") or "")
        song["_title2_norm"] = _normalize(song.get("title2") or "")
        first = lyric_lines(song.get("lyrics") or "")
        song["_first_norm"] = _normalize(first[0]) if first else ""
        tokens: set[str] = set()
        for field in (song["_title_norm"], song["_title2_norm"], song["_first_norm"]):
            tokens.update(field.split())
        for token in tokens:
            token_index.setdefault(token, []).append(index)
            if len(token) >= 4:
                prefix_index.setdefault(token[:4], []).append(index)
    _CATALOGUE[id(songs)] = (token_index, prefix_index)


def _candidates(songs: list[dict], query_norm: str) -> list[dict]:
    indexes = _CATALOGUE.get(id(songs))
    if not indexes:
        return songs
    token_index, prefix_index = indexes
    chosen: set[int] = set()
    for token in query_norm.split():
        chosen.update(token_index.get(token, ()))
        if len(token) >= 4:
            chosen.update(prefix_index.get(token[:4], ()))
    if not chosen:
        return songs
    return [songs[index] for index in chosen]


def _rank(query_norm: str, songs: list[dict]) -> tuple[tuple[float, int, dict] | None, tuple[float, dict] | None]:
    best: tuple[float, int, dict] | None = None
    second: tuple[float, dict] | None = None
    for song in songs:
        score = _song_score(query_norm, song)
        richness = _lyric_richness(song)
        if best is None or score > best[0] + 0.01 or (
            abs(score - best[0]) <= 0.01 and richness > best[1]
        ):
            if best is not None:
                second = (best[0], best[2])
            best = (score, richness, song)
        elif second is None or score > second[0]:
            second = (score, song)
    return best, second


@lru_cache(maxsize=100000)
def _ratio(left: str, right: str) -> float:
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _song_url(song: dict) -> str:
    url = song.get("url") or ""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return SONG_SITE + url


def _normalize(value: str) -> str:
    text = value.lower().replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return " ".join(TOKEN_FOLDS.get(token, token) for token in text.split())


def _song_score(query_norm: str, song: dict) -> float:
    if not query_norm:
        return 0
    title_score = _text_score(query_norm, song.get("_title_norm") or "")
    title2_score = _text_score(query_norm, song.get("_title2_norm") or "")
    first_score = _text_score(query_norm, song.get("_first_norm") or "") * 0.98
    return max(title_score, title2_score, first_score)


def _text_score(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0
    if query == candidate:
        return 100
    q_tokens = query.split()
    c_tokens = candidate.split()
    recall = _token_recall(q_tokens, c_tokens)
    ratio = _ratio(query, candidate)
    coverage = len(q_tokens) / len(c_tokens)
    prefix = 0.0
    if candidate.startswith(query):
        prefix = 0.78 + 0.22 * coverage
    elif query.startswith(candidate) and len(candidate) / len(query) >= 0.72:
        prefix = 0.84
    ordered = _tokens_in_order(q_tokens, c_tokens)
    score = max(ratio, prefix, (0.82 * recall + 0.18 * ratio))
    if ordered and recall >= 0.8:
        score = max(score, (0.74 + 0.26 * coverage) * recall)
    # A single word such as "AUM" is the opening slide, not a lyric search.
    if len(q_tokens) == 1:
        score = min(score, 0.70)
    if recall < 0.67 and prefix < 0.84 and ratio < 0.86:
        score = min(score, 0.7)
    return score * 100


def _token_recall(needles: list[str], haystack: list[str]) -> float:
    if not needles or not haystack:
        return 0
    used: set[int] = set()
    total = 0.0
    for needle in needles:
        best_i = -1
        best_r = 0.0
        for index, token in enumerate(haystack):
            if index in used:
                continue
            ratio = _ratio(needle, token)
            if ratio > best_r:
                best_r = ratio
                best_i = index
        if best_r >= 0.86:
            total += best_r
            used.add(best_i)
    return total / len(needles)


def _tokens_in_order(needles: list[str], haystack: list[str]) -> bool:
    index = 0
    for needle in needles:
        found = False
        while index < len(haystack):
            token = haystack[index]
            index += 1
            ratio = _ratio(needle, token)
            if ratio >= 0.86:
                found = True
                break
        if not found:
            return False
    return True


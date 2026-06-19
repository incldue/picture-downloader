# -*- coding: utf-8 -*-

import math
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

import requests
from PIL import Image, ImageStat

from .config import (
    MATCH_WORKERS,
    MAX_IMAGE_BYTES,
    MIN_IMAGE_HEIGHT,
    MIN_IMAGE_WIDTH,
    REQUEST_TIMEOUT,
    VISUAL_MATCH_ENABLED,
    WALLHAVEN_PROXY,
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

PREVIEW_THUMBNAIL_CACHE_SIZE = (320, 320)

_SESSION_LOCAL = threading.local()


def _request_session():
    session = getattr(_SESSION_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        _SESSION_LOCAL.session = session
    return session


cv2 = None
np = None
_OPTIONAL_CV_LOADED = False
_OPTIONAL_CV_LOCK = threading.Lock()


def _load_optional_cv():
    """Load OpenCV/Numpy only when visual features actually need them."""
    global cv2, np, _OPTIONAL_CV_LOADED
    if _OPTIONAL_CV_LOADED:
        return cv2, np

    with _OPTIONAL_CV_LOCK:
        if _OPTIONAL_CV_LOADED:
            return cv2, np

        try:
            import cv2 as cv2_mod  # type: ignore
        except Exception:
            cv2_mod = None

        try:
            import numpy as np_mod  # type: ignore
        except Exception:
            np_mod = None

        cv2 = cv2_mod
        np = np_mod
        _OPTIONAL_CV_LOADED = True
        return cv2, np


COLOR_TERMS = {
    "红": "red",
    "红色": "red",
    "red": "red",
    "蓝": "blue",
    "蓝色": "blue",
    "blue": "blue",
    "绿": "green",
    "绿色": "green",
    "green": "green",
    "黄": "yellow",
    "黄色": "yellow",
    "yellow": "yellow",
    "黑": "black",
    "黑色": "black",
    "black": "black",
    "白": "white",
    "白色": "white",
    "white": "white",
    "粉": "pink",
    "粉色": "pink",
    "pink": "pink",
    "紫": "purple",
    "紫色": "purple",
    "purple": "purple",
    "橙": "orange",
    "橙色": "orange",
    "orange": "orange",
    "灰": "gray",
    "灰色": "gray",
    "grey": "gray",
    "gray": "gray",
    "棕": "brown",
    "棕色": "brown",
    "brown": "brown",
}

FACE_TERMS = {
    "人",
    "人物",
    "人像",
    "头像",
    "脸",
    "面部",
    "美女",
    "帅哥",
    "portrait",
    "person",
    "people",
    "face",
    "headshot",
}

LOCAL_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}


def is_reference_image_query(keyword):
    path = os.path.expanduser(keyword.strip().strip("\"'"))
    _, ext = os.path.splitext(path)
    return bool(ext.lower() in LOCAL_IMAGE_EXTS and os.path.isfile(path))


def keyword_tokens(keyword):
    keyword = keyword.strip().lower()
    if not keyword:
        return []
    tokens = [keyword]
    tokens.extend(re.findall(r"[a-z0-9_+-]+", keyword, flags=re.I))
    tokens.extend(re.findall(r"[\u4e00-\u9fff]{1,}", keyword))
    seen = set()
    out = []
    for token in tokens:
        token = token.strip().lower()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _item_text(item):
    parts = [
        item.get("title", ""),
        item.get("source", ""),
        item.get("url", ""),
        item.get("thumb", ""),
        item.get("page_url", ""),
    ]
    tags = item.get("tags") or []
    if isinstance(tags, (list, tuple)):
        parts.extend(str(t) for t in tags)
    else:
        parts.append(str(tags))
    return " ".join(str(x) for x in parts if x).lower()


def metadata_score(item, keyword):
    tokens = keyword_tokens(keyword)
    if not tokens:
        return 0.0

    text = _item_text(item)
    score = 0.35  # Search engines already used the query; keep this as a weak prior.
    if str(item.get("_query", "")).strip().lower() == keyword.strip().lower():
        score += 0.75

    try:
        site_confidence = float(
            item.get("bing_confidence", 0) or item.get("wallpaperscraft_confidence", 0)
        )
        if site_confidence > 0:
            score += min(1.8, site_confidence / 100.0 * 1.8)
    except Exception:
        pass

    try:
        rank = int(item.get("_rank", 9999))
        if rank > 0:
            score += max(0.0, 0.9 - min(rank, 120) / 160.0)
    except Exception:
        pass

    full = tokens[0]
    if full and full in text:
        score += 1.2
    for token in tokens[1:]:
        if len(token) >= 2 and token in text:
            score += 0.35
    source = str(item.get("source", "")).lower()
    cap = 4.2 if source in ("bing", "wallpaperscraft") else 2.6
    return min(score, cap)


def _request_headers(item):
    headers = dict(HEADERS)
    token = item.get("_token")
    if token:
        headers["token"] = token
    referer = item.get("referer") or item.get("_referer") or item.get("page_url")
    if referer:
        if str(item.get("source", "")).lower() in ("bing", "wallpaperscraft"):
            headers["referer"] = referer
        else:
            headers["Referer"] = referer
    return headers


def fetch_image_bytes(item):
    headers = _request_headers(item)
    source = str(item.get("source", "")).lower()
    urls = []
    preview_url = item.get("_preview_url")
    if preview_url:
        urls.append(preview_url)
    if source in ("bing", "wallpaperscraft"):
        urls.extend([item.get("url"), item.get("thumb")])
    else:
        urls.extend([item.get("thumb"), item.get("url")])
    alt_urls = item.get("alt_urls") or []
    if isinstance(alt_urls, (list, tuple)):
        urls.extend(alt_urls)
    seen = set()
    session = _request_session()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        resp = None
        try:
            proxy = _wallhaven_proxy(item, url)
            if proxy:
                resp = session.get(
                    url,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                    stream=True,
                    proxies=proxy,
                )
            else:
                resp = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT, stream=True)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "").lower()
            if content_type and "text/html" in content_type:
                continue
            data = resp.raw.read(MAX_IMAGE_BYTES + 1, decode_content=True)
            if len(data) > MAX_IMAGE_BYTES:
                continue
            return data, resp.url, content_type
        except Exception:
            continue
        finally:
            if resp is not None:
                resp.close()
    return b"", "", ""


def _wallhaven_proxy(item, url):
    source = str(item.get("source", "")).lower()
    url_text = str(url).lower()
    if (
        source in ("wallhaven", "wallpaperscraft")
        or "wallhaven.cc" in url_text
        or "wallpaperscraft.com" in url_text
    ):
        return {"http": WALLHAVEN_PROXY, "https": WALLHAVEN_PROXY}
    return None


def open_image(data):
    if not data:
        return None
    try:
        img = Image.open(BytesIO(data))
        img.load()
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGB")
        return img
    except Exception:
        return None


def cache_preview_thumbnail(item, img):
    try:
        thumb = img.copy()
        if thumb.mode not in ("RGB", "RGBA"):
            thumb = thumb.convert("RGB")
        thumb.thumbnail(PREVIEW_THUMBNAIL_CACHE_SIZE, Image.LANCZOS)
        item["_thumb_pil"] = thumb.copy()
    except Exception:
        pass


def image_quality_score(img):
    width, height = img.size
    if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
        return -1.0, f"too small: {width}x{height}"

    pixels = width * height
    size_score = min(1.2, math.log(max(pixels, 1), 400 * 400))
    aspect = max(width / height, height / width)
    aspect_score = 0.4 if aspect <= 3.5 else -0.5

    small = img.convert("L").resize((64, 64))
    stat = ImageStat.Stat(small)
    variance = stat.var[0] if stat.var else 0
    detail_score = min(0.5, variance / 1800.0)
    return 0.7 + size_score + aspect_score + detail_score, f"{width}x{height}"


def _requested_colors(keyword):
    text = keyword.lower()
    colors = []
    for term, color in COLOR_TERMS.items():
        if term in text and color not in colors:
            colors.append(color)
    return colors


def _color_ratio(img, color):
    sample = img.convert("RGB").resize((96, 96))
    pixels = sample.getdata()
    total = 0
    hits = 0
    for r, g, b in pixels:
        total += 1
        mx = max(r, g, b)
        mn = min(r, g, b)
        if color == "red":
            ok = r > 100 and r > g * 1.35 and r > b * 1.25
        elif color == "blue":
            ok = b > 90 and b > r * 1.25 and b > g * 1.15
        elif color == "green":
            ok = g > 90 and g > r * 1.20 and g > b * 1.10
        elif color == "yellow":
            ok = r > 130 and g > 110 and b < 120 and abs(r - g) < 90
        elif color == "black":
            ok = mx < 65
        elif color == "white":
            ok = mn > 190
        elif color == "pink":
            ok = r > 150 and b > 100 and g < r * 0.82
        elif color == "purple":
            ok = r > 90 and b > 110 and g < min(r, b) * 0.85
        elif color == "orange":
            ok = r > 150 and 60 < g < 180 and b < 110 and r > g
        elif color == "gray":
            ok = mx - mn < 28 and 60 < mx < 210
        elif color == "brown":
            ok = r > 80 and g > 45 and b < 90 and r > g > b * 0.7
        else:
            ok = False
        if ok:
            hits += 1
    return hits / max(total, 1)


def color_match_score(img, keyword):
    colors = _requested_colors(keyword)
    if not colors:
        return 0.0, ""
    best_color = ""
    best_ratio = 0.0
    for color in colors:
        ratio = _color_ratio(img, color)
        if ratio > best_ratio:
            best_ratio = ratio
            best_color = color
    if best_ratio >= 0.18:
        return min(1.2, 0.3 + best_ratio * 2.2), f"{best_color}:{best_ratio:.0%}"
    return -0.4, f"{best_color or colors[0]}:{best_ratio:.0%}"


def _needs_face(keyword):
    text = keyword.lower()
    return any(term in text for term in FACE_TERMS)


def face_match_score(img, keyword):
    if not _needs_face(keyword):
        return 0.0, ""
    cv2_mod, np_mod = _load_optional_cv()
    if cv2_mod is None or np_mod is None:
        return 0.0, "opencv not installed"

    try:
        rgb = img.convert("RGB")
        arr = np_mod.array(rgb)
        gray = cv2_mod.cvtColor(arr, cv2_mod.COLOR_RGB2GRAY)
        cascade_path = os.path.join(cv2_mod.data.haarcascades, "haarcascade_frontalface_default.xml")
        detector = cv2_mod.CascadeClassifier(cascade_path)
        faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(32, 32))
        if len(faces) > 0:
            return min(1.4, 0.7 + len(faces) * 0.2), f"faces:{len(faces)}"
        return -0.35, "faces:0"
    except Exception:
        return 0.0, "opencv face failed"


def reference_match_score(img, reference_path):
    if not reference_path:
        return 0.0, ""
    cv2_mod, np_mod = _load_optional_cv()
    if cv2_mod is None or np_mod is None:
        return 0.0, "opencv not installed"

    try:
        target = cv2_mod.cvtColor(np_mod.array(img.convert("RGB")), cv2_mod.COLOR_RGB2GRAY)
        ref = cv2_mod.imread(reference_path, cv2_mod.IMREAD_GRAYSCALE)
        if ref is None:
            return 0.0, "reference unreadable"

        orb = cv2_mod.ORB_create(nfeatures=1200)
        kp1, des1 = orb.detectAndCompute(ref, None)
        kp2, des2 = orb.detectAndCompute(target, None)
        if des1 is None or des2 is None or not kp1 or not kp2:
            return 0.0, "no features"

        matcher = cv2_mod.BFMatcher(cv2_mod.NORM_HAMMING, crossCheck=True)
        matches = matcher.match(des1, des2)
        if not matches:
            return 0.0, "matches:0"
        good = [m for m in matches if m.distance <= 64]
        ratio = len(good) / max(min(len(kp1), len(kp2)), 1)
        return min(3.0, ratio * 8.0), f"orb:{len(good)}"
    except Exception:
        return 0.0, "opencv reference failed"


def score_item(item, keyword, visual_enabled=VISUAL_MATCH_ENABLED, reference_path=""):
    item = dict(item)
    score = metadata_score(item, keyword)
    reasons = [f"meta:{score:.2f}"]

    data, final_url, content_type = fetch_image_bytes(item)
    if final_url:
        item["_preview_url"] = final_url
    img = open_image(data)
    if img is None:
        item["_score"] = score - 1.0
        item["_match_reason"] = "invalid image"
        item["_valid_image"] = False
        return item

    q_score, q_reason = image_quality_score(img)
    score += q_score
    reasons.append(q_reason)
    item["_valid_image"] = q_score >= 0
    item["_size"] = img.size
    item["_content_type"] = content_type
    if item["_valid_image"]:
        cache_preview_thumbnail(item, img)

    if visual_enabled:
        c_score, c_reason = color_match_score(img, keyword)
        if c_reason:
            score += c_score
            reasons.append(c_reason)

        f_score, f_reason = face_match_score(img, keyword)
        if f_reason:
            score += f_score
            reasons.append(f_reason)

        r_score, r_reason = reference_match_score(img, reference_path)
        if r_reason:
            score += r_score
            reasons.append(r_reason)

    item["_score"] = round(score, 4)
    item["_match_reason"] = ", ".join(reasons)
    return item


def rank_items(items, keyword, limit=None, visual_enabled=VISUAL_MATCH_ENABLED, progress_callback=None):
    if not items:
        return []

    reference_path = ""
    if is_reference_image_query(keyword):
        reference_path = os.path.abspath(os.path.expanduser(keyword.strip().strip("\"'")))

    scored = []
    total = len(items)
    completed = 0

    def work(item):
        return score_item(item, keyword, visual_enabled, reference_path)

    with ThreadPoolExecutor(max_workers=MATCH_WORKERS) as pool:
        futures = [pool.submit(work, item) for item in items]
        for future in as_completed(futures):
            completed += 1
            try:
                scored.append(future.result())
            except Exception:
                pass
            if progress_callback:
                progress_callback(completed, total)

    valid = [it for it in scored if it.get("_valid_image")]
    fallback = [it for it in scored if not it.get("_valid_image")]
    ranked = sorted(valid, key=lambda it: it.get("_score", 0), reverse=True)
    if not ranked:
        # If every preview request failed because of a temporary network or anti-hotlink issue,
        # still return the best candidates so the downloader can try the original URLs.
        ranked = sorted(fallback, key=lambda it: it.get("_score", 0), reverse=True)

    if limit:
        return ranked[:limit]
    return ranked


def opencv_status():
    cv2_mod, np_mod = _load_optional_cv()
    return cv2_mod is not None and np_mod is not None

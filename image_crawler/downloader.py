# -*- coding: utf-8 -*-

import hashlib
import os
import re
import threading
from io import BytesIO
from typing import Optional, Tuple

import requests
from PIL import Image, ImageOps

from .config import DOWNLOAD_WORKERS, MAX_IMAGE_BYTES, REQUEST_TIMEOUT, WALLHAVEN_PROXY


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

EXT_BY_FORMAT = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "GIF": ".gif",
    "WEBP": ".webp",
    "BMP": ".bmp",
    "TIFF": ".tif",
}


class Downloader:
    def __init__(self, save_dir, target_resolution=None):
        self.save_dir = save_dir
        self.target_resolution = _parse_resolution(target_resolution)
        os.makedirs(save_dir, exist_ok=True)

    def download(self, items, keyword, progress_callback=None):
        total = len(items)
        if total == 0:
            return []

        completed = 0
        completed_lock = threading.Lock()
        results: list[Optional[Tuple[bool, str]]] = [None] * total

        def work(idx, item):
            nonlocal completed
            try:
                filepath = self._download_one(idx, item, keyword)
                result = (True, filepath)
            except Exception as exc:
                result = (False, str(exc))

            with completed_lock:
                completed += 1
                done = completed
            if progress_callback:
                progress_callback(done, total)
            return idx, result

        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            futures = [pool.submit(work, i, item) for i, item in enumerate(items)]
            for future in as_completed(futures):
                idx, result = future.result()
                results[idx] = result
        return results

    def _download_one(self, idx, item, keyword):
        data, final_url, content_type = self._fetch_best_image(item)
        if not data:
            raise RuntimeError("no image data returned")

        img = Image.open(BytesIO(data))
        img.load()
        img_format = (img.format or "").upper()
        ext = EXT_BY_FORMAT.get(img_format) or _guess_ext(final_url, content_type)
        save_data = data
        if self.target_resolution:
            save_data, ext = _resize_to_resolution(img, self.target_resolution)
        elif _should_convert_webp(item, img_format, ext):
            save_data, ext = _convert_to_jpg_or_png(img)

        filename = self._make_filename(keyword, idx, item, ext, save_data)
        filepath = os.path.join(self.save_dir, filename)

        with open(filepath, "wb") as handle:
            handle.write(save_data)
        return filepath

    def _fetch_best_image(self, item):
        headers = _headers_for_item(item)
        candidates = [item.get("url")]
        alt_urls = item.get("alt_urls") or []
        if isinstance(alt_urls, (list, tuple)):
            candidates.extend(alt_urls)
        candidates.extend([item.get("_preview_url"), item.get("thumb")])
        seen = set()
        for url in candidates:
            if not url or url in seen:
                continue
            seen.add(url)
            try:
                proxy = _wallhaven_proxy(item, url)
                if proxy:
                    resp = requests.get(
                        url,
                        headers=headers,
                        timeout=REQUEST_TIMEOUT,
                        stream=True,
                        proxies=proxy,
                    )
                else:
                    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, stream=True)
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "").lower()
                if "text/html" in content_type:
                    continue
                data = resp.raw.read(MAX_IMAGE_BYTES + 1, decode_content=True)
                if len(data) > MAX_IMAGE_BYTES:
                    continue
                Image.open(BytesIO(data)).verify()
                return data, resp.url, content_type
            except Exception:
                continue
        return b"", "", ""

    def _make_filename(self, keyword, idx, item, ext, data):
        base = _safe_filename(keyword or "image")
        source = _safe_filename(item.get("source", "img"))
        digest = hashlib.sha1(data[:65536]).hexdigest()[:8]
        name = f"{base}_{source}_{idx + 1:03d}_{digest}{ext}"
        path = os.path.join(self.save_dir, name)
        if not os.path.exists(path):
            return name

        stem = name[: -len(ext)]
        n = 2
        while True:
            candidate = f"{stem}_{n}{ext}"
            if not os.path.exists(os.path.join(self.save_dir, candidate)):
                return candidate
            n += 1


def _headers_for_item(item):
    headers = dict(HEADERS)
    token = item.get("_token")
    if token:
        headers["token"] = token
    referer = item.get("referer") or item.get("_referer") or item.get("page_url")
    if referer:
        if str(item.get("source", "")).lower() == "bing":
            headers["referer"] = referer
        else:
            headers["Referer"] = referer
    return headers


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


def _should_convert_webp(item, img_format, ext):
    source = str(item.get("source", "")).strip().lower()
    is_target_source = source in ("百度", "好壁纸")
    is_webp = img_format == "WEBP" or str(ext).lower() == ".webp"
    return is_target_source and is_webp


def _parse_resolution(value):
    if isinstance(value, tuple) and len(value) == 2:
        try:
            width, height = int(value[0]), int(value[1])
        except Exception:
            return None
        return (width, height) if width > 0 and height > 0 else None

    match = re.fullmatch(r"\s*(\d{2,5})\s*x\s*(\d{2,5})\s*", str(value or ""), flags=re.I)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _resize_to_resolution(img, target_resolution):
    target_width, target_height = target_resolution
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if _has_alpha(img) else "RGB")

    source_ratio = img.width / max(img.height, 1)
    target_ratio = target_width / max(target_height, 1)
    if source_ratio > target_ratio:
        crop_width = max(1, int(img.height * target_ratio))
        left = max(0, (img.width - crop_width) // 2)
        crop_box = (left, 0, left + crop_width, img.height)
    else:
        crop_height = max(1, int(img.width / target_ratio))
        top = max(0, (img.height - crop_height) // 2)
        crop_box = (0, top, img.width, top + crop_height)

    resized = img.crop(crop_box).resize((target_width, target_height), Image.LANCZOS)
    output = BytesIO()
    if _has_alpha(resized):
        resized.convert("RGBA").save(output, format="PNG", optimize=True)
        return output.getvalue(), ".png"

    resized.convert("RGB").save(output, format="JPEG", quality=95, optimize=True)
    return output.getvalue(), ".jpg"


def _convert_to_jpg_or_png(img):
    output = BytesIO()
    if _has_alpha(img):
        converted = img.convert("RGBA")
        converted.save(output, format="PNG", optimize=True)
        return output.getvalue(), ".png"

    converted = img.convert("RGB")
    converted.save(output, format="JPEG", quality=95, optimize=True)
    return output.getvalue(), ".jpg"


def _has_alpha(img):
    if img.mode in ("RGBA", "LA"):
        return True
    if img.mode == "P" and "transparency" in img.info:
        return True
    return False


def _safe_filename(text, max_len=60):
    text = str(text).strip()
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._ ")
    if not text:
        text = "image"
    return text[:max_len]


def _guess_ext(url, content_type):
    path = (url or "").split("?", 1)[0].lower()
    for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"]:
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/tiff": ".tif",
    }
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    return mapping.get(ctype, ".jpg")

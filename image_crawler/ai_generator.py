# -*- coding: utf-8 -*-

import base64
import hashlib
import os
from io import BytesIO

import requests
from PIL import Image

from .config import (
    AI_IMAGE_ALLOW_SIZE_FALLBACK,
    AI_IMAGE_API_KEY,
    AI_IMAGE_BASE_URL,
    AI_IMAGE_DEFAULT_SIZE,
    AI_IMAGE_ENDPOINT,
    AI_IMAGE_FORCE_OUTPUT_RESOLUTION,
    AI_IMAGE_MODEL,
    AI_IMAGE_NUM_IMAGES,
    AI_IMAGE_RESPONSE_FORMAT,
    AI_IMAGE_TIMEOUT,
)
from .downloader import EXT_BY_FORMAT, _parse_resolution, _resize_to_resolution, _safe_filename


class AIImageConfigError(RuntimeError):
    pass


class AIImageClient:
    def __init__(self):
        self.api_key = os.environ.get("IMAGE_CRAWLER_AI_API_KEY") or AI_IMAGE_API_KEY
        self.base_url = os.environ.get("IMAGE_CRAWLER_AI_BASE_URL") or AI_IMAGE_BASE_URL
        self.endpoint = os.environ.get("IMAGE_CRAWLER_AI_ENDPOINT") or AI_IMAGE_ENDPOINT
        self.model = os.environ.get("IMAGE_CRAWLER_AI_MODEL") or AI_IMAGE_MODEL
        self.default_size = os.environ.get("IMAGE_CRAWLER_AI_SIZE") or AI_IMAGE_DEFAULT_SIZE
        self.response_format = os.environ.get("IMAGE_CRAWLER_AI_RESPONSE_FORMAT") or AI_IMAGE_RESPONSE_FORMAT
        self.num_images = _safe_int(os.environ.get("IMAGE_CRAWLER_AI_NUM_IMAGES"), AI_IMAGE_NUM_IMAGES)
        self.timeout = _safe_int(os.environ.get("IMAGE_CRAWLER_AI_TIMEOUT"), AI_IMAGE_TIMEOUT)
        self.allow_size_fallback = _safe_bool(
            os.environ.get("IMAGE_CRAWLER_AI_ALLOW_SIZE_FALLBACK"),
            AI_IMAGE_ALLOW_SIZE_FALLBACK,
        )
        self.force_output_resolution = _safe_bool(
            os.environ.get("IMAGE_CRAWLER_AI_FORCE_OUTPUT_RESOLUTION"),
            AI_IMAGE_FORCE_OUTPUT_RESOLUTION,
        )

    def generate_and_save(self, prompt, save_dir, target_resolution=None):
        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("AI 提示词不能为空")
        if not self.api_key or not self.base_url:
            raise AIImageConfigError("请先在 config.py 中配置 AI_IMAGE_API_KEY 和 AI_IMAGE_BASE_URL")

        os.makedirs(save_dir, exist_ok=True)
        target_size = _parse_resolution(target_resolution)
        output_size = target_size if self.force_output_resolution else None
        request_size = target_resolution if target_size else self.default_size

        try:
            image_entries = self._request_generation(prompt, request_size)
        except Exception:
            if self.allow_size_fallback and target_size and request_size != self.default_size:
                image_entries = self._request_generation(prompt, self.default_size)
            else:
                raise

        paths = []
        for idx, entry in enumerate(image_entries):
            data, content_type, _source_url = self._entry_to_bytes(entry)
            if not data:
                continue
            data, ext = _normalize_image_data(data, content_type)
            paths.append(_write_image(save_dir, prompt, idx, data, ext, output_size))

        if not paths:
            raise RuntimeError("AI 接口未返回可保存的图片")
        return paths

    def _request_generation(self, prompt, size):
        payload = {
            "model": self.model,
            "prompt": prompt,
            "n": max(1, int(self.num_images or 1)),
        }
        if size:
            payload["size"] = size
        if self.response_format:
            payload["response_format"] = self.response_format

        response = requests.post(
            _endpoint_url(self.base_url, self.endpoint),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(_response_error(response))

        content_type = response.headers.get("Content-Type", "").lower()
        if content_type.startswith("image/"):
            return [{"bytes": response.content, "content_type": content_type, "url": response.url}]

        body = response.json()
        data = body.get("data") or body.get("images") or body.get("output") or []
        if isinstance(data, str):
            data = [data]
        elif isinstance(data, dict):
            data = [data]
        elif not isinstance(data, list):
            data = []
        if not data and any(key in body for key in ("url", "b64_json", "image", "bytes")):
            data = [body]
        return data

    def _entry_to_bytes(self, entry):
        if isinstance(entry, str):
            if entry.startswith(("http://", "https://")):
                return self._fetch_image_url(entry)
            return _decode_base64_image(entry), "", ""

        if not isinstance(entry, dict):
            return b"", "", ""

        raw = entry.get("bytes")
        if isinstance(raw, bytes):
            return raw, entry.get("content_type", ""), entry.get("url", "")

        for key in ("b64_json", "image", "base64", "image_base64"):
            data = _decode_base64_image(entry.get(key))
            if data:
                return data, entry.get("content_type", ""), entry.get("url", "")

        url = entry.get("url") or entry.get("image_url")
        if url:
            return self._fetch_image_url(str(url))

        return b"", "", ""

    def _fetch_image_url(self, url):
        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.content, response.headers.get("Content-Type", "").lower(), response.url


def _endpoint_url(base_url, endpoint):
    base = (base_url or "").rstrip("/")
    tail = (endpoint or "").strip("/")
    if not tail:
        return base
    if base.lower().endswith(tail.lower()):
        return base
    return f"{base}/{tail}"


def _decode_base64_image(value):
    if not value:
        return b""
    text = str(value).strip()
    if text.startswith("data:"):
        _prefix, _sep, text = text.partition(",")
    try:
        return base64.b64decode(text, validate=False)
    except Exception:
        return b""


def _normalize_image_data(data, content_type):
    img = Image.open(BytesIO(data))
    img.load()
    image_format = (img.format or "").upper()
    ext = EXT_BY_FORMAT.get(image_format) or _ext_from_content_type(content_type)
    return data, ext


def _ext_from_content_type(content_type):
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


def _write_image(save_dir, prompt, idx, data, ext, target_size=None):
    if target_size:
        img = Image.open(BytesIO(data))
        img.load()
        data, ext = _resize_to_resolution(img, target_size)
        _ensure_image_size(data, target_size)

    base = _safe_filename(prompt or "ai_image", max_len=48)
    digest = hashlib.sha1(data[:65536]).hexdigest()[:8]
    size_label = f"_{target_size[0]}x{target_size[1]}" if target_size else ""
    stem = f"ai_{base}_{idx + 1:02d}{size_label}_{digest}"
    filename = f"{stem}{ext}"
    path = os.path.join(save_dir, filename)
    counter = 2
    while os.path.exists(path):
        filename = f"{stem}_{counter}{ext}"
        path = os.path.join(save_dir, filename)
        counter += 1

    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _ensure_image_size(data, target_size):
    img = Image.open(BytesIO(data))
    img.load()
    if img.size != target_size:
        raise RuntimeError(f"AI 图片输出尺寸处理失败：{img.size[0]}x{img.size[1]} != {target_size[0]}x{target_size[1]}")


def _response_error(response):
    try:
        body = response.json()
        detail = body.get("error") or body
    except Exception:
        detail = response.text[:500]
    return f"AI 图片生成失败：HTTP {response.status_code}: {detail}"


def _safe_int(value, fallback):
    try:
        return int(value)
    except Exception:
        return int(fallback)


def _safe_bool(value, fallback):
    if value is None:
        return bool(fallback)
    return str(value).strip().lower() in ("1", "true", "yes", "on")

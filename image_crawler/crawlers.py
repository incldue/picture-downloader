# -*- coding: utf-8 -*-

import html as html_mod
import re
import time
import urllib.parse

import requests

from .config import MAX_IMAGES, REQUEST_TIMEOUT, SEARCH_DELAY, SEARCH_PAGE_SIZE, WALLHAVEN_PROXY


BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def normalize_url(url, base_url=None):
    if not url:
        return ""
    url = html_mod.unescape(str(url)).strip()
    url = url.replace("\\/", "/")
    if url.startswith("//"):
        return "https:" + url
    if base_url and url.startswith("/"):
        return urllib.parse.urljoin(base_url, url)
    return url


def clean_text(value):
    if not value:
        return ""
    value = html_mod.unescape(str(value))
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("\ue000", "").replace("\ue001", "")
    return re.sub(r"\s+", " ", value).strip()


def make_item(url, thumb=None, title="", source="", page_url="", tags=None, **extra):
    item = {
        "url": normalize_url(url),
        "thumb": normalize_url(thumb) or normalize_url(url),
        "title": clean_text(title),
        "source": source,
        "page_url": normalize_url(page_url),
        "tags": [clean_text(t) for t in (tags or []) if clean_text(t)],
    }
    item.update(extra)
    return item


def dedupe_items(items):
    seen = set()
    deduped = []
    for item in items:
        url = normalize_url(item.get("url"))
        if not url or not url.startswith(("http://", "https://")):
            continue
        key = url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        item["url"] = url
        item["thumb"] = normalize_url(item.get("thumb")) or url
        deduped.append(item)
    return deduped


def _query_tokens(keyword):
    keyword = keyword.strip().lower()
    tokens = [keyword] if keyword else []
    tokens.extend(re.findall(r"[a-z0-9_+-]+", keyword, flags=re.I))
    tokens.extend(re.findall(r"[\u4e00-\u9fff]{1,}", keyword))
    seen = set()
    result = []
    for token in tokens:
        token = token.strip().lower()
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result


class WallpapersCraftCrawler:
    source_name = "WallpapersCraft"
    base_url = "https://wallpaperscraft.com"
    default_image_size = "1920x1080"

    def __init__(self):
        self._ses = requests.Session()
        self._ses.trust_env = False
        self._ses.proxies.update({"http": WALLHAVEN_PROXY, "https": WALLHAVEN_PROXY})
        self._ses.headers.update(BASE_HEADERS)
        self._ses.headers.update({"Referer": self.base_url + "/"})
        self._cur_page = 1
        self.image_size = self.default_image_size

    def set_resolution(self, resolution):
        if resolution:
            self.image_size = resolution

    @staticmethod
    def _validate_keyword(keyword):
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _+\-.,]*", keyword.strip()):
            return
        raise ValueError("WallpapersCraft 只能使用英文关键词")

    def _fetch_page(self, keyword, page):
        resp = self._ses.get(
            f"{self.base_url}/search/",
            params={
                "order": "",
                "page": page,
                "query": keyword,
                "size": self.image_size or "",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return self._parse_search_html(resp.text, keyword, page)

    def _parse_search_html(self, html_text, keyword, page):
        blocks = re.findall(
            r"<li\b[^>]*class=[\"'][^\"']*wallpapers__item[^\"']*[\"'][^>]*>.*?</li>",
            html_text,
            flags=re.I | re.S,
        )
        results = []
        for offset, block in enumerate(blocks):
            href_match = re.search(
                r"<a\b[^>]*class=[\"'][^\"']*wallpapers__link[^\"']*[\"'][^>]*href=[\"']([^\"']+)[\"']",
                block,
                flags=re.I | re.S,
            )
            img_match = re.search(
                r"<img\b[^>]*class=[\"'][^\"']*wallpapers__image[^\"']*[\"'][^>]*src=[\"']([^\"']+)[\"']",
                block,
                flags=re.I | re.S,
            )
            if not href_match or not img_match:
                continue

            page_url = normalize_url(href_match.group(1), self.base_url)
            thumb = normalize_url(img_match.group(1))
            title = self._extract_title(block)
            rank = (page - 1) * SEARCH_PAGE_SIZE + offset + 1
            image_url = self._full_image_url(thumb)
            confidence = self._confidence(keyword, title, page_url, thumb, rank)
            results.append(
                make_item(
                    image_url,
                    thumb,
                    title=title,
                    source=self.source_name,
                    page_url=page_url,
                    tags=[keyword, title, page_url],
                    referer=page_url,
                    _referer=page_url,
                    wallpaperscraft_confidence=confidence,
                    _wallpaperscraft_confidence=confidence,
                    _rank=rank,
                    _query=keyword,
                    alt_urls=[image_url, thumb],
                )
            )
        return results

    @staticmethod
    def _extract_title(block):
        alt_match = re.search(r"<img\b[^>]*alt=[\"']([^\"']+)[\"']", block, flags=re.I | re.S)
        if alt_match:
            title = clean_text(alt_match.group(1))
            title = re.sub(r"^Preview wallpaper\s+", "", title, flags=re.I)
            if title:
                return title
        info_matches = re.findall(
            r"<span\b[^>]*class=[\"'][^\"']*wallpapers__info[^\"']*[\"'][^>]*>(.*?)</span>",
            block,
            flags=re.I | re.S,
        )
        for raw in reversed(info_matches):
            title = clean_text(raw)
            if title and not re.fullmatch(r"[\d.\sx]+", title):
                return title
        return ""

    def _full_image_url(self, thumb):
        thumb = normalize_url(thumb)
        if not thumb:
            return ""
        return re.sub(r"_(\d+)x(\d+)(\.[A-Za-z0-9]+)$", f"_{self.image_size}\\3", thumb)

    @staticmethod
    def _confidence(keyword, title, page_url, thumb, rank):
        tokens = _query_tokens(keyword)
        text = " ".join([title, page_url, thumb]).lower()

        rank_conf = max(0.0, 1.0 - (max(rank, 1) - 1) / 80.0)
        text_hits = 0
        for token in tokens:
            if token and token in text:
                text_hits += 1
        text_conf = min(1.0, text_hits / max(len(tokens), 1))

        full = keyword.strip().lower()
        exact_conf = 1.0 if full and full in text else 0.0
        title_conf = 1.0 if full and full in title.lower() else 0.0

        confidence = 100 * (0.50 * rank_conf + 0.25 * text_conf + 0.15 * exact_conf + 0.10 * title_conf)
        return max(1, min(100, int(round(confidence))))

    def _collect(self, keyword, num, first=None):
        self._validate_keyword(keyword)
        results = []
        page = self._cur_page if first is None else first
        while len(results) < num:
            try:
                items = self._fetch_page(keyword, page)
            except Exception:
                break
            if not items:
                break
            for offset, item in enumerate(items):
                item["_rank"] = item.get("_rank", (page - 1) * SEARCH_PAGE_SIZE + offset + 1)
                item["_query"] = keyword
                results.append(item)
                if len(results) >= num:
                    break
            page += 1
            time.sleep(SEARCH_DELAY)
        self._cur_page = max(self._cur_page, page)
        return dedupe_items(results)[:num]

    def search(self, keyword, num=MAX_IMAGES):
        self._cur_page = 1
        return self._collect(keyword, num, first=1)

    def load_more(self, keyword, existing_count=0, num=MAX_IMAGES):
        return self._collect(keyword, num)

    @staticmethod
    def name():
        return WallpapersCraftCrawler.source_name


class BaiduCrawler:
    source_name = "百度"

    def __init__(self):
        self._ses = requests.Session()
        self._ses.headers.update(BASE_HEADERS)
        self._ses.headers.update(
            {
                "Referer": "https://image.baidu.com/search/index",
                "Accept": "application/json, text/plain, */*",
            }
        )
        self._next_pn = 0

    def _init_cookie(self, keyword):
        try:
            self._ses.get(
                "https://image.baidu.com/search/index",
                params={"tn": "baiduimage", "word": keyword},
                timeout=REQUEST_TIMEOUT,
            )
        except Exception:
            pass

    def _fetch_page(self, keyword, pn, rn):
        params = {
            "tn": "resultjson_com",
            "ipn": "rj",
            "ct": "201326592",
            "is": "",
            "fp": "result",
            "queryWord": keyword,
            "cl": "2",
            "lm": "-1",
            "ie": "utf-8",
            "oe": "utf-8",
            "st": "-1",
            "face": "0",
            "istype": "2",
            "nc": "1",
            "word": keyword,
            "pn": pn,
            "rn": rn,
        }
        resp = self._ses.get(
            "https://image.baidu.com/search/acjson",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"
        body = resp.json()
        if body.get("antiFlag") or body.get("message"):
            return []
        return body.get("data") or []

    @staticmethod
    def _decode_obj_url(url):
        url = normalize_url(url)
        if not url:
            return ""
        return url

    def _collect(self, keyword, num, pn=None):
        if pn is None:
            pn = self._next_pn
        results = []
        while len(results) < num:
            try:
                data = self._fetch_page(keyword, pn, min(SEARCH_PAGE_SIZE, num - len(results)))
            except Exception:
                break
            if not data:
                break
            page_found = 0
            for row in data:
                if not isinstance(row, dict):
                    continue
                thumb = row.get("thumbURL") or row.get("thumbnailUrl") or ""
                url = row.get("middleURL") or row.get("hoverURL") or row.get("objURL") or thumb
                url = self._decode_obj_url(url)
                if not normalize_url(url).startswith(("http://", "https://")):
                    continue
                results.append(
                    make_item(
                        url,
                        thumb,
                        title=row.get("fromPageTitleEnc") or row.get("fromPageTitle") or keyword,
                        source=self.source_name,
                        page_url=row.get("fromURL") or row.get("fromUrl") or "",
                        tags=[row.get("type"), row.get("fromPageTitleEnc"), keyword],
                    )
                )
                page_found += 1
            if page_found == 0:
                break
            pn += SEARCH_PAGE_SIZE
            time.sleep(SEARCH_DELAY)
        self._next_pn = max(self._next_pn, pn)
        return dedupe_items(results)[:num]

    def search(self, keyword, num=MAX_IMAGES):
        self._next_pn = 0
        self._init_cookie(keyword)
        return self._collect(keyword, num, pn=0)

    def load_more(self, keyword, existing_count=0, num=MAX_IMAGES):
        return self._collect(keyword, num)

    @staticmethod
    def name():
        return BaiduCrawler.source_name


class HaoWallpaperCrawler:
    source_name = "好壁纸"
    base_url = "https://haowallpaper.com"

    def __init__(self):
        self._ses = requests.Session()
        self._ses.headers.update(BASE_HEADERS)
        self._token = None
        self._cur_page = 1

    def _ensure_token(self):
        if self._token is not None:
            return
        try:
            self._ses.get(self.base_url, timeout=REQUEST_TIMEOUT)
            raw = self._ses.cookies.get("askId", "")
            self._token = urllib.parse.unquote(raw) if raw else ""
        except Exception:
            self._token = ""

    def _extract_ids(self, html_text):
        ids = re.findall(r"/common/file/getCroppingImg/(\d+)", html_text)
        ordered = []
        seen = set()
        for fid in ids:
            if len(fid) > 8 and fid not in seen:
                seen.add(fid)
                ordered.append(fid)
        return ordered

    def _search_page(self, keyword, page):
        resp = self._ses.get(
            self.base_url,
            params={"page": page, "sortType": 3, "rows": 18, "search": keyword},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return self._extract_ids(resp.text)

    def _items_from_ids(self, ids, keyword):
        token = self.get_token()
        results = []
        for fid in ids:
            results.append(
                make_item(
                    f"{self.base_url}/link/common/file/previewFileImg/{fid}",
                    f"{self.base_url}/link/common/file/getCroppingImg/{fid}",
                    title=keyword,
                    source=self.source_name,
                    page_url=self.base_url,
                    tags=[keyword, "wallpaper"],
                    _file_id=fid,
                    _token=token,
                )
            )
        return results

    def search(self, keyword, num=MAX_IMAGES):
        self._cur_page = 1
        try:
            ids = self._search_page(keyword, self._cur_page)
        except Exception:
            return []
        return self._items_from_ids(ids[:num], keyword)

    def load_more(self, keyword, existing_count=0, num=MAX_IMAGES):
        self._cur_page += 1
        try:
            ids = self._search_page(keyword, self._cur_page)
        except Exception:
            return []
        return self._items_from_ids(ids[:num], keyword)

    def get_token(self):
        self._ensure_token()
        return self._token or ""

    @staticmethod
    def name():
        return HaoWallpaperCrawler.source_name


class WallhavenCrawler:
    source_name = "Wallhaven"

    def __init__(self):
        self._ses = requests.Session()
        # Wallhaven is the only source forced through the local proxy.
        self._ses.trust_env = False
        self._ses.proxies.update({"http": WALLHAVEN_PROXY, "https": WALLHAVEN_PROXY})
        self._ses.headers.update(BASE_HEADERS)
        self._ses.headers.update(
            {
                "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://wallhaven.cc/",
            }
        )
        self._cur_page = 1
        self._use_api = True
        self._resolution = ""

    def set_resolution(self, resolution):
        self._resolution = resolution or ""

    def _api_search(self, keyword, page):
        params = {
            "q": keyword,
            "page": page,
            "categories": "111",
            "purity": "100",
            "sorting": "relevance",
            "order": "desc",
        }
        if self._resolution:
            params["resolutions"] = self._resolution
        resp = self._ses.get(
            "https://wallhaven.cc/api/v1/search",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data") or []

    def _scrape_search(self, keyword, page):
        params = {
            "q": keyword,
            "page": page,
            "categories": "111",
            "purity": "100",
            "sorting": "relevance",
            "order": "desc",
        }
        if self._resolution:
            params["resolutions"] = self._resolution
        resp = self._ses.get(
            "https://wallhaven.cc/search",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        html_text = resp.text
        items = []
        figures = re.findall(r"<figure\b.*?</figure>", html_text, flags=re.I | re.S)
        seen = set()

        def add_item(wid, thumb=""):
            wid = clean_text(wid)
            if not wid or wid in seen:
                return
            seen.add(wid)
            thumb = normalize_url(thumb) or _wallhaven_small_thumb(wid)
            alt_urls = _wallhaven_original_candidates(wid)
            items.append(
                {
                    "id": wid,
                    "path": alt_urls[0],
                    "alt_urls": alt_urls,
                    "thumbs": {"small": thumb, "original": thumb},
                    "url": f"https://wallhaven.cc/w/{wid}",
                    "tags": [keyword],
                }
            )

        for figure in figures:
            id_match = re.search(r'data-wallpaper-id=["\']([^"\']+)["\']', figure, flags=re.I)
            if not id_match:
                continue
            thumb_match = re.search(
                r'<img[^>]+(?:data-src|src)=["\']([^"\']+)["\']',
                figure,
                flags=re.I | re.S,
            )
            add_item(id_match.group(1), thumb_match.group(1) if thumb_match else "")

        if not items:
            for wid in re.findall(r'data-wallpaper-id=["\']([^"\']+)["\']', html_text, flags=re.I):
                add_item(wid)
        return items

    def _fetch_page(self, keyword, page):
        if self._use_api:
            try:
                return self._api_search(keyword, page)
            except Exception:
                self._use_api = False
        try:
            return self._scrape_search(keyword, page)
        except Exception:
            return []

    def _collect(self, keyword, num, reset=False):
        if reset:
            self._cur_page = 1
            self._use_api = True
        results = []
        while len(results) < num:
            rows = self._fetch_page(keyword, self._cur_page)
            if not rows:
                break
            for row in rows:
                thumbs = row.get("thumbs") if isinstance(row.get("thumbs"), dict) else {}
                thumb = thumbs.get("small") or thumbs.get("large") or thumbs.get("original") or ""
                url = row.get("path") or ""
                if not url:
                    continue
                tag_names = _wallhaven_tag_names(row.get("tags"), keyword)
                results.append(
                    make_item(
                        url,
                        thumb,
                        title=" ".join(tag_names),
                        source=self.source_name,
                        page_url=row.get("url") or "",
                        tags=tag_names,
                        alt_urls=row.get("alt_urls") or [],
                        _id=row.get("id", ""),
                    )
                )
                if len(results) >= num:
                    break
            self._cur_page += 1
            time.sleep(SEARCH_DELAY)
        return dedupe_items(results)[:num]

    def search(self, keyword, num=MAX_IMAGES):
        return self._collect(keyword, num, reset=True)

    def load_more(self, keyword, existing_count=0, num=MAX_IMAGES):
        return self._collect(keyword, num, reset=False)

    @staticmethod
    def name():
        return WallhavenCrawler.source_name


def _wallhaven_tag_names(tags, keyword):
    names = []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict):
                value = tag.get("name") or tag.get("alias") or tag.get("id")
            else:
                value = tag
            value = clean_text(value)
            if value:
                names.append(value)
    if not names:
        names.append(keyword)
    return names


def _wallhaven_small_thumb(wid):
    return f"https://th.wallhaven.cc/small/{wid[:2]}/{wid}.jpg"


def _wallhaven_original_candidates(wid):
    base = f"https://w.wallhaven.cc/full/{wid[:2]}/wallhaven-{wid}"
    return [base + ".jpg", base + ".png", base + ".webp"]

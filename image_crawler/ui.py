# -*- coding: utf-8 -*-

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
from tkinter import filedialog, messagebox, ttk

from .config import (
    DEFAULT_RESOLUTION,
    DEFAULT_DOWNLOAD_DIR,
    MAX_IMAGES,
    RESOLUTION_OPTIONS,
    RESOLUTION_ORIGINAL,
    THUMBNAIL_COL_MIN_WIDTH,
    THUMBNAIL_SIZE,
    THUMBNAIL_WORKERS,
    VISUAL_MATCH_ENABLED,
)
from .crawlers import (
    BaiduCrawler,
    HaoWallpaperCrawler,
    WallpapersCraftCrawler,
    WallhavenCrawler,
    dedupe_items,
)
from .ai_generator import AIImageClient
from .downloader import Downloader
from .image_matcher import fetch_image_bytes, opencv_status, rank_items


SOURCE_ALL = "全部"
SOURCES = [
    SOURCE_ALL,
    WallpapersCraftCrawler.name(),
    BaiduCrawler.name(),
    HaoWallpaperCrawler.name(),
    WallhavenCrawler.name(),
]

COLORS = {
    "bg": "#f6f8fb",
    "panel": "#ffffff",
    "card": "#ffffff",
    "card_alt": "#eef2f7",
    "line": "#dbe3ef",
    "text": "#0f172a",
    "muted": "#64748b",
    "accent": "#2563eb",
    "accent_dark": "#1d4ed8",
    "success": "#16a34a",
    "warning": "#d97706",
    "danger": "#dc2626",
    "input": "#ffffff",
}


class ImageCrawlerUI:
    def __init__(self, root):
        self.root = root
        root.title("Image Crawler Pro")
        root.geometry("1160x820")
        root.minsize(820, 580)
        root.configure(bg=COLORS["bg"])

        self.download_path = tk.StringVar(value=DEFAULT_DOWNLOAD_DIR)
        self.source_var = tk.StringVar(value=SOURCE_ALL)
        self.resolution_var = tk.StringVar(value=DEFAULT_RESOLUTION)
        self.visual_var = tk.BooleanVar(value=VISUAL_MATCH_ENABLED)

        self.searching = False
        self.loading_more = False
        self.ai_generating = False
        self.items = []
        self.image_refs = []
        self._thumb_size = THUMBNAIL_SIZE
        self._resize_job = None
        self.keyword = ""
        self._source = SOURCE_ALL
        self._resolution = ""
        self._crawlers = []
        self._errors = []

        self._configure_style()
        self._build_top()
        self._build_middle()
        self._build_bottom()

    def _configure_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TFrame", background=COLORS["bg"])
        style.configure("Panel.TFrame", background=COLORS["panel"], relief=tk.FLAT)
        style.configure("Card.TFrame", background=COLORS["card"], relief=tk.FLAT)
        style.configure("App.TLabel", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("Panel.TLabel", background=COLORS["panel"], foreground=COLORS["text"])
        style.configure("Muted.TLabel", background=COLORS["panel"], foreground=COLORS["muted"])
        style.configure("Card.TLabel", background=COLORS["card"], foreground=COLORS["text"])
        style.configure("MutedCard.TLabel", background=COLORS["card"], foreground=COLORS["muted"])
        style.configure(
            "App.Horizontal.TProgressbar",
            troughcolor=COLORS["input"],
            background=COLORS["accent"],
            bordercolor=COLORS["line"],
            lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent_dark"],
        )
        style.configure(
            "App.TCombobox",
            fieldbackground=COLORS["input"],
            background=COLORS["panel"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["accent"],
            bordercolor=COLORS["line"],
            insertcolor=COLORS["text"],
        )

    def _button(self, parent, text, command=None, primary=False, width=None, state=tk.NORMAL):
        bg = COLORS["accent"] if primary else COLORS["card_alt"]
        fg = "#ffffff" if primary else COLORS["text"]
        active_bg = COLORS["accent_dark"] if primary else COLORS["line"]
        options = {}
        if command is not None:
            options["command"] = command
        if width is not None:
            options["width"] = width
        button = tk.Button(
            parent,
            text=text,
            bd=0,
            padx=14,
            pady=8,
            relief=tk.FLAT,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            disabledforeground="#64748b",
            font=("", 10, "bold" if primary else "normal"),
            cursor="hand2",
            **options,
        )
        button.bind("<Enter>", lambda _e, b=button, c=active_bg: b.config(bg=c) if b["state"] == tk.NORMAL else None)
        button.bind("<Leave>", lambda _e, b=button, c=bg: b.config(bg=c) if b["state"] == tk.NORMAL else None)
        if state != tk.NORMAL:
            button["state"] = state
        return button

    def _entry(self, parent, textvariable=None, width=None):
        options = {}
        if textvariable is not None:
            options["textvariable"] = textvariable
        if width is not None:
            options["width"] = width
        entry = tk.Entry(
            parent,
            bd=0,
            relief=tk.FLAT,
            bg=COLORS["input"],
            fg=COLORS["text"],
            insertbackground=COLORS["accent"],
            highlightthickness=1,
            highlightbackground=COLORS["line"],
            highlightcolor=COLORS["accent"],
            font=("", 11),
            **options,
        )
        return entry

    def _text(self, parent, height=3):
        return tk.Text(
            parent,
            height=height,
            bd=0,
            relief=tk.FLAT,
            bg=COLORS["input"],
            fg=COLORS["text"],
            insertbackground=COLORS["accent"],
            highlightthickness=1,
            highlightbackground=COLORS["line"],
            highlightcolor=COLORS["accent"],
            font=("", 10),
            wrap=tk.WORD,
        )

    def _build_top(self):
        top = tk.Frame(self.root, bg=COLORS["bg"])
        top.pack(fill=tk.X, padx=16, pady=(16, 8))

        header = tk.Frame(top, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        header.pack(fill=tk.X)

        title_box = tk.Frame(header, bg=COLORS["panel"])
        title_box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=18, pady=16)
        tk.Label(
            title_box,
            text="Image Crawler Pro",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("", 20, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="多源搜索 · AI生成 · 视觉校验 · 高清下载",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=("", 10),
        ).pack(anchor="w", pady=(4, 0))

        status_text = "OpenCV 已启用" if opencv_status() else "OpenCV 未安装，使用 Pillow 基础校验"
        status_color = COLORS["success"] if opencv_status() else COLORS["warning"]
        tk.Label(
            header,
            text=status_text,
            bg=COLORS["card"],
            fg=status_color,
            padx=12,
            pady=8,
            font=("", 9, "bold"),
        ).pack(side=tk.RIGHT, padx=18)

        panel = tk.Frame(top, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        panel.pack(fill=tk.X, pady=(12, 0))

        row1 = tk.Frame(panel, bg=COLORS["panel"])
        row1.pack(fill=tk.X, padx=16, pady=(16, 8))

        tk.Label(row1, text="关键词", bg=COLORS["panel"], fg=COLORS["muted"]).pack(side=tk.LEFT)
        self.keyword_entry = self._entry(row1, width=36)
        self.keyword_entry.pack(side=tk.LEFT, padx=(8, 14), ipady=8)
        self.keyword_entry.bind("<Return>", lambda _e: self._on_search())

        tk.Label(row1, text="图源", bg=COLORS["panel"], fg=COLORS["muted"]).pack(side=tk.LEFT)
        self.source_cb = ttk.Combobox(
            row1,
            textvariable=self.source_var,
            values=SOURCES,
            width=16,
            state="readonly",
            style="App.TCombobox",
        )
        self.source_cb.pack(side=tk.LEFT, padx=(8, 14), ipady=5)

        tk.Label(row1, text="分辨率", bg=COLORS["panel"], fg=COLORS["muted"]).pack(side=tk.LEFT)
        self.resolution_cb = ttk.Combobox(
            row1,
            textvariable=self.resolution_var,
            values=RESOLUTION_OPTIONS,
            width=12,
            state="readonly",
            style="App.TCombobox",
        )
        self.resolution_cb.pack(side=tk.LEFT, padx=(8, 14), ipady=5)

        self.search_btn = self._button(row1, "搜索", self._on_search, primary=True, width=10)
        self.search_btn.pack(side=tk.LEFT)

        self.visual_check = tk.Checkbutton(
            row1,
            text="视觉校验/排序",
            variable=self.visual_var,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            activebackground=COLORS["panel"],
            activeforeground=COLORS["accent"],
            selectcolor=COLORS["input"],
            bd=0,
            cursor="hand2",
        )
        self.visual_check.pack(side=tk.LEFT, padx=(14, 0))

        row2 = tk.Frame(panel, bg=COLORS["panel"])
        row2.pack(fill=tk.X, padx=16, pady=(4, 8))

        tk.Label(row2, text="下载目录", bg=COLORS["panel"], fg=COLORS["muted"]).pack(side=tk.LEFT)
        self.path_entry = self._entry(row2)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8), ipady=8)
        self.path_entry.insert(0, DEFAULT_DOWNLOAD_DIR)

        self.path_btn = self._button(row2, "浏览", self._on_browse)
        self.path_btn.pack(side=tk.LEFT)

        row3 = tk.Frame(panel, bg=COLORS["panel"])
        row3.pack(fill=tk.X, padx=16, pady=(0, 16))

        tk.Label(row3, text="AI 提示词", bg=COLORS["panel"], fg=COLORS["muted"]).pack(side=tk.LEFT, anchor="n")
        self.ai_prompt = self._text(row3, height=3)
        self.ai_prompt.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8), ipady=4)
        self.ai_prompt.bind("<Control-Return>", lambda _e: self._on_ai_generate())

        self.ai_btn = self._button(row3, "AI生成并下载", self._on_ai_generate, primary=True, width=14)
        self.ai_btn.pack(side=tk.LEFT, anchor="n")

    def _build_middle(self):
        container = tk.Frame(self.root, bg=COLORS["bg"])
        container.pack(fill=tk.BOTH, expand=True, padx=16, pady=(8, 8))

        shell = tk.Frame(container, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        shell.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(shell, bg=COLORS["panel"], highlightthickness=0)
        self.vbar = tk.Scrollbar(shell, orient=tk.VERTICAL, command=self.canvas.yview)
        self.grid_frame = tk.Frame(self.canvas, bg=COLORS["panel"])

        self.grid_frame.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")

        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=10)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10), pady=10)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-event.delta / 60), "units")

        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _build_bottom(self):
        bottom = tk.Frame(self.root, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        bottom.pack(fill=tk.X, padx=16, pady=(0, 16))

        self.status_var = tk.StringVar(value="就绪")
        tk.Label(
            bottom,
            textvariable=self.status_var,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            anchor="w",
        ).pack(side=tk.LEFT, padx=14, pady=12)

        self.progress = ttk.Progressbar(bottom, mode="determinate", length=240, style="App.Horizontal.TProgressbar")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        self.selected_var = tk.StringVar(value="已选 0")
        tk.Label(bottom, textvariable=self.selected_var, bg=COLORS["panel"], fg=COLORS["muted"]).pack(
            side=tk.LEFT, padx=(0, 10)
        )

        self.more_btn = self._button(bottom, "加载更多", self._on_load_more, state=tk.DISABLED)
        self.more_btn.pack(side=tk.RIGHT, padx=(4, 12), pady=10)

        self.dl_btn = self._button(bottom, "下载选中", self._on_download, primary=True, state=tk.DISABLED)
        self.dl_btn.pack(side=tk.RIGHT, padx=4, pady=10)

        self.select_all_btn = self._button(bottom, "全选", self._select_all, state=tk.DISABLED)
        self.select_all_btn.pack(side=tk.RIGHT, padx=4, pady=10)

        self.clear_sel_btn = self._button(bottom, "清空选择", self._clear_selection, state=tk.DISABLED)
        self.clear_sel_btn.pack(side=tk.RIGHT, padx=4, pady=10)

    def _on_canvas_resize(self, event):
        width = event.width if event else self.canvas.winfo_width()
        if width > 0:
            self.canvas.itemconfig(self.canvas_window, width=max(1, width - 18))
            if self._resize_job:
                self.root.after_cancel(self._resize_job)
            self._resize_job = self.root.after(70, self._layout_cells)

    def _on_browse(self):
        path = filedialog.askdirectory()
        if path:
            self.download_path.set(path)
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, path)

    def _selected_resolution(self):
        resolution = self.resolution_var.get().strip()
        if not resolution or resolution == RESOLUTION_ORIGINAL:
            return ""
        return resolution if resolution in RESOLUTION_OPTIONS else ""

    def _active_crawlers(self, source):
        choices = [
            (WallpapersCraftCrawler.name(), WallpapersCraftCrawler),
            (BaiduCrawler.name(), BaiduCrawler),
            (HaoWallpaperCrawler.name(), HaoWallpaperCrawler),
            (WallhavenCrawler.name(), WallhavenCrawler),
        ]
        if source == SOURCE_ALL:
            crawlers = [cls() for _name, cls in choices]
        else:
            crawlers = [cls() for name, cls in choices if name == source]

        resolution = self._resolution
        for crawler in crawlers:
            set_resolution = getattr(crawler, "set_resolution", None)
            if callable(set_resolution):
                set_resolution(resolution)
        return crawlers

    def _on_search(self):
        keyword = self.keyword_entry.get().strip()
        if not keyword or self.searching:
            return

        self.searching = True
        self.loading_more = False
        self.keyword = keyword
        self._source = self.source_var.get()
        self._resolution = self._selected_resolution()
        self._errors = []

        self.search_btn.config(state=tk.DISABLED, text="搜索中...")
        self.more_btn.config(state=tk.DISABLED)
        self.dl_btn.config(state=tk.DISABLED)
        self.select_all_btn.config(state=tk.DISABLED)
        self.clear_sel_btn.config(state=tk.DISABLED)
        self.progress["value"] = 0
        self.status_var.set("正在搜索...")
        self._clear_grid()

        threading.Thread(target=self._search_worker, daemon=True).start()

    def _search_worker(self):
        self._crawlers = self._active_crawlers(self._source)
        if not self._crawlers:
            self.root.after(0, lambda: self._on_search_done([]))
            return

        per_source = MAX_IMAGES if self._source != SOURCE_ALL else max(20, MAX_IMAGES // len(self._crawlers) + 15)
        raw_items = []

        def crawl(crawler):
            try:
                return crawler.name(), crawler.search(self.keyword, per_source)
            except Exception as exc:
                return crawler.name(), exc

        with ThreadPoolExecutor(max_workers=len(self._crawlers)) as pool:
            futures = [pool.submit(crawl, crawler) for crawler in self._crawlers]
            for future in as_completed(futures):
                name, result = future.result()
                if isinstance(result, Exception):
                    self._errors.append(f"{name}: {result}")
                else:
                    raw_items.extend(result)

        raw_items = dedupe_items(raw_items)
        if not raw_items:
            self.root.after(0, lambda: self._on_search_done([]))
            return

        self.root.after(0, lambda: self._set_status(f"找到 {len(raw_items)} 个候选，正在校验图片..."))

        def on_match_progress(done, total):
            self.root.after(
                0,
                lambda d=done, t=total: (
                    self.progress.configure(maximum=t, value=d),
                    self.status_var.set(f"正在校验图片... {d}/{t}"),
                ),
            )

        ranked = rank_items(
            raw_items,
            self.keyword,
            limit=MAX_IMAGES,
            visual_enabled=self.visual_var.get(),
            progress_callback=on_match_progress,
        )
        self.root.after(0, lambda items=ranked: self._on_search_done(items))

    def _on_search_done(self, items):
        self.searching = False
        self.items = items
        self.search_btn.config(state=tk.NORMAL, text="搜索")
        self.progress["value"] = 0

        count = len(self.items)
        if count == 0:
            msg = "未找到可用图片"
            if self._errors:
                msg += "；" + "；".join(self._errors[:2])
            self.status_var.set(msg)
            self.more_btn.config(state=tk.DISABLED)
            self.dl_btn.config(state=tk.DISABLED)
            self.select_all_btn.config(state=tk.DISABLED)
            self.clear_sel_btn.config(state=tk.DISABLED)
            return

        suffix = f"，错误 {len(self._errors)} 个源" if self._errors else ""
        self.status_var.set(f"找到 {count} 张可用图片{suffix}")
        self.more_btn.config(state=tk.NORMAL)
        self.dl_btn.config(state=tk.NORMAL)
        self.select_all_btn.config(state=tk.NORMAL)
        self.clear_sel_btn.config(state=tk.NORMAL)
        self._build_thumbnail_grid()
        threading.Thread(target=self._load_new_thumbnails, args=(0,), daemon=True).start()

    def _on_load_more(self):
        if self.searching or self.loading_more or not self.keyword or not self._crawlers:
            return
        self.loading_more = True
        self.more_btn.config(state=tk.DISABLED, text="加载中...")
        self.status_var.set("正在加载更多...")
        threading.Thread(target=self._load_more_worker, daemon=True).start()

    def _load_more_worker(self):
        raw_items = []

        def load(crawler):
            try:
                return crawler.name(), crawler.load_more(self.keyword, len(self.items), MAX_IMAGES)
            except Exception as exc:
                return crawler.name(), exc

        with ThreadPoolExecutor(max_workers=max(1, len(self._crawlers))) as pool:
            futures = [pool.submit(load, crawler) for crawler in self._crawlers]
            for future in as_completed(futures):
                name, result = future.result()
                if isinstance(result, Exception):
                    self._errors.append(f"{name}: {result}")
                else:
                    raw_items.extend(result)

        seen = {it.get("url") for it in self.items}
        new_items = [it for it in dedupe_items(raw_items) if it.get("url") not in seen]
        if not new_items:
            self.root.after(0, lambda: self._on_load_more_done([]))
            return

        ranked = rank_items(
            new_items,
            self.keyword,
            limit=MAX_IMAGES,
            visual_enabled=self.visual_var.get(),
        )
        self.root.after(0, lambda items=ranked: self._on_load_more_done(items))

    def _on_load_more_done(self, new_items):
        self.loading_more = False
        self.more_btn.config(state=tk.NORMAL, text="加载更多")
        if not new_items:
            self.status_var.set(f"共 {len(self.items)} 张，没有更多可用图片")
            return

        start = len(self.items)
        self.items.extend(new_items)
        for idx in range(start, len(self.items)):
            item = self.items[idx]
            item["var"] = tk.BooleanVar(value=False)
            item["frame"] = self._make_cell(self.grid_frame, idx)
        self._layout_cells()
        self.status_var.set(f"共 {len(self.items)} 张，新增 {len(new_items)} 张")
        threading.Thread(target=self._load_new_thumbnails, args=(start,), daemon=True).start()

    def _clear_grid(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        self.items = []
        self.image_refs.clear()
        self._update_selected()

    def _build_thumbnail_grid(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        self.image_refs.clear()
        for idx, item in enumerate(self.items):
            item["var"] = tk.BooleanVar(value=False)
            item["frame"] = self._make_cell(self.grid_frame, idx)
        self._layout_cells()
        self._update_selected()

    def _make_cell(self, parent, idx):
        item = self.items[idx]
        size = self._thumb_size
        cell = tk.Frame(
            parent,
            bg=COLORS["card"],
            padx=10,
            pady=10,
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )

        img_label = tk.Label(
            cell,
            bg=COLORS["input"],
            cursor="hand2",
            bd=0,
        )
        img_label.pack()
        placeholder = self._placeholder(idx, size)
        item["_photo"] = placeholder
        img_label.config(image=placeholder)
        img_label.bind("<Button-1>", lambda _e, i=idx: self._toggle_item(i))

        score = item.get("_score")
        source = item.get("source", "")
        label = f"#{idx + 1}  {source}"
        site_confidence = item.get("bing_confidence") or item.get("wallpaperscraft_confidence")
        if site_confidence is not None:
            label += f"  · 置信 {int(site_confidence)}%"
        if score is not None:
            label += f"  · 评分 {score:.1f}"

        cb = tk.Checkbutton(
            cell,
            text=label,
            variable=item["var"],
            command=self._update_selected,
            bg=COLORS["card"],
            fg=COLORS["text"],
            activebackground=COLORS["card"],
            activeforeground=COLORS["accent"],
            selectcolor=COLORS["input"],
            bd=0,
            anchor="w",
            justify=tk.LEFT,
            wraplength=size[0],
            cursor="hand2",
        )
        cb.pack(anchor="w", pady=(8, 2))

        title = item.get("title") or item.get("_match_reason") or ""
        if len(title) > 34:
            title = title[:33] + "..."
        title_label = tk.Label(
            cell,
            text=title,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            wraplength=size[0],
            justify=tk.LEFT,
            anchor="w",
        )
        title_label.pack(anchor="w")

        item["img_lbl"] = img_label
        item["check_lbl"] = cb
        item["title_lbl"] = title_label
        return cell

    def _placeholder(self, idx, size=None):
        size = size or self._thumb_size
        img = Image.new("RGB", size, COLORS["input"])
        draw = ImageDraw.Draw(img)
        text = str(idx + 1)
        bbox = draw.textbbox((0, 0), text)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        radius = max(18, min(size) // 9)
        draw.rounded_rectangle((5, 5, size[0] - 5, size[1] - 5), radius=radius, outline=COLORS["line"], width=2)
        draw.text(((size[0] - tw) / 2, (size[1] - th) / 2), text, fill=COLORS["muted"])
        return ImageTk.PhotoImage(img)

    def _layout_cells(self):
        self._resize_job = None
        if not self.items:
            return
        width = max(self.canvas.winfo_width() - 28, THUMBNAIL_COL_MIN_WIDTH)
        old_size = self._thumb_size
        cols = self._adaptive_columns(width)
        self._thumb_size = self._adaptive_thumb_size(width, cols)
        for idx, item in enumerate(self.items):
            frame = item.get("frame")
            if not frame:
                continue
            frame.grid_forget()
            frame.grid(row=idx // cols, column=idx % cols, padx=7, pady=7, sticky="n")
        if old_size != self._thumb_size:
            self._refresh_thumbnail_sizes()

    def _adaptive_columns(self, width):
        available = max(width, THUMBNAIL_COL_MIN_WIDTH)
        cols = max(1, available // THUMBNAIL_COL_MIN_WIDTH)
        while cols > 1:
            side = self._adaptive_thumb_size(available, cols)[0]
            if side >= 140:
                break
            cols -= 1
        return cols

    def _adaptive_thumb_size(self, width, cols):
        # Reserve card padding, grid gaps, border, and a right safety gutter so
        # the last column never gets clipped by the canvas edge.
        side = int(max(width, 160) / max(cols, 1)) - 44
        side = max(140, min(248, side))
        return (side, side)

    def _render_thumb_image(self, img, size):
        thumb = img.copy()
        if thumb.mode not in ("RGB", "RGBA"):
            thumb = thumb.convert("RGB")
        thumb.thumbnail(size, Image.LANCZOS)

        canvas_img = Image.new("RGB", size, COLORS["input"])
        x = (size[0] - thumb.width) // 2
        y = (size[1] - thumb.height) // 2
        if thumb.mode == "RGBA":
            canvas_img.paste(thumb, (x, y), thumb)
        else:
            canvas_img.paste(thumb.convert("RGB"), (x, y))

        mask = Image.new("L", size, 0)
        radius = max(18, min(size) // 10)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
        rounded = Image.new("RGB", size, COLORS["input"])
        rounded.paste(canvas_img, (0, 0), mask)
        return rounded

    def _refresh_thumbnail_sizes(self):
        for idx, item in enumerate(self.items):
            label = item.get("img_lbl")
            if label and label.winfo_exists():
                pil_img = item.get("_thumb_pil")
                if pil_img is not None:
                    photo = ImageTk.PhotoImage(self._render_thumb_image(pil_img, self._thumb_size))
                else:
                    photo = self._placeholder(idx, self._thumb_size)
                item["_photo"] = photo
                label.config(image=photo)

            title_label = item.get("title_lbl")
            if title_label and title_label.winfo_exists():
                title_label.config(wraplength=self._thumb_size[0])

            check_label = item.get("check_lbl")
            if check_label and check_label.winfo_exists():
                check_label.config(wraplength=self._thumb_size[0])

    def _load_new_thumbnails(self, start):
        def fetch(idx, item):
            data, _url, _ctype = fetch_image_bytes(item)
            if not data:
                return idx, None
            try:
                img = Image.open(BytesIO(data))
                img.load()
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                return idx, img.copy()
            except Exception:
                return idx, None

        with ThreadPoolExecutor(max_workers=THUMBNAIL_WORKERS) as pool:
            futures = [pool.submit(fetch, idx, self.items[idx]) for idx in range(start, len(self.items))]
            for future in as_completed(futures):
                idx, img = future.result()
                if img is not None:
                    self.root.after(0, lambda i=idx, im=img: self._set_thumb(i, im))

    def _set_thumb(self, idx, img):
        if idx >= len(self.items):
            return
        item = self.items[idx]
        label = item.get("img_lbl")
        if not label or not label.winfo_exists():
            return
        item["_thumb_pil"] = img
        photo = ImageTk.PhotoImage(self._render_thumb_image(img, self._thumb_size))
        item["_photo"] = photo
        label.config(image=photo)

    def _toggle_item(self, idx):
        if idx >= len(self.items):
            return
        var = self.items[idx].get("var")
        if var:
            var.set(not var.get())
            self._update_selected()

    def _select_all(self):
        for item in self.items:
            var = item.get("var")
            if var:
                var.set(True)
        self._update_selected()

    def _clear_selection(self):
        for item in self.items:
            var = item.get("var")
            if var:
                var.set(False)
        self._update_selected()

    def _update_selected(self):
        selected = sum(1 for item in self.items if item.get("var") and item["var"].get())
        self.selected_var.set(f"已选 {selected}")

    def _on_ai_generate(self):
        if self.ai_generating:
            return
        if self.searching or self.loading_more:
            messagebox.showinfo("提示", "请等待当前搜索任务完成。")
            return

        prompt = self.ai_prompt.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showinfo("提示", "请先输入 AI 图片提示词。")
            return

        save_dir = self.path_entry.get().strip() or DEFAULT_DOWNLOAD_DIR
        target_resolution = self._selected_resolution()

        self.ai_generating = True
        self.ai_btn.config(state=tk.DISABLED, text="AI生成中...")
        self.search_btn.config(state=tk.DISABLED)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        target_text = f"，输出 {target_resolution}" if target_resolution else ""
        self.status_var.set(f"AI 正在生成图片{target_text}...")

        threading.Thread(
            target=self._ai_generate_worker,
            args=(prompt, save_dir, target_resolution),
            daemon=True,
        ).start()

    def _ai_generate_worker(self, prompt, save_dir, target_resolution):
        try:
            paths = AIImageClient().generate_and_save(prompt, save_dir, target_resolution)
            error = ""
        except Exception as exc:
            paths = []
            error = str(exc)
        self.root.after(
            0,
            lambda: self._on_ai_generate_done(paths, error, save_dir, target_resolution),
        )

    def _on_ai_generate_done(self, paths, error, save_dir, target_resolution):
        self.ai_generating = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress["value"] = 0
        self.ai_btn.config(state=tk.NORMAL, text="AI生成并下载")
        self.search_btn.config(state=tk.NORMAL)

        if error:
            self.status_var.set(f"AI 生成失败：{error}")
            messagebox.showerror("AI 生成失败", error)
            return

        msg = f"AI 生成完成：成功 {len(paths)} 张"
        if target_resolution:
            msg += f"，分辨率 {target_resolution}"
        msg += f" -> {os.path.abspath(save_dir)}"
        self.status_var.set(msg)

    def _on_download(self):
        selected = [item for item in self.items if item.get("var") and item["var"].get()]
        if not selected:
            messagebox.showinfo("提示", "请先选择要下载的图片。")
            return

        keyword = self.keyword_entry.get().strip() or "image"
        save_dir = self.path_entry.get().strip() or DEFAULT_DOWNLOAD_DIR
        target_resolution = self._selected_resolution()

        self.dl_btn.config(state=tk.DISABLED, text="下载中...")
        self.more_btn.config(state=tk.DISABLED)
        self.progress["maximum"] = len(selected)
        self.progress["value"] = 0
        threading.Thread(
            target=self._download_worker,
            args=(selected, keyword, save_dir, target_resolution),
            daemon=True,
        ).start()

    def _download_worker(self, selected, keyword, save_dir, target_resolution):
        def on_progress(done, total):
            self.root.after(
                0,
                lambda d=done, t=total: (
                    self.progress.configure(maximum=t, value=d),
                    self.status_var.set(f"正在下载... {d}/{t}"),
                ),
            )

        downloader = Downloader(save_dir, target_resolution=target_resolution)
        results = downloader.download(selected, keyword, on_progress)
        ok = sum(1 for result in results if result and result[0])
        fail = sum(1 for result in results if result and not result[0])
        self.root.after(0, lambda: self._on_download_done(ok, fail, save_dir, target_resolution))

    def _on_download_done(self, ok, fail, save_dir, target_resolution):
        self.dl_btn.config(state=tk.NORMAL, text="下载选中")
        self.more_btn.config(state=tk.NORMAL if self.items else tk.DISABLED)
        self.progress["value"] = 0
        msg = f"完成：成功 {ok} 张"
        if fail:
            msg += f"，失败 {fail} 张"
        if target_resolution:
            msg += f"，分辨率 {target_resolution}"
        msg += f" -> {os.path.abspath(save_dir)}"
        self.status_var.set(msg)
        self._update_selected()

    def _set_status(self, text):
        self.status_var.set(text)

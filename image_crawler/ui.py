# -*- coding: utf-8 -*-

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

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


SOURCE_ALL = "全部"
SOURCE_WALLPAPERSCRAFT = "WallpapersCraft"
SOURCE_BAIDU = "百度"
SOURCE_HAO_WALLPAPER = "好壁纸"
SOURCE_WALLHAVEN = "Wallhaven"
SOURCES = [
    SOURCE_ALL,
    SOURCE_WALLPAPERSCRAFT,
    SOURCE_BAIDU,
    SOURCE_HAO_WALLPAPER,
    SOURCE_WALLHAVEN,
]

_PIL_IMAGE = None
_PIL_IMAGE_DRAW = None
_PIL_IMAGE_TK = None
_THUMB_MASK_CACHE = {}


def _pil_image():
    global _PIL_IMAGE
    if _PIL_IMAGE is None:
        from PIL import Image

        _PIL_IMAGE = Image
    return _PIL_IMAGE


def _pil_image_draw():
    global _PIL_IMAGE_DRAW
    if _PIL_IMAGE_DRAW is None:
        from PIL import ImageDraw

        _PIL_IMAGE_DRAW = ImageDraw
    return _PIL_IMAGE_DRAW


def _pil_image_tk():
    global _PIL_IMAGE_TK
    if _PIL_IMAGE_TK is None:
        from PIL import ImageTk

        _PIL_IMAGE_TK = ImageTk
    return _PIL_IMAGE_TK


def _rounded_thumb_mask(size):
    key = tuple(size)
    mask = _THUMB_MASK_CACHE.get(key)
    if mask is None:
        Image = _pil_image()
        ImageDraw = _pil_image_draw()
        mask = Image.new("L", key, 0)
        radius = max(18, min(key) // 10)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, key[0], key[1]), radius=radius, fill=255)
        _THUMB_MASK_CACHE[key] = mask
    return mask


def _resource_path(relative_path):
    base_dir = getattr(sys, "_MEIPASS", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    return os.path.join(base_dir, relative_path)

COLORS = {
    "bg": "#f5f5f7",
    "panel": "#ffffff",
    "panel_soft": "#fbfbfd",
    "card": "#ffffff",
    "card_alt": "#eef0f5",
    "line": "#e5e5ea",
    "line_dark": "#d1d1d6",
    "text": "#1d1d1f",
    "muted": "#6e6e73",
    "accent": "#007aff",
    "accent_dark": "#0066d6",
    "success": "#34c759",
    "warning": "#ff9500",
    "danger": "#ff3b30",
    "input": "#f7f7fa",
    "input_focus": "#ffffff",
}


class SmoothDropdown:
    def __init__(self, parent, variable, values, width=14, fonts=None):
        self.parent = parent
        self.root = parent.winfo_toplevel()
        self.variable = variable
        self.values = list(values)
        self.fonts = fonts or {}
        self.width_px = max(120, int(width * 8 + 42))
        self.row_height = 30
        self.popup = None
        self.popup_frame = None
        self._animating = False
        self._root_click_bind = None
        self._root_escape_bind = None

        self.frame = tk.Frame(
            parent,
            width=self.width_px,
            height=34,
            bg=COLORS["input"],
            highlightbackground=COLORS["line"],
            highlightcolor=COLORS["accent"],
            highlightthickness=1,
            cursor="hand2",
        )
        self.frame.pack_propagate(False)

        self.label = tk.Label(
            self.frame,
            textvariable=self.variable,
            bg=COLORS["input"],
            fg=COLORS["text"],
            anchor="w",
            padx=10,
            font=self.fonts.get("input"),
            cursor="hand2",
        )
        self.label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.arrow = tk.Canvas(self.frame, width=22, height=22, bg=COLORS["input"], highlightthickness=0, bd=0)
        self.arrow.pack(side=tk.RIGHT, padx=(0, 6))
        self._draw_arrow(False)

        for widget in (self.frame, self.label, self.arrow):
            widget.bind("<Button-1>", self._toggle)
            widget.bind("<Enter>", self._hover_on)
            widget.bind("<Leave>", self._hover_off)

    def pack(self, *args, **kwargs):
        return self.frame.pack(*args, **kwargs)

    def grid(self, *args, **kwargs):
        return self.frame.grid(*args, **kwargs)

    def place(self, *args, **kwargs):
        return self.frame.place(*args, **kwargs)

    def _draw_arrow(self, opened):
        self.arrow.delete("all")
        if opened:
            points = (6, 13, 11, 8, 16, 13)
        else:
            points = (6, 9, 11, 14, 16, 9)
        self.arrow.create_line(*points, fill=COLORS["muted"], width=2, capstyle=tk.ROUND, joinstyle=tk.ROUND)

    def _hover_on(self, _event=None):
        if self.popup is None:
            self.frame.config(bg=COLORS["input_focus"], highlightbackground=COLORS["accent"])
            self.label.config(bg=COLORS["input_focus"])
            self.arrow.config(bg=COLORS["input_focus"])

    def _hover_off(self, _event=None):
        if self.popup is None:
            self.frame.config(bg=COLORS["input"], highlightbackground=COLORS["line"])
            self.label.config(bg=COLORS["input"])
            self.arrow.config(bg=COLORS["input"])

    def _toggle(self, _event=None):
        if self.popup is not None:
            self._close()
        else:
            self._open()

    def _open(self):
        if self.popup is not None or self._animating:
            return
        self.root.update_idletasks()
        x = self.frame.winfo_rootx()
        y = self.frame.winfo_rooty() + self.frame.winfo_height() + 4
        width = max(self.frame.winfo_width(), self.width_px)
        target_height = max(1, len(self.values) * self.row_height + 6)

        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        place_x = x - root_x
        place_y = y - root_y

        self.popup = tk.Frame(
            self.root,
            bg=COLORS["panel"],
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )
        self.popup.place(x=place_x, y=place_y, width=width, height=1)
        self.popup.lift()
        self.popup_frame = self.popup

        for value in self.values:
            selected = value == self.variable.get()
            row_bg = "#eaf3ff" if selected else COLORS["panel"]
            row_fg = COLORS["accent"] if selected else COLORS["text"]
            row = tk.Label(
                self.popup_frame,
                text=value,
                bg=row_bg,
                fg=row_fg,
                anchor="w",
                padx=12,
                font=self.fonts.get("body"),
                cursor="hand2",
            )
            row.pack(fill=tk.X, ipady=6)
            row.bind("<Enter>", lambda _e, w=row: w.config(bg=COLORS["input"]))
            row.bind("<Leave>", lambda _e, w=row, bg=row_bg: w.config(bg=bg))
            row.bind("<Button-1>", lambda _e, v=value: self._select(v))

        self.frame.config(bg=COLORS["input_focus"], highlightbackground=COLORS["accent"])
        self.label.config(bg=COLORS["input_focus"])
        self.arrow.config(bg=COLORS["input_focus"])
        self._draw_arrow(True)
        self._animating = True
        self._animate_open(width, target_height, 1)

    def _animate_open(self, width, target_height, step):
        if self.popup is None:
            self._animating = False
            return
        steps = 9
        progress = min(1.0, step / steps)
        eased = 1 - (1 - progress) ** 3
        height = max(1, int(target_height * eased))
        self.popup.place_configure(width=width, height=height)
        self.popup.lift()
        if step < steps:
            self.root.after(12, lambda: self._animate_open(width, target_height, step + 1))
        else:
            self._animating = False
            self.popup.focus_set()
            self.popup.bind("<Escape>", lambda _e: self._close())
            if self._root_click_bind is None:
                self.root.after(1, self._bind_close_events)

    def _bind_close_events(self):
        if self.popup is None:
            return
        if self._root_click_bind is None:
            self._root_click_bind = self.root.bind("<Button-1>", self._root_click_close, add="+")
        if self._root_escape_bind is None:
            self._root_escape_bind = self.root.bind("<Escape>", lambda _e: self._close(), add="+")

    def _select(self, value):
        self.variable.set(value)
        self._close()

    def _root_click_close(self, event):
        if self.popup is None:
            return
        popup_inside = self._point_in_widget(event, self.popup)
        control_inside = self._point_in_widget(event, self.frame)
        if not popup_inside and not control_inside:
            self._close()

    def _point_in_widget(self, event, widget):
        try:
            x1 = widget.winfo_rootx()
            y1 = widget.winfo_rooty()
            x2 = x1 + widget.winfo_width()
            y2 = y1 + widget.winfo_height()
        except tk.TclError:
            return False
        return x1 <= event.x_root <= x2 and y1 <= event.y_root <= y2

    def _close(self):
        if self.popup is None or self._animating:
            return
        popup = self.popup
        width = popup.winfo_width()
        start_height = max(1, popup.winfo_height())
        self._animating = True
        self._animate_close(popup, width, start_height, 1)

    def _animate_close(self, popup, width, start_height, step):
        steps = 7
        progress = min(1.0, step / steps)
        eased = 1 - (1 - progress) ** 3
        height = max(1, int(start_height * (1 - eased)))
        try:
            popup.place_configure(width=width, height=height)
        except tk.TclError:
            pass
        if step < steps:
            self.root.after(10, lambda: self._animate_close(popup, width, start_height, step + 1))
            return

        try:
            popup.place_forget()
            popup.destroy()
        except tk.TclError:
            pass
        if self.popup is popup:
            self.popup = None
            self.popup_frame = None
        self._animating = False
        self.frame.config(bg=COLORS["input"], highlightbackground=COLORS["line"])
        self.label.config(bg=COLORS["input"])
        self.arrow.config(bg=COLORS["input"])
        self._draw_arrow(False)
        if self._root_click_bind is not None:
            try:
                self.root.unbind("<Button-1>", self._root_click_bind)
            except tk.TclError:
                pass
            self._root_click_bind = None
        if self._root_escape_bind is not None:
            try:
                self.root.unbind("<Escape>", self._root_escape_bind)
            except tk.TclError:
                pass
            self._root_escape_bind = None


class ImageCrawlerUI:
    def __init__(self, root):
        self.root = root
        root.title("Image Crawler Pro")
        root.geometry("1160x820")
        root.minsize(820, 580)
        root.configure(bg=COLORS["bg"])
        self._set_app_icon()

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
        self._thumbnail_generation = 0
        self.keyword = ""
        self._source = SOURCE_ALL
        self._resolution = ""
        self._crawlers = []
        self._errors = []
        self._drag_offset = (0, 0)
        self._resize_start = (0, 0, 0, 0)
        self._custom_frame_enabled = False
        self._is_maximized = False
        self._normal_geometry = ""

        self._init_fonts()
        self._configure_style()
        self._build_top()
        self._build_middle()
        self._build_bottom()
        self._enable_custom_window()

    def _set_app_icon(self):
        icon_path = _resource_path(os.path.join("assets", "app.ico"))
        png_path = _resource_path(os.path.join("assets", "app.png"))
        try:
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
                return
        except Exception:
            pass
        try:
            if os.path.exists(png_path):
                self._window_icon = tk.PhotoImage(file=png_path)
                self.root.iconphoto(True, self._window_icon)
        except Exception:
            pass

    def _init_fonts(self):
        try:
            families = set(tkfont.families(self.root))
        except Exception:
            families = set()
        family = next(
            (
                name
                for name in (
                    "SF Pro Text",
                    "SF Pro Display",
                    "Segoe UI Variable",
                    "Segoe UI",
                    "Microsoft YaHei UI",
                )
                if name in families
            ),
            "Segoe UI",
        )
        self.fonts = {
            "title": (family, 22, "bold"),
            "subtitle": (family, 10),
            "body": (family, 10),
            "input": (family, 11),
            "button": (family, 10),
            "button_bold": (family, 10, "bold"),
            "badge": (family, 9, "bold"),
            "placeholder": (family, 18, "bold"),
        }
        self.root.option_add("*Font", self.fonts["body"])

    def _enable_custom_window(self):
        self._custom_frame_enabled = True
        self._apply_borderless()
        self.root.after(0, self._apply_borderless)
        self.root.bind("<Map>", self._restore_borderless_after_map, add="+")

    def _apply_borderless(self):
        if not self._custom_frame_enabled:
            return
        try:
            self.root.overrideredirect(True)
        except tk.TclError:
            pass

    def _restore_borderless_after_map(self, _event=None):
        if self._custom_frame_enabled:
            self.root.after(20, self._apply_borderless)

    def _bind_window_drag(self, *widgets):
        for widget in widgets:
            widget.bind("<ButtonPress-1>", self._start_window_move)
            widget.bind("<B1-Motion>", self._move_window)
            widget.bind("<Double-Button-1>", lambda _e: self._toggle_maximize())

    def _start_window_move(self, event):
        if self._is_maximized:
            ratio = event.x_root / max(self.root.winfo_width(), 1)
            self._toggle_maximize()
            self.root.update_idletasks()
            self._drag_offset = (int(self.root.winfo_width() * ratio), event.y_root - self.root.winfo_y())
            return
        self._drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _move_window(self, event):
        if self._is_maximized:
            return
        dx, dy = self._drag_offset
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _start_window_resize(self, event):
        if self._is_maximized:
            return
        self._resize_start = (event.x_root, event.y_root, self.root.winfo_width(), self.root.winfo_height())

    def _resize_window(self, event):
        if self._is_maximized:
            return
        start_x, start_y, start_w, start_h = self._resize_start
        min_w, min_h = self.root.minsize()
        width = max(min_w, start_w + event.x_root - start_x)
        height = max(min_h, start_h + event.y_root - start_y)
        self.root.geometry(f"{width}x{height}")

    def _work_area(self):
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except Exception:
            pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

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
            troughcolor=COLORS["line"],
            background=COLORS["accent"],
            bordercolor=COLORS["line"],
            lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent_dark"],
        )
        style.configure(
            "App.TCombobox",
            fieldbackground=COLORS["input"],
            background=COLORS["input"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["accent"],
            bordercolor=COLORS["line"],
            insertcolor=COLORS["text"],
            padding=(8, 6, 8, 6),
        )
        style.map(
            "App.TCombobox",
            fieldbackground=[("readonly", COLORS["input"])],
            selectbackground=[("readonly", COLORS["input"])],
            selectforeground=[("readonly", COLORS["text"])],
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
            pady=9,
            relief=tk.FLAT,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            disabledforeground="#64748b",
            font=self.fonts["button_bold"] if primary else self.fonts["button"],
            highlightthickness=0,
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
            font=self.fonts["input"],
            **options,
        )
        entry.bind("<FocusIn>", lambda _e, w=entry: w.config(bg=COLORS["input_focus"], highlightbackground=COLORS["accent"]))
        entry.bind("<FocusOut>", lambda _e, w=entry: w.config(bg=COLORS["input"], highlightbackground=COLORS["line"]))
        return entry

    def _text(self, parent, height=3):
        text = tk.Text(
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
            font=self.fonts["body"],
            wrap=tk.WORD,
        )
        text.bind("<FocusIn>", lambda _e, w=text: w.config(bg=COLORS["input_focus"], highlightbackground=COLORS["accent"]))
        text.bind("<FocusOut>", lambda _e, w=text: w.config(bg=COLORS["input"], highlightbackground=COLORS["line"]))
        return text

    def _traffic_lights(self, parent):
        canvas = tk.Canvas(parent, width=56, height=14, bg=COLORS["panel"], highlightthickness=0, bd=0)
        controls = (
            ("close", "#ff5f57", self._close_window),
            ("minimize", "#ffbd2e", self._minimize_window),
            ("maximize", "#28c840", self._toggle_maximize),
        )
        hit_areas = []
        for idx, (name, color, command) in enumerate(controls):
            x = 7 + idx * 18
            canvas.create_oval(x - 5, 2, x + 5, 12, fill=color, outline=color)
            hit_areas.append((name, command, x))
        canvas._traffic_hit_areas = hit_areas
        canvas._traffic_active = None
        canvas.bind("<Motion>", lambda event, c=canvas: self._traffic_motion(c, event))
        canvas.bind("<Leave>", lambda _event, c=canvas: self._traffic_leave(c))
        canvas.bind("<Button-1>", lambda event, c=canvas: self._traffic_click(c, event))
        return canvas

    def _traffic_hit(self, canvas, event):
        for name, command, x in getattr(canvas, "_traffic_hit_areas", ()):
            if (event.x - x) ** 2 + (event.y - 7) ** 2 <= 36:
                return name, command, x
        return None

    def _traffic_motion(self, canvas, event):
        hit = self._traffic_hit(canvas, event)
        active_name = hit[0] if hit else None
        if getattr(canvas, "_traffic_active", None) == active_name:
            return
        canvas._traffic_active = active_name
        if hit:
            name, _command, x = hit
            canvas.config(cursor="hand2")
            self._show_window_icon(canvas, name, x)
        else:
            canvas.config(cursor="")
            self._hide_window_icon(canvas)

    def _traffic_leave(self, canvas):
        canvas._traffic_active = None
        canvas.config(cursor="")
        self._hide_window_icon(canvas)

    def _traffic_click(self, canvas, event):
        hit = self._traffic_hit(canvas, event)
        if hit:
            _name, command, _x = hit
            command()

    def _show_window_icon(self, canvas, name, x):
        canvas.delete("window_icon")
        color = "#4b4b4f"
        if name == "close":
            canvas.create_line(x - 2, 5, x + 2, 9, fill=color, width=1.4, tags="window_icon")
            canvas.create_line(x + 2, 5, x - 2, 9, fill=color, width=1.4, tags="window_icon")
        elif name == "minimize":
            canvas.create_line(x - 3, 7, x + 3, 7, fill=color, width=1.5, tags="window_icon")
        elif name == "maximize":
            canvas.create_rectangle(x - 3, 4, x + 3, 10, outline=color, width=1.2, tags="window_icon")

    def _hide_window_icon(self, canvas):
        canvas.delete("window_icon")

    def _close_window(self):
        self.root.destroy()

    def _minimize_window(self):
        try:
            self.root.overrideredirect(False)
        except tk.TclError:
            pass
        self.root.iconify()

    def _toggle_maximize(self):
        if self._is_maximized:
            if self._normal_geometry:
                self.root.geometry(self._normal_geometry)
            self._is_maximized = False
            return

        self._normal_geometry = self.root.geometry()
        x, y, width, height = self._work_area()
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self._is_maximized = True

    def _build_top(self):
        top = tk.Frame(self.root, bg=COLORS["bg"])
        top.pack(fill=tk.X, padx=18, pady=(10, 6))

        header = tk.Frame(top, bg=COLORS["panel"], highlightthickness=0)
        header.pack(fill=tk.X)

        title_box = tk.Frame(header, bg=COLORS["panel"])
        title_box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=18, pady=10)
        self._traffic_lights(title_box).pack(anchor="w", pady=(0, 7))
        title_label = tk.Label(
            title_box,
            text="Image Crawler Pro",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=self.fonts["title"],
        )
        title_label.pack(anchor="w")
        subtitle_label = tk.Label(
            title_box,
            text="多源搜索 · AI生成 · 视觉校验 · 高清下载",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=self.fonts["subtitle"],
        )
        subtitle_label.pack(anchor="w", pady=(4, 0))
        self._bind_window_drag(header, title_box, title_label, subtitle_label)

        self.cv_status_var = tk.StringVar(value="OpenCV 按需加载")
        status_badge = tk.Label(
            header,
            textvariable=self.cv_status_var,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            padx=12,
            pady=8,
            font=self.fonts["badge"],
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )
        status_badge.pack(side=tk.RIGHT, padx=18)
        self._bind_window_drag(status_badge)

        panel = tk.Frame(top, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        panel.pack(fill=tk.X, pady=(8, 0))

        row1 = tk.Frame(panel, bg=COLORS["panel"])
        row1.pack(fill=tk.X, padx=18, pady=(12, 6))

        tk.Label(row1, text="关键词", bg=COLORS["panel"], fg=COLORS["muted"], font=self.fonts["body"]).pack(side=tk.LEFT)
        self.keyword_entry = self._entry(row1, width=36)
        self.keyword_entry.pack(side=tk.LEFT, padx=(8, 14), ipady=9)
        self.keyword_entry.bind("<Return>", lambda _e: self._on_search())

        tk.Label(row1, text="图源", bg=COLORS["panel"], fg=COLORS["muted"], font=self.fonts["body"]).pack(side=tk.LEFT)
        self.source_cb = SmoothDropdown(row1, self.source_var, SOURCES, width=16, fonts=self.fonts)
        self.source_cb.pack(side=tk.LEFT, padx=(8, 14), ipady=6)

        tk.Label(row1, text="分辨率", bg=COLORS["panel"], fg=COLORS["muted"], font=self.fonts["body"]).pack(side=tk.LEFT)
        self.resolution_cb = SmoothDropdown(row1, self.resolution_var, RESOLUTION_OPTIONS, width=12, fonts=self.fonts)
        self.resolution_cb.pack(side=tk.LEFT, padx=(8, 14), ipady=6)

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
            font=self.fonts["body"],
            cursor="hand2",
        )
        self.visual_check.pack(side=tk.LEFT, padx=(14, 0))

        row2 = tk.Frame(panel, bg=COLORS["panel"])
        row2.pack(fill=tk.X, padx=18, pady=(2, 6))

        tk.Label(row2, text="下载目录", bg=COLORS["panel"], fg=COLORS["muted"], font=self.fonts["body"]).pack(side=tk.LEFT)
        self.path_entry = self._entry(row2)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8), ipady=9)
        self.path_entry.insert(0, DEFAULT_DOWNLOAD_DIR)

        self.path_btn = self._button(row2, "浏览", self._on_browse)
        self.path_btn.pack(side=tk.LEFT)

        row3 = tk.Frame(panel, bg=COLORS["panel"])
        row3.pack(fill=tk.X, padx=18, pady=(0, 12))

        tk.Label(row3, text="AI 提示词", bg=COLORS["panel"], fg=COLORS["muted"], font=self.fonts["body"]).pack(side=tk.LEFT, anchor="n")
        self.ai_prompt = self._text(row3, height=2)
        self.ai_prompt.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8), ipady=4)
        self.ai_prompt.bind("<Control-Return>", lambda _e: self._on_ai_generate())

        self.ai_btn = self._button(row3, "AI生成并下载", self._on_ai_generate, primary=True, width=14)
        self.ai_btn.pack(side=tk.LEFT, anchor="n")

    def _build_middle(self):
        container = tk.Frame(self.root, bg=COLORS["bg"])
        container.pack(fill=tk.BOTH, expand=True, padx=18, pady=(6, 6))

        shell = tk.Frame(container, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        shell.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(shell, bg=COLORS["panel_soft"], highlightthickness=0)
        self.vbar = tk.Scrollbar(shell, orient=tk.VERTICAL, command=self.canvas.yview)
        self.grid_frame = tk.Frame(self.canvas, bg=COLORS["panel_soft"])

        self.grid_frame.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")

        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0), pady=10)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=10)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-event.delta / 60), "units")

        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _build_bottom(self):
        bottom = tk.Frame(self.root, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        bottom.pack(fill=tk.X, padx=18, pady=(0, 10))

        self.status_var = tk.StringVar(value="就绪")
        tk.Label(
            bottom,
            textvariable=self.status_var,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            anchor="w",
            font=self.fonts["body"],
        ).pack(side=tk.LEFT, padx=16, pady=10)

        self.progress = ttk.Progressbar(bottom, mode="determinate", length=240, style="App.Horizontal.TProgressbar")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        self.selected_var = tk.StringVar(value="已选 0")
        tk.Label(bottom, textvariable=self.selected_var, bg=COLORS["panel"], fg=COLORS["muted"], font=self.fonts["body"]).pack(
            side=tk.LEFT, padx=(0, 10)
        )

        self.resize_grip = tk.Canvas(bottom, width=16, height=16, bg=COLORS["panel"], highlightthickness=0, bd=0)
        for offset in (3, 7, 11):
            self.resize_grip.create_line(offset, 14, 14, offset, fill=COLORS["line_dark"], width=1)
        try:
            self.resize_grip.config(cursor="size_nw_se")
        except tk.TclError:
            pass
        self.resize_grip.bind("<ButtonPress-1>", self._start_window_resize)
        self.resize_grip.bind("<B1-Motion>", self._resize_window)
        self.resize_grip.pack(side=tk.RIGHT, padx=(2, 10), pady=8)

        self.more_btn = self._button(bottom, "加载更多", self._on_load_more, state=tk.DISABLED)
        self.more_btn.pack(side=tk.RIGHT, padx=(4, 8), pady=8)

        self.dl_btn = self._button(bottom, "下载选中", self._on_download, primary=True, state=tk.DISABLED)
        self.dl_btn.pack(side=tk.RIGHT, padx=4, pady=8)

        self.select_all_btn = self._button(bottom, "全选", self._select_all, state=tk.DISABLED)
        self.select_all_btn.pack(side=tk.RIGHT, padx=4, pady=8)

        self.clear_sel_btn = self._button(bottom, "清空选择", self._clear_selection, state=tk.DISABLED)
        self.clear_sel_btn.pack(side=tk.RIGHT, padx=4, pady=8)

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
        from .crawlers import BaiduCrawler, HaoWallpaperCrawler, WallpapersCraftCrawler, WallhavenCrawler

        choices = [
            (SOURCE_WALLPAPERSCRAFT, WallpapersCraftCrawler),
            (SOURCE_BAIDU, BaiduCrawler),
            (SOURCE_HAO_WALLPAPER, HaoWallpaperCrawler),
            (SOURCE_WALLHAVEN, WallhavenCrawler),
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
        try:
            from .crawlers import dedupe_items
            from .image_matcher import rank_items

            self._crawlers = self._active_crawlers(self._source)
        except Exception as exc:
            self._errors.append(f"初始化失败: {exc}")
            self.root.after(0, lambda: self._on_search_done([]))
            return

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
        generation = self._thumbnail_generation
        threading.Thread(target=self._load_new_thumbnails, args=(0, generation), daemon=True).start()

    def _on_load_more(self):
        if self.searching or self.loading_more or not self.keyword or not self._crawlers:
            return
        self.loading_more = True
        self.more_btn.config(state=tk.DISABLED, text="加载中...")
        self.status_var.set("正在加载更多...")
        threading.Thread(target=self._load_more_worker, daemon=True).start()

    def _load_more_worker(self):
        try:
            from .crawlers import dedupe_items
            from .image_matcher import rank_items
        except Exception as exc:
            self._errors.append(f"加载更多初始化失败: {exc}")
            self.root.after(0, lambda: self._on_load_more_done([]))
            return

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
        generation = self._thumbnail_generation
        threading.Thread(target=self._load_new_thumbnails, args=(start, generation), daemon=True).start()

    def _clear_grid(self):
        self._thumbnail_generation += 1
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
            padx=12,
            pady=12,
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )

        img_label = tk.Label(
            cell,
            bg=COLORS["input"],
            fg=COLORS["muted"],
            cursor="hand2",
            bd=0,
            font=self.fonts["placeholder"],
        )
        img_label.pack()
        placeholder = self._placeholder(idx, size)
        item["_photo"] = placeholder
        img_label.config(image=placeholder, text=f"#{idx + 1}", compound=tk.CENTER)
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
            font=self.fonts["body"],
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
            font=self.fonts["subtitle"],
        )
        title_label.pack(anchor="w")

        item["img_lbl"] = img_label
        item["check_lbl"] = cb
        item["title_lbl"] = title_label
        return cell

    def _placeholder(self, idx, size=None):
        size = size or self._thumb_size
        return tk.PhotoImage(width=size[0], height=size[1])

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
            frame.grid(row=idx // cols, column=idx % cols, padx=8, pady=8, sticky="n")
        if old_size != self._thumb_size:
            self._refresh_thumbnail_sizes()

    def _adaptive_columns(self, width):
        available = max(width, THUMBNAIL_COL_MIN_WIDTH)
        cols = max(1, available // THUMBNAIL_COL_MIN_WIDTH)
        while cols > 1:
            side = self._adaptive_thumb_size(available, cols)[0]
            if side >= 150:
                break
            cols -= 1
        return cols

    def _adaptive_thumb_size(self, width, cols):
        # Reserve card padding, grid gaps, border, and a right safety gutter so
        # the last column never gets clipped by the canvas edge.
        side = int(max(width, 160) / max(cols, 1)) - 52
        side = max(150, min(276, side))
        return (side, side)

    def _render_thumb_image(self, img, size):
        Image = _pil_image()

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

        mask = _rounded_thumb_mask(size)
        rounded = Image.new("RGB", size, COLORS["input"])
        rounded.paste(canvas_img, (0, 0), mask)
        return rounded

    def _refresh_thumbnail_sizes(self):
        ImageTk = None
        for idx, item in enumerate(self.items):
            label = item.get("img_lbl")
            if label and label.winfo_exists():
                pil_img = item.get("_thumb_pil")
                if pil_img is not None:
                    if ImageTk is None:
                        ImageTk = _pil_image_tk()
                    photo = ImageTk.PhotoImage(self._render_thumb_image(pil_img, self._thumb_size))
                    label.config(image=photo, text="")
                else:
                    photo = self._placeholder(idx, self._thumb_size)
                    label.config(image=photo, text=f"#{idx + 1}", compound=tk.CENTER)
                item["_photo"] = photo

            title_label = item.get("title_lbl")
            if title_label and title_label.winfo_exists():
                title_label.config(wraplength=self._thumb_size[0])

            check_label = item.get("check_lbl")
            if check_label and check_label.winfo_exists():
                check_label.config(wraplength=self._thumb_size[0])

    def _load_new_thumbnails(self, start, generation):
        items_snapshot = list(enumerate(self.items[start:], start))
        cached_items = []
        missing = []
        for idx, item in items_snapshot:
            cached = item.get("_thumb_pil")
            if cached is not None:
                cached_items.append((idx, cached))
            else:
                missing.append((idx, item))

        if cached_items:
            self.root.after(0, lambda batch=cached_items, g=generation: self._apply_cached_thumbnails(batch, g))

        if not missing:
            return

        try:
            from .image_matcher import fetch_image_bytes

            Image = _pil_image()
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._set_status(f"缩略图加载失败：{e}"))
            return

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
            futures = [pool.submit(fetch, idx, item) for idx, item in missing]
            for future in as_completed(futures):
                if generation != self._thumbnail_generation:
                    return
                idx, img = future.result()
                if img is not None:
                    self.root.after(0, lambda i=idx, im=img, g=generation: self._set_thumb(i, im, g))

    def _apply_cached_thumbnails(self, cached_items, generation, start=0, batch_size=8):
        if generation != self._thumbnail_generation:
            return
        end = min(len(cached_items), start + batch_size)
        for idx, img in cached_items[start:end]:
            self._set_thumb(idx, img, generation)
        if end < len(cached_items):
            self.root.after(12, lambda: self._apply_cached_thumbnails(cached_items, generation, end, batch_size))

    def _set_thumb(self, idx, img, generation):
        if generation != self._thumbnail_generation or idx >= len(self.items):
            return
        item = self.items[idx]
        label = item.get("img_lbl")
        if not label or not label.winfo_exists():
            return
        item["_thumb_pil"] = img
        ImageTk = _pil_image_tk()
        photo = ImageTk.PhotoImage(self._render_thumb_image(img, self._thumb_size))
        item["_photo"] = photo
        label.config(image=photo, text="")

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
            from .ai_generator import AIImageClient

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
        try:
            from .downloader import Downloader
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._on_download_error(str(e), save_dir))
            return

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

    def _on_download_error(self, error, save_dir):
        self.dl_btn.config(state=tk.NORMAL, text="下载选中")
        self.more_btn.config(state=tk.NORMAL if self.items else tk.DISABLED)
        self.progress["value"] = 0
        self.status_var.set(f"下载失败：{error} -> {os.path.abspath(save_dir)}")

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

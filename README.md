# 🖼️ Image Crawler Pro

![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)![GUI](https://img.shields.io/badge/GUI-Tkinter-brightgreen.svg)![OpenCV](https://img.shields.io/badge/optional-OpenCV-orange.svg)![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

在写博客时有时会涉及到设置文章封面，而我因为懒觉得每次都要打开网页搜索图片，一方面不能保证图片的质量，另一方面花费成本高(单从搜索、选择、下载)，所以利用**Agent**开发了一款桌面端图片下载助手。

**Image Crawler Pro** 是一款桌面端图片搜索、筛选与下载工具。它支持多图源聚合搜索、缩略图回显、图片有效性校验、关键词相关性排序，以及可选的 OpenCV 视觉匹配能力，适合快速收集壁纸、素材和关键词相关图片。

作者：debu8ger([incldue](https://github.com/incldue))



## 🎯 为什么需要它？

日常写博客时考虑到前端的美观需要文章封面，而又碍于去网页端步骤太麻烦，于是写了这么一个小工具。它将搜索、校验、筛选、下载整合到一个轻量桌面应用中：

- **多源聚合**：同时从多个图片站点拉取候选结果。
- **预览筛选**：先看缩略图，再批量选择需要下载的图片。
- **有效性校验**：自动跳过无法打开、尺寸过小或非图片响应的结果。
- **视觉排序**：结合关键词、图片质量、颜色/人像特征进行排序。



## ✅ 特性

- **多图源支持**
  - `WallpapersCraft`
  - `百度图片`
  - `haowallpaper`
  - `Wallhaven`
- **缩略图桌面 UI**
  - 支持滚动预览、自动换列、自适应窗口边缘。
  - 支持全选、清空选择、加载更多、下载所选。
  - 状态栏实时显示搜索、校验、下载进度。
- **下载策略更稳**
  - 优先下载高清图或原图。
  - 原图失败时自动回退到预览图/缩略图。
  - 文件名自动清理非法字符，避免 Windows 保存失败。
- **OpenCV 视觉增强**
  - 颜色关键词加权(虽然感觉没啥用)。
  - 人像、头像、`face`、`person` 等关键词会做人脸检测加权。
  - 输入本地图片路径时，会使用 ORB 特征做相似图片匹配。
- **AI 图片生成**
  - UI 中可输入提示词生成下载。
  - 默认兼容 OpenAI 风格的 `/images/generations` 接口。
  - 支持接口返回 `url` 或 `b64_json` 图片数据。
- **代理策略**
  - 因为俩站点图片质量高，`Wallhaven` 和 `WallpapersCraft` 强制走 `http://127.0.0.1:7890`。(也就是说在下载图片时得保持代理打开)
  - 其他图源默认直连。



## ⚠️ 当前存在的问题

- **图源结构可能变化**：图片站点 HTML 或接口调整后，可能需要同步更新解析逻辑。
- **部分站点存在风控**：百度、壁纸站等可能限制自动请求，失败时程序会跳过对应图源。
- **OpenCV 是可选增强**：未安装 OpenCV 时，程序仍可运行，但只进行基础图片校验。
- **部分站点仅支持英文输入**：由于这俩站点为国外质量较高的图片网站，`wallhaven`和`wallpaperscraft`仅支持英文输入关键词。



## 🚀 快速部署

### 1. 安装依赖

```bash
python -m pip install -r requirements.txt
```

如果不需要 OpenCV 视觉增强，可以只安装基础依赖：

```bash
python -m pip install requests Pillow
```

### 2. 启动程序

```bash
python main.py
```

Windows 下也可以直接双击：

```text
run.bat
```

### 3. 代理准备

如果需要使用 `Wallhaven` 或 `WallpapersCraft`，请确保本机代理打开且可用 (端口`7890`可自行在/image_crawler/config.py 更改)。

```text
http://127.0.0.1:7890
```

### 4. AI 图片生成配置

在 `image_crawler/config.py` 中填写你的供应商信息：

```python
AI_IMAGE_API_KEY = "你的 API Key"
AI_IMAGE_BASE_URL = "https://api.openai.com/v1"
```

如供应商需要不同模型或路径，可同时调整：

```python
AI_IMAGE_MODEL = "gpt-image-1"
AI_IMAGE_ENDPOINT = "/images/generations"
```

配置完成后，在 UI 的 `AI 提示词` 输入框输入描述，点击 `AI生成并下载`。选择具体分辨率时：

- 程序会先把 UI 分辨率作为接口 `size` 参数提交给供应商。
- 如果供应商不支持该尺寸，会退回 `AI_IMAGE_DEFAULT_SIZE` 请求。
- 保存前会强制居中裁剪并缩放到 UI 选中的目标尺寸。

如果你希望供应商不支持高分辨率时直接报错，而不是退回默认尺寸后本地缩放，可设置：

```python
AI_IMAGE_ALLOW_SIZE_FALLBACK = False
```



## 📁 项目清单

```text
image_crawler/
├── image_crawler/
│   ├── __init__.py
│   ├── config.py
│   ├── crawlers.py
│   ├── downloader.py
│   ├── image_matcher.py
│   └── ui.py
├── downloads/
│   └── .gitkeep
├── main.py
├── requirements.txt
├── run.bat
├── pyrightconfig.json
├── .gitignore
└── README.md
```

- `image_crawler/config.py`：全局配置项，例如下载目录、线程数、代理。
- `image_crawler/crawlers.py`：各图片源搜索逻辑。
- `image_crawler/downloader.py`：图片下载、扩展名判断、文件保存。
- `image_crawler/image_matcher.py`：图片有效性校验、排序、OpenCV 匹配。
- `image_crawler/ui.py`：桌面 UI。
- `main.py`：项目入口。
- `requirements.txt`：依赖。
- `run.bat`：Windows 一键启动脚本。



## 🤝 贡献与反馈

如果你在使用过程中发现某个图源失效、缩略图无法显示、下载失败或排序不准确，欢迎提交 Issue 或自行修改对应逻辑。



## 📜 许可说明

本项目仅供技术学习与个人使用。请遵守目标网站的使用条款、图片版权要求和本地法律法规，不建议用于大规模商业采集。

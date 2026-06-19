# -*- coding: utf-8 -*-

def main():
    try:
        import tkinter as tk
        from image_crawler.ui import ImageCrawlerUI
    except ModuleNotFoundError as exc:
        missing = exc.name or "dependency"
        print(f"缺少依赖：{missing}")
        print("请先运行：python -m pip install -r requirements.txt")
        print("Windows 双击启动可先运行：run.bat --install")
        raise

    root = tk.Tk()
    root.withdraw()
    ImageCrawlerUI(root)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()

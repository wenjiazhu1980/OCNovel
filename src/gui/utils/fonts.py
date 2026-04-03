"""跨平台字体名称常量"""
import sys

if sys.platform == "darwin":
    FONT_UI = "PingFang SC"
    FONT_MONO = "Menlo"
elif sys.platform == "win32":
    FONT_UI = "Microsoft YaHei"
    FONT_MONO = "Consolas"
else:
    FONT_UI = "Noto Sans CJK SC"
    FONT_MONO = "DejaVu Sans Mono"

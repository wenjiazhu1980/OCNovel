# OCNovel 构建指南

## 前置依赖

- Python 3.9+
- 安装项目依赖：`pip install -r requirements.txt`
- PyInstaller 已包含在 requirements.txt 中

> **重要**：PyInstaller 不支持交叉编译。macOS 构建须在 macOS 上执行，Windows 构建须在 Windows 上执行。

---

## macOS 构建

```bash
pyinstaller ocnovel.spec
```

产物位于 `dist/OCNovel.app`。

---

## Windows 构建

```bash
pyinstaller ocnovel_win.spec
```

产物位于 `dist/OCNovel/OCNovel.exe`。

可将整个 `dist/OCNovel/` 目录打包为 zip 分发，或使用 Inno Setup / NSIS 制作安装包。

---

## 图标管理

项目包含两种格式的图标：

| 文件 | 用途 |
|------|------|
| `assets/ocnovel.icns` | macOS .app 图标 |
| `assets/ocnovel.ico` | Windows .exe 图标 |

如需从 `.icns` 重新生成 `.ico`：

```bash
# 1. 提取 PNG（需 macOS sips）
sips -s format png assets/ocnovel.icns --out /tmp/ocnovel_256.png --resampleWidth 256

# 2. 转换为 ICO（需 Pillow）
pip install Pillow
python -c "
from PIL import Image
img = Image.open('/tmp/ocnovel_256.png')
img.save('assets/ocnovel.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
"
```

---

## 注意事项

- 初版构建排除了 FlagEmbedding / PyTorch 等大体积依赖，Reranker 功能在打包版本中不可用
- 首次启动时，应用会在用户主目录创建 `~/OCNovel/` 并从模板初始化 `config.json` 和 `.env`
- API 密钥等敏感配置需用户手动编辑 `~/OCNovel/.env`

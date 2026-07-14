# P1：vision 可选大图压缩

## 目标

在 `scripts/vision.py` 中增加**可选**图片压缩：有 Pillow 时对过大图片缩略后上传；无 Pillow 时保持现有原图 base64 行为不变。

## 来源证据

- looksee-mcp `src/looksee_mcp/server.py` `_compress`（约 L84–102）：
  - `len(raw) <= 50 * 1024` 不压
  - 有 PIL：`thumbnail((768, 768))` + JPEG quality=65
  - 无 PIL：原样返回
- 同文件 `_from_file` / `vision` 在编码前调用 `_compress`

## 具体步骤

### 1. 在 vision.py 增加压缩辅助函数

文件：`scripts/vision.py`

在 `encode_image` **之前或之后**增加（重写，勿整段粘贴）：

```python
# 默认阈值与上限（可通过环境变量覆盖，便于调试）
_COMPRESS_MIN_BYTES = int(os.environ.get("HELLOMEDIA_COMPRESS_MIN_BYTES", str(50 * 1024)))
_COMPRESS_MAX_SIDE = int(os.environ.get("HELLOMEDIA_COMPRESS_MAX_SIDE", "1536"))
_COMPRESS_JPEG_QUALITY = int(os.environ.get("HELLOMEDIA_COMPRESS_JPEG_QUALITY", "75"))


def _mime_for_ext(path):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "bmp": "image/bmp", "tiff": "image/tiff",
        "webp": "image/webp", "gif": "image/gif",
    }.get(ext, "image/png")


def load_image_payload(path, *, compress=True):
    """Return (base64_str, mime). Optionally compress large images if Pillow is available.

    compress=False or missing Pillow → original bytes (current behavior).
    """
    with open(path, "rb") as f:
        raw = f.read()
    mime = _mime_for_ext(path)
    if not compress or len(raw) <= _COMPRESS_MIN_BYTES:
        return base64.b64encode(raw).decode(), mime
    try:
        from io import BytesIO
        from PIL import Image  # optional
    except ImportError:
        return base64.b64encode(raw).decode(), mime

    try:
        im = Image.open(path)
        # Keep animated gif first frame only when compressing
        if getattr(im, "is_animated", False):
            im.seek(0)
        im = im.convert("RGB")
        im.thumbnail((_COMPRESS_MAX_SIDE, _COMPRESS_MAX_SIDE), Image.Resampling.LANCZOS
                     if hasattr(Image, "Resampling") else Image.LANCZOS)
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=_COMPRESS_JPEG_QUALITY, optimize=True)
        compressed = buf.getvalue()
        # Only use compressed if it actually shrinks payload
        if len(compressed) < len(raw):
            print(
                f"[vision] compressed {os.path.basename(path)}: "
                f"{len(raw)} -> {len(compressed)} bytes",
                file=sys.stderr,
            )
            return base64.b64encode(compressed).decode(), "image/jpeg"
    except Exception as exc:
        print(f"[vision] compress skipped for {path}: {exc}", file=sys.stderr)
    return base64.b64encode(raw).decode(), mime
```

说明相对 looksee 的调整（有意为之）：

- 默认 max side **1536**（而非 768），降低 OCR/UI 截图糊掉风险
- JPEG quality **75**（而非 65）
- 仅当压缩后更小时才替换
- 可用环境变量调参

### 2. 改造 encode 调用点

文件：`scripts/vision.py`

1. 保留 `encode_image` 作薄封装或删除重复逻辑，统一走 `load_image_payload`。
2. 修改 `_try_openai` 与 `_try_anthropic`：不要手写 mime + encode_image，改为：

```python
b64, mime = load_image_payload(img_path, compress=True)
# openai:
content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}})
# anthropic:
content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
```

### 3. CLI 开关

文件：`scripts/vision.py` `main()` argparse 增加：

```python
parser.add_argument(
    "--no-compress",
    action="store_true",
    help="Disable optional image compression even if Pillow is installed",
)
```

将 `compress=not args.no_compress` 传入 `load_image_payload`（若函数在 try_channel 内调用，可把 flag 经 `try_channel` / `_try_*` 参数下传，或用模块级/闭包；推荐显式参数 `compress: bool` 传到 `_try_openai` / `_try_anthropic` / `try_channel`）。

### 4. 不修改 config.json schema

本任务不强制新配置字段；环境变量 + CLI 足够。可选：在 `defaults` 文档中于 P4 说明。

## 安装依赖（可选）

```bash
# 可选，非必须
pip install Pillow
```

## 验证命令

在仓库根目录 `D:\GitHub\dev\skills\hellomedia`：

```bash
# 1) 语法与导入（无 PIL 也应成功）
python -c "import ast; ast.parse(open('scripts/vision.py',encoding='utf-8').read()); print('syntax_ok')"

# 2) 无图时错误行为不变
python scripts/vision.py --prompt "x" 2>&1 | findstr /i "No images"

# 3) 单元式测压缩函数：准备一张 >50KB 的 png（或用现有截图）
python -c "
from scripts.vision import load_image_payload, _COMPRESS_MIN_BYTES
import os, sys
# 找一张测试图：用户可改路径
p = os.environ.get('TEST_IMG', '')
if not p or not os.path.exists(p):
    print('SKIP_no_test_img')
    sys.exit(0)
b64, mime = load_image_payload(p, compress=True)
print('mime', mime, 'b64_len', len(b64), 'min_bytes', _COMPRESS_MIN_BYTES)
print('compress_path_ok')
"
```

若本机有 API，可再跑真实请求（非必须）：

```bash
python scripts/vision.py --image ./path/to/large.png --prompt "用一句话描述" --no-compress
python scripts/vision.py --image ./path/to/large.png --prompt "用一句话描述"
```

## 完成标准

- [ ] `load_image_payload` 存在；无 Pillow 时返回原图 base64 + 原 mime
- [ ] 有 Pillow 且文件 > 阈值时尝试压缩；失败则回退原图
- [ ] `--no-compress` 强制原图
- [ ] OpenAI 与 Anthropic 两条路径都使用同一 payload 加载函数
- [ ] 未新增硬依赖到 README「必须安装」列表
- [ ] 现有「无图 / 缺文件」JSON 错误行为保持

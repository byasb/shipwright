"""Screenshot compositor. Real device captures onto branded backdrops with caption text.

Rule from the error index: NEVER let an image model redraw the UI (it hallucinates numbers/text).
The backdrop is a gradient (or, behind GEN_BACKDROPS=true, a text-free image from Gemini image
models); the capture is pasted pixel-exact, scaled, inside a rounded "device" mask.

Sizes: API slot APP_IPHONE_67 takes 1320×2868. Web uploader wants 1284×2778 — we render both.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont

API_SIZE = (1320, 2868)   # APP_IPHONE_67 via API
WEB_SIZE = (1284, 2778)   # ASC web uploader "6.5-inch" slot
FONT_CANDIDATES = [
    "/System/Library/Fonts/SFCompactDisplay.ttf", "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


@dataclass
class Panel:
    screen: str
    headline: str
    sub: str


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def gradient(size: tuple[int, int], top: str, bottom: str) -> Image.Image:
    w, h = size
    t, b = _hex(top), _hex(bottom)
    img = Image.new("RGB", (1, h))
    px = img.load()
    for y in range(h):
        f = y / max(h - 1, 1)
        px[0, y] = tuple(int(t[i] + (b[i] - t[i]) * f) for i in range(3))
    return img.resize(size)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return m


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def compose(capture: Image.Image, panel: Panel, colors: dict, size: tuple[int, int] = API_SIZE,
            backdrop: Image.Image | None = None) -> Image.Image:
    w, h = size
    canvas = (backdrop.convert("RGB").resize(size) if backdrop else gradient(size, colors.get("bg_top", "#5856D6"), colors.get("bg_bottom", "#8E5CF6")))
    draw = ImageDraw.Draw(canvas)
    text_color = _hex(colors.get("text", "#FFFFFF"))

    # caption block: headline + sub, top 17% of the canvas
    hf, sf = _font(int(w * 0.072)), _font(int(w * 0.040))
    y = int(h * 0.055)
    for line in _wrap(draw, panel.headline, hf, int(w * 0.86)):
        tw = draw.textlength(line, font=hf)
        draw.text(((w - tw) / 2, y), line, font=hf, fill=text_color)
        y += int(hf.size * 1.15)
    y += int(h * 0.008)
    for line in _wrap(draw, panel.sub, sf, int(w * 0.86)):
        tw = draw.textlength(line, font=sf)
        draw.text(((w - tw) / 2, y), line, font=sf, fill=text_color + (235,) if canvas.mode == "RGBA" else text_color)
        y += int(sf.size * 1.3)

    # device: real capture scaled to ~82% width, rounded corners, soft shadow, bottom-bleeding
    dev_w = int(w * 0.82)
    dev_h = int(capture.height * dev_w / capture.width)
    shot = capture.convert("RGB").resize((dev_w, dev_h), Image.LANCZOS)
    radius = int(dev_w * 0.10)
    top = max(y + int(h * 0.03), int(h * 0.20))
    x0 = (w - dev_w) // 2
    shadow = Image.new("RGBA", (dev_w + 120, dev_h + 120), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((60, 60, 60 + dev_w, 60 + dev_h), radius=radius, fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    canvas.paste(shadow, (x0 - 60, top - 60 + 24), shadow)
    canvas.paste(shot, (x0, top), _rounded_mask((dev_w, dev_h), radius))
    return canvas


def to_web_size(img: Image.Image) -> Image.Image:
    """Scale-to-fill + centre-crop 1320×2868 → 1284×2778 (aspect differs 0.4%, crop invisible)."""
    tw, th = WEB_SIZE
    scale = max(tw / img.width, th / img.height)
    r = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    l, t = (r.width - tw) // 2, (r.height - th) // 2
    return r.crop((l, t, l + tw, t + th))


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def gen_backdrop(prompt: str, size: tuple[int, int] = API_SIZE) -> Image.Image | None:
    """Optional: text-free branded backdrop from a Gemini image model. Returns None on any failure so
    the gradient fallback keeps the pipeline unattended."""
    try:
        from google.genai import Client, types

        client = Client(api_key=os.environ.get("GEMINI_API_KEY") or __import__("shipwright.config", fromlist=["secret"]).secret("gemini-api-key"))
        r = client.models.generate_content(
            model=os.environ.get("IMAGE_MODEL", "gemini-3.1-flash-image"),
            contents=f"Abstract, text-free, portrait 9:19.5 app-store backdrop. {prompt}. No letters, no UI, no devices.",
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        for part in r.candidates[0].content.parts:
            if getattr(part, "inline_data", None) and part.inline_data.data:
                return Image.open(io.BytesIO(part.inline_data.data)).convert("RGB").resize(size)
    except Exception:  # noqa: BLE001
        return None
    return None

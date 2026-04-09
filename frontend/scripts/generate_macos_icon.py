from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "src-tauri" / "icons"
SOURCE_PATH = ICONS_DIR / "icon-source.png"
OUTPUT_PATH = ICONS_DIR / "icon.png"
SIZE = 1024


def build_squircle_mask(size: int, radius_ratio: float = 0.19) -> Image.Image:
    radius = int(size * radius_ratio)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=1.4))


def build_background(size: int) -> Image.Image:
    base = Image.new("RGBA", (size, size), (4, 7, 24, 255))
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for i in range(11):
        inset = int(size * 0.035 * i)
        alpha = max(0, 85 - i * 7)
        color = (17, 22, 58, alpha)
        draw.rounded_rectangle(
            (inset, inset, size - inset - 1, size - inset - 1),
            radius=int(size * 0.19),
            outline=color,
            width=max(1, int(size * 0.006)),
        )

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        (int(size * 0.18), int(size * 0.12), int(size * 0.82), int(size * 0.78)),
        fill=(28, 130, 172, 72),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=size * 0.08))

    rim = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rim_draw = ImageDraw.Draw(rim)
    rim_draw.rounded_rectangle(
        (int(size * 0.02), int(size * 0.02), int(size * 0.98), int(size * 0.98)),
        radius=int(size * 0.19),
        outline=(255, 255, 255, 22),
        width=int(size * 0.008),
    )

    base = Image.alpha_composite(base, glow)
    base = Image.alpha_composite(base, overlay)
    base = Image.alpha_composite(base, rim)
    return base


def extract_boat_art(source: Image.Image) -> Image.Image:
    rgb = source.convert("RGB")
    alpha = source.getchannel("A")
    background = Image.new("RGB", source.size, (4, 7, 24))
    diff = ImageChops.difference(rgb, background).convert("L")
    threshold = diff.point(lambda px: 255 if px > 26 else 0)
    soft = threshold.filter(ImageFilter.GaussianBlur(radius=5))
    boat_alpha = ImageChops.screen(alpha, soft)
    boat = source.copy()
    boat.putalpha(boat_alpha)
    return boat


def compose_icon() -> None:
    source = Image.open(SOURCE_PATH).convert("RGBA")
    background = build_background(SIZE)
    squircle_mask = build_squircle_mask(SIZE)
    background.putalpha(squircle_mask)

    boat = extract_boat_art(source)
    target_width = int(SIZE * 0.68)
    target_height = int(target_width * (boat.height / boat.width))
    boat = boat.resize((target_width, target_height), Image.Resampling.LANCZOS)

    boat_glow = boat.filter(ImageFilter.GaussianBlur(radius=18))
    glow_canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    glow_pos = ((SIZE - boat_glow.width) // 2, int(SIZE * 0.3) - boat_glow.height // 2)
    glow_canvas.alpha_composite(boat_glow, glow_pos)
    glow_canvas = glow_canvas.filter(ImageFilter.GaussianBlur(radius=20))

    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.alpha_composite(background)
    icon.alpha_composite(glow_canvas)

    boat_canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    boat_pos = ((SIZE - boat.width) // 2, int(SIZE * 0.52) - boat.height // 2)
    boat_canvas.alpha_composite(boat, boat_pos)
    icon.alpha_composite(boat_canvas)

    icon.save(OUTPUT_PATH)


if __name__ == "__main__":
    compose_icon()

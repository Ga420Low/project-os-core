from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


CANVAS = 1024


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    build_dir = root / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGBA", (CANVAS, CANVAS), (4, 9, 15, 255))
    draw = ImageDraw.Draw(image)

    _paint_background(image)
    _paint_glow(image)
    _paint_frame(draw)
    _paint_tiles(draw)
    _paint_core(image)
    _paint_prompt(draw)

    png_path = build_dir / "icon.png"
    ico_path = build_dir / "icon.ico"
    image.save(png_path)
    image.save(
        ico_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)],
    )


def _paint_background(image: Image.Image) -> None:
    px = image.load()
    center_x = CANVAS / 2
    center_y = CANVAS / 2
    max_distance = (center_x**2 + center_y**2) ** 0.5
    for y in range(CANVAS):
        for x in range(CANVAS):
            dx = x - center_x
            dy = y - center_y
            distance = (dx * dx + dy * dy) ** 0.5 / max_distance
            mix = max(0.0, min(1.0, 1.0 - distance))
            r = int(5 + 10 * mix)
            g = int(10 + 26 * mix)
            b = int(18 + 46 * mix)
            px[x, y] = (r, g, b, 255)


def _paint_glow(image: Image.Image) -> None:
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    cyan = (88, 203, 255, 170)
    blue = (53, 120, 190, 150)
    draw.ellipse((210, 200, 820, 820), fill=blue)
    draw.ellipse((280, 260, 770, 770), fill=cyan)
    glow = glow.filter(ImageFilter.GaussianBlur(70))
    image.alpha_composite(glow)


def _paint_frame(draw: ImageDraw.ImageDraw) -> None:
    outer = (86, 86, CANVAS - 86, CANVAS - 86)
    draw.rounded_rectangle(outer, radius=140, fill=(8, 16, 25, 238), outline=(83, 167, 214, 110), width=8)
    inner = (118, 118, CANVAS - 118, CANVAS - 118)
    draw.rounded_rectangle(inner, radius=114, outline=(146, 221, 255, 40), width=2)


def _paint_tiles(draw: ImageDraw.ImageDraw) -> None:
    tiles = [
        (170, 170, 280, 280),
        (298, 170, 408, 280),
    ]
    colors = [
        ((106, 207, 255, 230), (13, 77, 122, 255)),
        ((170, 214, 245, 200), (19, 47, 76, 255)),
    ]
    for rect, colors_pair in zip(tiles, colors, strict=True):
        fill, outline = colors_pair
        draw.rounded_rectangle(rect, radius=28, fill=fill, outline=outline, width=3)


def _paint_core(image: Image.Image) -> None:
    core = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(core)

    diamond = [(514, 246), (786, 518), (514, 790), (242, 518)]
    draw.polygon(diamond, fill=(18, 40, 62, 255), outline=(89, 199, 255, 255))
    draw.line(diamond + [diamond[0]], fill=(89, 199, 255, 255), width=18, joint="curve")

    inner = [(514, 322), (710, 518), (514, 714), (318, 518)]
    draw.polygon(inner, fill=(10, 23, 35, 255), outline=(188, 235, 255, 120))
    draw.line(inner + [inner[0]], fill=(173, 227, 255, 100), width=8, joint="curve")

    beam = [(514, 392), (608, 486), (514, 580), (420, 486)]
    draw.polygon(beam, fill=(103, 213, 255, 225))

    glow = core.filter(ImageFilter.GaussianBlur(18))
    image.alpha_composite(glow)
    image.alpha_composite(core)


def _paint_prompt(draw: ImageDraw.ImageDraw) -> None:
    draw.rounded_rectangle((604, 668, 768, 716), radius=20, fill=(232, 247, 255, 245))
    draw.rounded_rectangle((640, 740, 766, 770), radius=14, fill=(89, 199, 255, 255))


if __name__ == "__main__":
    main()

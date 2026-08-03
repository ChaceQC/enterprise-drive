from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "apps" / "drive-desktop" / "src-tauri" / "icons"


def render(size: int) -> Image.Image:
    scale = size / 256
    image = Image.new("RGBA", (size, size), (22, 60, 47, 255))
    draw = ImageDraw.Draw(image)
    cloud = [
        (52, 150, 204, 190),
        (37, 112, 219, 183),
        (65, 78, 142, 166),
        (113, 61, 186, 155),
    ]
    for left, top, right, bottom in cloud:
        draw.ellipse(
            tuple(round(value * scale) for value in (left, top, right, bottom)),
            fill=(235, 248, 239, 255),
        )
    draw.rounded_rectangle(
        tuple(round(value * scale) for value in (45, 130, 211, 194)),
        radius=round(24 * scale),
        fill=(235, 248, 239, 255),
    )
    draw.rounded_rectangle(
        tuple(round(value * scale) for value in (83, 145, 173, 158)),
        radius=round(7 * scale),
        fill=(32, 126, 91, 255),
    )
    return image


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    render(32).save(ICON_DIR / "32x32.png")
    render(128).save(ICON_DIR / "128x128.png")
    render(256).save(ICON_DIR / "128x128@2x.png")
    render(256).save(
        ICON_DIR / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()

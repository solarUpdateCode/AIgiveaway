"""Programmatic icon generator for AIgiveaway (tray icon + Windows .ico)."""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw


def create_app_icon_image(size: int = 256) -> Image.Image:
    """Create a sleek dark-slate + electric-cyan lightning/gift badge icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = int(size * 0.06)
    radius = int(size * 0.22)

    # Rounded dark navy background
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius,
        fill=(15, 23, 42, 255),
        outline=(56, 189, 248, 255),
        width=max(2, size // 32),
    )

    # Inner glowing cyan lightning bolt
    s = size
    bolt = [
        (int(s * 0.56), int(s * 0.16)),
        (int(s * 0.28), int(s * 0.54)),
        (int(s * 0.48), int(s * 0.54)),
        (int(s * 0.40), int(s * 0.84)),
        (int(s * 0.72), int(s * 0.44)),
        (int(s * 0.52), int(s * 0.44)),
    ]
    draw.polygon(bolt, fill=(56, 189, 248, 255))

    # Small green "live/on" indicator dot at top-right
    dot_r = int(size * 0.085)
    cx, cy = int(size * 0.78), int(size * 0.22)
    draw.ellipse(
        [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
        fill=(34, 197, 94, 255),
        outline=(15, 23, 42, 255),
        width=max(2, size // 64),
    )
    return img


def generate_ico(output_path: str | Path) -> Path:
    """Generate a multi-resolution Windows .ico file."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    base = create_app_icon_image(256)
    base.save(
        out,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    return out


if __name__ == "__main__":
    generate_ico("assets/app.ico")
    print("Generated assets/app.ico")

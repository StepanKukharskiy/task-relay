"""Apply a transparent rounded-square mask to the existing Task Relay icon.

From `desktop/`, run this script, then `npx tauri icon
src-tauri/icons/icon-master.png` when regenerating platform icon files. Requires
Pillow only for icon regeneration, not app builds.
"""

from pathlib import Path

from PIL import Image, ImageDraw


ICONS = Path(__file__).resolve().parents[1] / "src-tauri" / "icons"
SOURCE = ICONS / "icon-base.png"
OUTPUT = ICONS / "icon-master.png"
CORNER_RADIUS = 0.22
ANTIALIAS = 4


def main() -> None:
    icon = Image.open(SOURCE).convert("RGBA")
    if icon.width != icon.height:
        raise ValueError("The icon source must be square")

    edge = icon.width * ANTIALIAS
    mask = Image.new("L", (edge, edge), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, edge - 1, edge - 1),
        radius=round(edge * CORNER_RADIUS),
        fill=255,
    )
    icon.putalpha(mask.resize(icon.size, Image.Resampling.LANCZOS))
    icon.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()

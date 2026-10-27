"""Turn official artwork into the brand images Home Assistant expects.

Usage (from the repository root, with Pillow installed):

    python scripts/make_brand.py --icon pad/naar/app-icoon.png --logo pad/naar/logo.png \
        [--dark-logo pad/naar/logo-wit.png]

Writes custom_components/appie/brand/: icon.png (256x256), icon@2x.png (512x512),
logo.png (128 px high), logo@2x.png (256 px high) and, if given, dark_logo*.png.
Transparent edges are trimmed, as the home-assistant/brands rules ask.
Home Assistant 2026.3+ shows these images; older versions ignore the folder.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

OUT = Path(__file__).parents[1] / "custom_components/appie/brand"


def _trim(image: Image.Image) -> Image.Image:
    box = image.getchannel("A").getbbox()
    return image.crop(box) if box else image


def _icon(src: Path) -> None:
    image = _trim(Image.open(src).convert("RGBA"))
    side = max(image.size)
    square = Image.new("RGBA", (side, side))
    square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        square.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)


def _logo(src: Path, prefix: str = "") -> None:
    image = _trim(Image.open(src).convert("RGBA"))
    for name, height in ((f"{prefix}logo.png", 128), (f"{prefix}logo@2x.png", 256)):
        width = round(image.width * height / image.height)
        image.resize((width, height), Image.LANCZOS).save(OUT / name, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--icon", type=Path, required=True, help="square icon, ideally 512x512 or larger")
    parser.add_argument("--logo", type=Path, required=True, help="logo for light backgrounds")
    parser.add_argument("--dark-logo", type=Path, help="logo for dark backgrounds")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    _icon(args.icon)
    _logo(args.logo)
    if args.dark_logo:
        _logo(args.dark_logo, "dark_")
    for path in sorted(OUT.glob("*.png")):
        print(path.relative_to(OUT.parents[2]), Image.open(path).size)


if __name__ == "__main__":
    main()

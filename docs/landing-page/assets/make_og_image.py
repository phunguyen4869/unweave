"""Regenerate og-image.png, the 1200x630 link-preview card for the landing page.

    python docs/landing-page/assets/make_og_image.py

Needs Pillow. Uses Segoe UI on Windows, else DejaVu Sans.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1200, 630
BACKGROUND = (15, 17, 21)       # --bg on the landing page
GLOW = (255, 138, 61)           # --accent
TEXT = (232, 234, 240)          # --text
MUTED = (154, 161, 178)         # --muted

TITLE = "Unweave"
SUBTITLE = "AI-powered audio stem separation, 100% local"
FOOTNOTE = "Free & open source  ·  Windows 10/11"

FONTS = {
    "bold": [r"C:\Windows\Fonts\segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "regular": [r"C:\Windows\Fonts\segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS[weight]:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise SystemExit(f"No {weight} font found; install Segoe UI or DejaVu Sans.")


def centered(draw: ImageDraw.ImageDraw, y: int, text: str, face, fill) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=face)
    draw.text(((WIDTH - (right - left)) / 2 - left, y - top), text, font=face, fill=fill)


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)

    # A soft warm glow behind the icon, fading into the background.
    glow = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    ImageDraw.Draw(glow).ellipse((WIDTH / 2 - 520, -380, WIDTH / 2 + 520, 420), fill=(48, 30, 22))
    image = Image.blend(image, glow.filter(ImageFilter.GaussianBlur(140)), 1.0)

    icon = Image.open(HERE / "icon-256.png").convert("RGBA").resize((150, 150), Image.LANCZOS)
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((WIDTH / 2 - 70, 82, WIDTH / 2 + 70, 230), 36, fill=(*GLOW, 70))
    image.paste(shadow.filter(ImageFilter.GaussianBlur(24)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(24)))
    image.paste(icon, ((WIDTH - 150) // 2, 70), icon)

    draw = ImageDraw.Draw(image)
    centered(draw, 252, TITLE, font("bold", 76), TEXT)
    centered(draw, 340, SUBTITLE, font("regular", 30), MUTED)
    draw.rounded_rectangle((WIDTH / 2 - 45, 409, WIDTH / 2 + 45, 416), 4, fill=GLOW)
    centered(draw, 460, FOOTNOTE, font("regular", 22), MUTED)

    image.save(HERE / "og-image.png", optimize=True)
    print("wrote", HERE / "og-image.png")


if __name__ == "__main__":
    main()

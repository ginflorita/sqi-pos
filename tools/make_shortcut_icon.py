"""Build the Windows shortcut icon from the bundled SQI company logo."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'static' / 'sqi-logo.png'
OUTPUT = ROOT / 'static' / 'sqi-pos.ico'


def main():
    source = Image.open(SOURCE).convert('RGBA')
    # The lettering below the oval is too small to read in a desktop icon.
    logo = source.crop((0, 0, source.width, round(source.height * 0.62)))
    logo = logo.resize((228, 118), Image.Resampling.LANCZOS)

    icon = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle((4, 4, 251, 251), radius=44,
                           fill=(255, 255, 255, 255), outline=(16, 143, 72, 255), width=9)
    icon.alpha_composite(logo, ((256 - logo.width) // 2, (256 - logo.height) // 2))
    icon.save(OUTPUT, format='ICO', sizes=[(16, 16), (24, 24), (32, 32),
                                           (48, 48), (64, 64), (128, 128), (256, 256)])
    print(OUTPUT)


if __name__ == '__main__':
    main()

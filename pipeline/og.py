"""Make static/og.png (1200x630 link preview) and static/favicon.svg. Re-run after renaming the site.

  python pipeline/og.py
Needs Pillow; fonts are Windows' Segoe UI (falls back to Pillow's default font elsewhere).
"""
import io, json, urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static"
NAME, TAG = "PROSTATS.GG", "Every pro League of Legends game of 2026"
SUB = "Match histories · builds · tier list · leaderboards · head-to-head"
GOLD, BG = (200, 170, 110), (14, 16, 21)
CHAMPS = ["Orianna", "JarvanIV", "Rumble", "Varus", "Nautilus", "Azir", "Ahri", "LeeSin"]

def font(name, size):
    try: return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
    except OSError: return ImageFont.load_default(size)

def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "RiftLedger/0.1"}), timeout=30).read()

def diamond(d, cx, cy, r, w):
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], outline=GOLD, width=w)
    r2 = r * 0.45
    d.polygon([(cx, cy - r2), (cx + r2, cy), (cx, cy + r2), (cx - r2, cy)], fill=GOLD)

def main():
    OUT.mkdir(exist_ok=True)
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), BG)
    ver = json.loads(get("https://ddragon.leagueoflegends.com/api/versions.json"))[0]
    # dimmed splash art behind, faded to the background colour at the edges
    splash = Image.open(io.BytesIO(get("https://ddragon.leagueoflegends.com/cdn/img/champion/splash/Orianna_0.jpg"))).convert("RGB")
    splash = splash.resize((W, int(splash.height * W / splash.width))).crop((0, 40, W, 40 + H)).filter(ImageFilter.GaussianBlur(2))
    img = Image.blend(img, splash, 0.28)
    shade = Image.new("L", (W, H))
    sd = ImageDraw.Draw(shade)
    for y in range(H): sd.line([(0, y), (W, y)], fill=int(255 * min(1, max(0, (y - 300) / 330))))
    img.paste(Image.new("RGB", (W, H), BG), mask=shade)
    d = ImageDraw.Draw(img)
    f1, f2, f3 = font("segoeuib.ttf", 92), font("seguisb.ttf", 38), font("seguisb.ttf", 26)
    tw = d.textlength(NAME, font=f1) + 0.16 * 92 * (len(NAME) - 1)
    x0 = (W - (tw + 110)) / 2
    diamond(d, x0 + 42, 215, 42, 7)
    x = x0 + 110
    for ch in NAME:  # letter-spaced wordmark like the site header
        d.text((x, 160), ch, font=f1, fill=GOLD); x += d.textlength(ch, font=f1) + 0.16 * 92
    for text, f, y, col in ((TAG, f2, 300, (232, 234, 238)), (SUB, f3, 362, (154, 161, 173))):
        d.text(((W - d.textlength(text, font=f)) / 2, y), text, font=f, fill=col)
    n, sz, gap = len(CHAMPS), 72, 14
    x = (W - (n * sz + (n - 1) * gap)) / 2
    for c in CHAMPS:
        icon = Image.open(io.BytesIO(get(f"https://ddragon.leagueoflegends.com/cdn/{ver}/img/champion/{c}.png"))).convert("RGB").resize((sz, sz))
        m = Image.new("L", (sz, sz)); ImageDraw.Draw(m).rounded_rectangle((0, 0, sz - 1, sz - 1), 14, fill=255)
        img.paste(icon, (int(x), 450), m); x += sz + gap
    img.save(OUT / "og.png", optimize=True)
    (OUT / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#0e1015"/>'
        '<path d="M32 8 56 32 32 56 8 32Z" fill="none" stroke="#c8aa6e" stroke-width="6" stroke-linejoin="round"/>'
        '<path d="M32 22 42 32 32 42 22 32Z" fill="#c8aa6e"/></svg>', encoding="utf-8")
    print("wrote", OUT / "og.png", OUT / "favicon.svg")

if __name__ == "__main__":
    main()

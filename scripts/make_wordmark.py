"""Strip the baked green box from logo-primary.png via GIMP-style color-to-alpha,
producing a transparent wordmark (white PITCH + yellow RANK) for the infographics.

Run once when the source logo changes:
    python scripts/make_wordmark.py
"""
from PIL import Image

SRC = "frontend/public/logos/logo-primary.png"
OUT = "frontend/public/logos/logo-wordmark.png"
KEY = (5, 46, 39)  # sampled box green


def chan_alpha(p: int, k: int) -> float:
    if p > k:
        return (p - k) / (255 - k) if k < 255 else 0.0
    if p < k:
        return (k - p) / k if k > 0 else 0.0
    return 0.0


def main() -> None:
    im = Image.open(SRC).convert("RGBA")
    px = im.load()
    w, h = im.size
    kr, kg, kb = KEY
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            alpha = max(chan_alpha(r, kr), chan_alpha(g, kg), chan_alpha(b, kb))
            alpha = max(0.0, min(1.0, alpha))
            if alpha < 1 / 255:
                px[x, y] = (0, 0, 0, 0)
                continue
            nr = int(max(0, min(255, (r - kr) / alpha + kr)))
            ng = int(max(0, min(255, (g - kg) / alpha + kg)))
            nb = int(max(0, min(255, (b - kb) / alpha + kb)))
            px[x, y] = (nr, ng, nb, int(alpha * a))
    im.save(OUT)
    print("wrote", OUT, im.size)


if __name__ == "__main__":
    main()

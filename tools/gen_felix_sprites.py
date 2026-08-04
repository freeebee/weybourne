"""Draw Felix's sprite frames onto a pixel grid and emit them as SVG.

Seven frames are needed and they must agree with each other to the pixel: a
walk cycle whose head jumps a row is worse than no walk cycle at all. Hand
-editing seven files of a few hundred <rect> runs each would guarantee that
drift, so the shared body is written once here and only the limbs vary.

The character matches the existing mascot-felix-hero pair — brown hair,
dark-rimmed glasses, cobalt overalls over a blue shirt, brass-buckled belt,
wrench in his right hand — on the same 36x44 grid with his feet on the same
row, so a frame swap never makes him hop.

    python tools/gen_felix_sprites.py

Writes web/public/mascot/mascot-felix-<state>.svg. Safe to re-run; it only
touches the seven generated files and leaves the original hero/strike pair
alone.
"""
from __future__ import annotations

from pathlib import Path

W, H = 36, 44
OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "mascot"

# Palette lifted from the existing sprites so the new frames sit beside them.
CL = {
    "K": "#26190E",   # outline
    "h": "#7A4A26", "H": "#9C6A38", "d": "#5B3418",      # hair
    "s": "#FBD6AC", "S": "#E8A87E",                       # skin, shadow
    "g": "#1A1D22", "w": "#FFFFFF", "b": "#4A2E18",       # glasses, brow
    "m": "#B93B31",                                        # mouth
    "t": "#4C7FC4", "T": "#3B6FD1",                        # shirt
    "o": "#2C55A8", "O": "#1F3F7E",                        # overalls, shade
    "L": "#8A5A32", "B": "#F2C14E",                        # belt, brass
    "e": "#6B3E22", "E": "#4A2A16",                        # boots
    "M": "#C9CFD6", "N": "#98A2AC",                        # wrench metal
}


class Grid:
    def __init__(self):
        self.px = [[None] * W for _ in range(H)]

    def set(self, x, y, c):
        if 0 <= x < W and 0 <= y < H and c:
            self.px[y][x] = c

    def rect(self, x, y, w, h, c):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, c)

    def row(self, y, spans):
        """spans: (x, width, colour) tuples on one row."""
        for x, w, c in spans:
            self.rect(x, y, w, 1, c)

    def outline(self):
        """One dark pixel around the silhouette — what makes it read as pixel
        art rather than a blob of rectangles."""
        edge = []
        for y in range(H):
            for x in range(W):
                if self.px[y][x] is not None:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and self.px[ny][nx] not in (None, "K"):
                        edge.append((x, y))
                        break
        for x, y in edge:
            self.px[y][x] = "K"

    def svg(self, name: str) -> str:
        out = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 44" '
            'width="240" height="240" role="img" aria-label="Felix" '
            'shape-rendering="crispEdges">',
            f"<title>{name}</title>",
        ]
        for y in range(H):
            x = 0
            while x < W:
                c = self.px[y][x]
                if c is None:
                    x += 1
                    continue
                run = 1
                while x + run < W and self.px[y][x + run] == c:
                    run += 1
                out.append(f'<rect x="{x}" y="{y}" width="{run}" height="1" '
                           f'fill="{CL[c]}"/>')
                x += run
        out.append("</svg>")
        return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# The parts
# --------------------------------------------------------------------------- #

def head(g: Grid, mouth: str = "flat"):
    """Head, hair and glasses. Identical in every frame: a head that shifts
    between frames is the thing the eye notices first."""
    # A fuller mop: the reference head is wide and the hair has volume above
    # the brow, not a flat cap sitting on it.
    g.row(2, [(13, 11, "d")])
    g.row(3, [(12, 13, "h"), (14, 6, "H")])
    g.row(4, [(11, 15, "h"), (13, 4, "H"), (21, 3, "H")])
    g.row(5, [(11, 15, "h"), (12, 3, "H"), (20, 3, "H")])
    g.row(6, [(11, 15, "h"), (16, 5, "H")])
    g.row(7, [(11, 15, "h")])
    # Forehead. Without these two rows the hair meets the rims and the whole
    # face reads as a bandit mask.
    g.row(8, [(11, 1, "h"), (12, 12, "s"), (24, 1, "h")])
    g.row(9, [(11, 1, "h"), (12, 12, "s"), (24, 1, "h")])
    # Spectacles: two rimmed lenses with a bridge, skin showing all round —
    # not a band across the face.
    g.row(10, [(12, 1, "h"), (13, 4, "g"), (17, 2, "s"), (19, 4, "g"), (23, 1, "h")])
    g.row(11, [(12, 1, "h"), (13, 1, "g"), (14, 2, "w"), (16, 1, "g"),
               (17, 2, "g"), (19, 1, "g"), (20, 2, "w"), (22, 1, "g"), (23, 1, "h")])
    g.row(12, [(12, 1, "h"), (13, 1, "g"), (14, 1, "w"), (15, 1, "g"), (16, 1, "g"),
               (17, 2, "s"), (19, 1, "g"), (20, 1, "g"), (21, 1, "w"), (22, 1, "g"),
               (23, 1, "h")])
    g.row(13, [(12, 1, "h"), (13, 4, "g"), (17, 2, "s"), (19, 4, "g"), (23, 1, "h")])
    g.row(14, [(11, 1, "h"), (12, 12, "s"), (24, 1, "h")])
    g.row(15, [(12, 12, "s"), (17, 2, "S")])          # nose
    if mouth == "open":
        g.row(16, [(12, 12, "s"), (16, 4, "K")])
        g.row(17, [(13, 10, "s"), (16, 4, "m")])
    elif mouth == "grin":
        g.row(16, [(12, 12, "s"), (16, 4, "m")])
        g.row(17, [(13, 10, "s")])
    else:
        g.row(16, [(12, 12, "s"), (16, 4, "b")])
        g.row(17, [(14, 8, "s")])


def torso(g: Grid):
    """Shirt, bib, straps, belt — the part that never moves."""
    g.row(18, [(15, 6, "S")])                                   # neck
    g.rect(11, 19, 14, 2, "t")                                  # shoulders
    g.rect(10, 21, 16, 2, "t")
    g.rect(13, 21, 2, 2, "o")                                   # straps
    g.rect(21, 21, 2, 2, "o")
    g.rect(11, 23, 14, 6, "o")                                  # bib
    g.rect(11, 23, 2, 6, "O")
    g.rect(23, 23, 2, 6, "O")
    g.row(29, [(10, 16, "L")])                                  # belt
    g.row(29, [(17, 2, "B")])                                   # buckle
    g.rect(11, 30, 14, 1, "o")


def legs(g: Grid, pose: str):
    """stand | walk_a | walk_b — the hips stay put, the feet move.

    The two walk frames swap which leg is planted and which is mid-stride, and
    the difference has to be several pixels: a one-pixel change reads as a
    rendering wobble rather than a stride."""
    if pose == "walk_a":
        # left leg striding forward, right leg trailing and lifted
        g.rect(10, 31, 6, 5, "o")
        g.rect(10, 35, 5, 5, "o")
        g.rect(10, 31, 1, 9, "O")
        g.rect(9, 40, 8, 3, "e")
        g.rect(9, 42, 8, 1, "E")
        g.rect(20, 31, 5, 5, "o")
        g.rect(21, 35, 5, 3, "o")
        g.rect(24, 31, 1, 7, "O")
        g.rect(21, 38, 7, 3, "e")
        g.rect(21, 40, 7, 1, "E")
    elif pose == "walk_b":
        g.rect(11, 31, 5, 5, "o")
        g.rect(9, 35, 5, 3, "o")
        g.rect(11, 31, 1, 6, "O")
        g.rect(8, 38, 7, 3, "e")
        g.rect(8, 40, 7, 1, "E")
        g.rect(20, 31, 6, 5, "o")
        g.rect(21, 35, 5, 5, "o")
        g.rect(25, 31, 1, 9, "O")
        g.rect(20, 40, 8, 3, "e")
        g.rect(20, 42, 8, 1, "E")
    else:                                       # stand
        g.rect(12, 31, 5, 9, "o")
        g.rect(12, 31, 1, 9, "O")
        g.rect(19, 31, 5, 9, "o")
        g.rect(23, 31, 1, 9, "O")
        g.rect(11, 40, 7, 3, "e")
        g.rect(11, 42, 7, 1, "E")
        g.rect(19, 40, 7, 3, "e")
        g.rect(19, 42, 7, 1, "E")


def wrench(g: Grid, x: int, y: int, up: bool = False, short: bool = False):
    """A spanner: shaft, then an open jaw at the far end."""
    shaft = 4 if short else 7
    if up:
        g.rect(x, y, 3, shaft, "M")
        g.rect(x + 2, y, 1, shaft, "N")
        g.rect(x - 1, y - 3, 5, 3, "M")
        g.rect(x + 1, y - 3, 1, 2, None)      # the gap in the jaw
        g.rect(x - 1, y - 1, 5, 1, "N")
    else:
        g.rect(x, y, 3, shaft, "M")
        g.rect(x + 2, y, 1, shaft, "N")
        g.rect(x - 1, y + shaft, 5, 3, "M")
        g.rect(x + 1, y + shaft + 1, 1, 2, None)
        g.rect(x - 1, y + shaft + 2, 5, 1, "N")


def arms(g: Grid, pose: str):
    """down | swing_a | swing_b | raised | struck | typing_a | typing_b.
    The left arm (viewer's right) is the free hand; the right hand holds the
    wrench, on the viewer's left, as in the reference."""
    if pose in ("down", "swing_a", "swing_b"):
        drop = {"down": 0, "swing_a": 1, "swing_b": -1}[pose]
        # Wrench arm. The spanner hangs at his thigh, not past his boots —
        # down by the feet it merged with them into one brown lump.
        g.rect(9, 21 + drop, 3, 6, "t")
        g.rect(9, 27 + drop, 3, 2, "B")             # glove
        wrench(g, 9, 29 + drop, short=True)
        # free arm
        g.rect(24, 21 - drop, 3, 6, "t")
        g.rect(24, 27 - drop, 3, 2, "B")
    elif pose == "raised":
        g.rect(9, 21, 3, 4, "t")
        g.rect(7, 15, 3, 7, "t")
        g.rect(7, 12, 3, 3, "B")
        wrench(g, 7, 4, up=True)
        g.rect(24, 22, 3, 6, "t")
        g.rect(24, 28, 3, 2, "B")
    elif pose == "struck":
        g.rect(9, 22, 3, 5, "t")
        g.rect(6, 24, 4, 4, "t")
        g.rect(4, 27, 3, 3, "B")
        wrench(g, 4, 30)
        g.rect(24, 22, 3, 6, "t")
        g.rect(24, 28, 3, 2, "B")
    elif pose in ("typing_a", "typing_b"):
        # Both forearms out in front, hands alternating a row: at this size a
        # seated figure reads as a shapeless block, but hands bobbing over an
        # unseen keyboard reads as typing immediately.
        lift = 0 if pose == "typing_a" else 1
        # Elbows out, hands brought in front of the belt and close together.
        # Held wide they read as a shrug.
        g.rect(9, 21, 3, 4, "t")
        g.rect(10, 25, 4, 2, "t")
        g.rect(13, 27 + lift, 3, 2, "B")
        g.rect(24, 21, 3, 4, "t")
        g.rect(22, 25, 4, 2, "t")
        g.rect(20, 28 - lift, 3, 2, "B")


FRAMES = {
    "idle":   dict(mouth="flat", arm="down",     leg="stand"),
    "walk-a": dict(mouth="flat", arm="swing_a",  leg="walk_a"),
    "walk-b": dict(mouth="flat", arm="swing_b",  leg="walk_b"),
    "fix-a":  dict(mouth="grin", arm="raised",   leg="stand"),
    "fix-b":  dict(mouth="open", arm="struck",   leg="stand"),
    "type-a": dict(mouth="flat", arm="typing_a", leg="stand"),
    "type-b": dict(mouth="flat", arm="typing_b", leg="stand"),
}


def build(spec: dict) -> Grid:
    g = Grid()
    # Arms first so the torso overlaps them at the shoulder seam.
    arms(g, spec["arm"])
    legs(g, spec["leg"])
    torso(g)
    head(g, spec["mouth"])
    g.outline()
    return g


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for state, spec in FRAMES.items():
        name = f"mascot-felix-{state}"
        (OUT / f"{name}.svg").write_text(build(spec).svg(name), encoding="utf-8")
        print("wrote", name + ".svg")


if __name__ == "__main__":
    main()

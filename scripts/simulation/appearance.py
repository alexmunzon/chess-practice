"""Fixed synthetic appearance only; no frame metadata, FEN or truth access.

Original simple vector silhouettes, rendered locally with Pillow. Shared templates
make this a deliberately modest simulation baseline, not physical-piece training.
"""
from PIL import Image, ImageDraw

PANEL_SIZE = 640
BOARD_ORIGIN = (64, 64)
TILE_SIZE = 64
LABELS = '.PNBRQKpnbrqk'
LIGHT_TILE = (231, 216, 184)
DARK_TILE = (103, 132, 101)
PANEL_COLOR = (184, 190, 193)
MARKERS = [
    {'name': 'tl', 'center': (32, 32), 'rgb': (240, 35, 35), 'radius': 12},
    {'name': 'tr', 'center': (608, 32), 'rgb': (35, 220, 75), 'radius': 12},
    {'name': 'br', 'center': (608, 608), 'rgb': (35, 90, 240), 'radius': 12},
    {'name': 'bl', 'center': (32, 608), 'rgb': (235, 35, 220), 'radius': 12},
]


def render_tile(label, dark=False, style='classic'):
    """Return a deterministic RGB 64×64 tile for one explicit piece label.

    ``unfamiliar`` is a separate slender-piece appearance challenge. It is not a
    supported recognizer template and must not be added using held-out results.
    """
    if label not in LABELS or len(label) != 1 or style not in ('classic', 'unfamiliar'):
        raise ValueError('Unsupported synthetic label or rendering style')
    image = Image.new('RGB', (64, 64), DARK_TILE if dark else LIGHT_TILE)
    if label == '.':
        return image
    piece = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(piece)
    fill = (248, 245, 231) if label.isupper() else (35, 38, 43)
    edge = (39, 42, 44) if label.isupper() else (239, 233, 210)
    def polygon(points):
        draw.polygon(points, fill=fill)
        draw.line(points + [points[0]], fill=edge, width=2, joint='curve')
    def ellipse(box):
        draw.ellipse(box, fill=fill, outline=edge, width=2)
    kind = label.upper()
    if kind == 'P':
        polygon([(28, 25), (36, 25), (38, 43), (44, 49), (20, 49), (26, 43)])
        ellipse((24, 12, 40, 28))
    elif kind == 'R':
        polygon([(22, 23), (42, 23), (40, 44), (45, 49), (19, 49), (24, 44)])
        polygon([(18, 12), (25, 12), (25, 19), (29, 19), (29, 12), (35, 12),
                 (35, 19), (39, 19), (39, 12), (46, 12), (45, 29), (19, 29)])
    elif kind == 'N':
        polygon([(21, 49), (22, 39), (29, 30), (20, 34), (15, 28), (24, 17),
                 (28, 8), (32, 17), (39, 15), (46, 24), (44, 38), (41, 49)])
        draw.ellipse((29, 21, 32, 24), fill=edge)
        draw.line([(17, 29), (23, 29)], fill=edge, width=2)
    elif kind == 'B':
        polygon([(28, 30), (36, 30), (38, 43), (44, 49), (20, 49), (26, 43)])
        ellipse((23, 10, 41, 34))
        draw.line([(32, 11), (27, 24)], fill=edge, width=3)
        ellipse((29, 8, 35, 14))
    elif kind == 'Q':
        polygon([(23, 32), (41, 32), (39, 43), (45, 49), (19, 49), (25, 43)])
        polygon([(18, 16), (25, 24), (28, 12), (33, 24), (39, 12), (40, 25),
                 (47, 16), (42, 35), (22, 35)])
        for x, y in ((18, 15), (28, 11), (39, 11), (47, 15)):
            ellipse((x-3, y-3, x+3, y+3))
    else:
        polygon([(25, 28), (39, 28), (38, 43), (45, 49), (19, 49), (26, 43)])
        ellipse((23, 22, 41, 36))
        polygon([(29, 8), (35, 8), (35, 12), (41, 12), (41, 18), (35, 18),
                 (35, 25), (29, 25), (29, 18), (23, 18), (23, 12), (29, 12)])
    draw.rounded_rectangle((18, 48, 46, 51), radius=2, fill=fill, outline=edge, width=2)
    draw.rounded_rectangle((16, 52, 48, 55), radius=2, fill=fill, outline=edge, width=2)
    if style == 'unfamiliar':
        slender = piece.resize((34, 64), Image.Resampling.BICUBIC)
        piece = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        piece.alpha_composite(slender, (15, 0))
    image.paste(piece, (0, 0), piece)
    return image

"""スロット画像をグリッドに並べて1枚の RGBA 画像へ合成する。

通常表示と位置調整モードで共通のグリッド計算（GridMetrics）を使い、
調整モードではクリック座標からセルを逆算できるようにしている。
"""

from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageDraw

# 背景を敷くときの余白と色
PADDING = 4      # background: dark のときにグリッドの外側へ付く余白
_BG_COLOR = (0, 0, 0, 140)

# 位置調整モード
FRAME = 16                          # 外周の掴みしろ（ここをドラッグして全体を移動）
_FRAME_BG = (26, 26, 30, 220)
_FRAME_LINE = (255, 170, 0, 255)
_GRID_BG = (0, 0, 0, 120)
_CELL_LINE = (255, 255, 255, 70)
_HOVER_BG = (255, 170, 0, 70)
_HELD_LINE = (255, 170, 0, 255)
_DISABLED_ALPHA = 165               # OFF のスキルを薄く見せる（薄すぎると背景に埋もれる）
_DISABLED_BG = (18, 18, 22, 235)    # OFF のマスは下地を敷いてゲーム画面を透かさない


@dataclass
class GridMetrics:
    """セル座標とピクセル座標を相互に変換する。"""
    pad: int
    cell_w: int
    cell_h: int
    gap: int
    cols: int
    rows: int

    def cell_origin(self, col: int, row: int) -> tuple[int, int]:
        return (self.pad + col * (self.cell_w + self.gap),
                self.pad + row * (self.cell_h + self.gap))

    def size(self) -> tuple[int, int]:
        return (self.pad * 2 + self.cols * self.cell_w + max(0, self.cols - 1) * self.gap,
                self.pad * 2 + self.rows * self.cell_h + max(0, self.rows - 1) * self.gap)

    def cell_at(self, x: int, y: int) -> Optional[tuple[int, int]]:
        """ピクセル座標が属するセル。グリッドの外なら None。

        セル間の隙間は手前のセルに含める（狭い隙間で操作が空振りしないように）。
        """
        cx, cy = x - self.pad, y - self.pad
        if cx < 0 or cy < 0:
            return None
        col = cx // (self.cell_w + self.gap)
        row = cy // (self.cell_h + self.gap)
        if col >= self.cols or row >= self.rows:
            return None
        return (int(col), int(row))

    def is_frame(self, x: int, y: int) -> bool:
        """外周の掴みしろの上か。"""
        w, h = self.size()
        return not (self.pad <= x < w - self.pad and self.pad <= y < h - self.pad)


def _cell_size(images: list[Image.Image], scale: float) -> tuple[int, int]:
    if not images:
        return (1, 1)
    return (max(int(round(im.width * scale)) for im in images),
            max(int(round(im.height * scale)) for im in images))


def _scaled(im: Image.Image, scale: float) -> Image.Image:
    return im.convert("RGBA").resize(
        (int(round(im.width * scale)), int(round(im.height * scale))), Image.LANCZOS)


def _dimmed(im: Image.Image) -> Image.Image:
    """OFF のスキルを示す、グレースケールで薄い画像にする。"""
    gray = im.convert("L").convert("RGBA")
    gray.putalpha(_DISABLED_ALPHA)
    return gray


def _paste_centered(canvas: Image.Image, im: Image.Image,
                    ox: int, oy: int, cell_w: int, cell_h: int) -> None:
    x = ox + (cell_w - im.width) // 2
    y = oy + (cell_h - im.height) // 2
    canvas.paste(im, (x, y), im)


def compose(items: list[tuple[int, int, Image.Image]], scale: float = 2.0,
            gap: int = 4, background: str = "none") -> tuple[Image.Image, GridMetrics]:
    """通常表示。items は (col, row, 画像) のリスト。"""
    if not items:
        return (Image.new("RGBA", (1, 1), (0, 0, 0, 0)),
                GridMetrics(0, 1, 1, gap, 0, 0))

    images = [im for _, _, im in items]
    cell_w, cell_h = _cell_size(images, scale)
    cols = max(col for col, _, _ in items) + 1
    rows = max(row for _, row, _ in items) + 1
    pad = PADDING if background == "dark" else 0
    metrics = GridMetrics(pad, cell_w, cell_h, gap, cols, rows)

    canvas = Image.new("RGBA", metrics.size(), _BG_COLOR if background == "dark" else (0, 0, 0, 0))
    for col, row, im in items:
        ox, oy = metrics.cell_origin(col, row)
        _paste_centered(canvas, _scaled(im, scale), ox, oy, cell_w, cell_h)
    return (canvas, metrics)


def compose_adjust(items: list[tuple[int, int, Image.Image]], scale: float = 2.0,
                   gap: int = 4, held: Optional[tuple[int, int, Image.Image]] = None,
                   cursor: Optional[tuple[int, int]] = None,
                   disabled: Optional[list[tuple[int, int, Image.Image]]] = None
                   ) -> tuple[Image.Image, GridMetrics]:
    """位置調整モード。外周の枠とグリッド線を描く。

    held は持ち上げ中のアイコン (col, row, 画像)。元のセルには描かず、
    カーソル位置に追従させる。グリッドは右と下に1セル分広げ、
    今より外側のセルへも置けるようにする。

    disabled は表示 OFF のスキル。場所は取り続けるので、
    どのマスが埋まっているか分かるようグレースケールで薄く描く。
    """
    disabled = disabled or []
    all_items = items + disabled + ([held] if held is not None else [])
    images = [im for _, _, im in all_items]
    cell_w, cell_h = _cell_size(images, scale)

    if all_items:
        cols = max(col for col, _, _ in all_items) + 2   # 右に1列分の余地
        rows = max(row for _, row, _ in all_items) + 2   # 下に1行分の余地
    else:
        cols = rows = 1
    metrics = GridMetrics(FRAME, cell_w, cell_h, gap, cols, rows)

    width, height = metrics.size()
    canvas = Image.new("RGBA", (width, height), _FRAME_BG)
    draw = ImageDraw.Draw(canvas)

    # グリッド領域の背景（完全透明だとクリックが下へ抜けてしまう）
    draw.rectangle((FRAME, FRAME, width - FRAME - 1, height - FRAME - 1), fill=_GRID_BG)

    hover = metrics.cell_at(*cursor) if cursor is not None else None
    for row in range(rows):
        for col in range(cols):
            ox, oy = metrics.cell_origin(col, row)
            box = (ox, oy, ox + cell_w - 1, oy + cell_h - 1)
            if hover == (col, row):
                draw.rectangle(box, fill=_HOVER_BG)
            draw.rectangle(box, outline=_CELL_LINE, width=1)

    for col, row, im in disabled:
        ox, oy = metrics.cell_origin(col, row)
        # 下地を敷かないとゲーム画面が透けて、薄いアイコンが埋もれてしまう
        draw.rectangle((ox, oy, ox + cell_w - 1, oy + cell_h - 1),
                       fill=_DISABLED_BG, outline=_CELL_LINE, width=1)
        _paste_centered(canvas, _dimmed(_scaled(im, scale)), ox, oy, cell_w, cell_h)

    for col, row, im in items:
        ox, oy = metrics.cell_origin(col, row)
        _paste_centered(canvas, _scaled(im, scale), ox, oy, cell_w, cell_h)

    # 掴みしろであることが分かるように外周を縁取る
    draw.rectangle((0, 0, width - 1, height - 1), outline=_FRAME_LINE, width=2)

    if held is not None:
        scaled = _scaled(held[2], scale)
        if cursor is not None:
            hx = cursor[0] - scaled.width // 2
            hy = cursor[1] - scaled.height // 2
        else:
            hx, hy = metrics.cell_origin(held[0], held[1])
        canvas.paste(scaled, (hx, hy), scaled)
        draw.rectangle((hx, hy, hx + scaled.width - 1, hy + scaled.height - 1),
                       outline=_HELD_LINE, width=2)

    return (canvas, metrics)

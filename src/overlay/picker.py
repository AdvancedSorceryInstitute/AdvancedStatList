"""画面上でスキルスロットを指定するピッカー。

起動時にゲームのクライアント領域を1枚キャプチャし、その静止画の上でクリックさせる。
半透明のウィンドウを被せる方式よりゲーム画面が明瞭に見え、ルーペも重ねられる。
"""

import tkinter as tk
from typing import Callable, Optional

import mss
import numpy as np
from PIL import Image, ImageDraw, ImageTk

from win.window import find_hwnd
from win.window_capture import capture_client

HELP_TEXT = "クリックでスキルを登録   方向キーで1px調整   Esc で終了"

# 登録済みスロットと同じ x / y に吸着させる距離（px）
SNAP_DISTANCE = 4

_HELP_BG = "#000000"
_HELP_FG = "#ffffff"
_CURSOR_COLOR = "#ffaa00"
_SNAPPED_COLOR = "#33ddff"
_PICKED_COLOR = "#33cc55"


class SlotPicker:
    """クライアント領域の静止画上でスロット矩形を選ばせる。

    クリックのたびに on_pick が呼ばれ、Esc または右クリックで終了する。
    """

    ZOOM = 4          # ルーペの拡大率
    LOUPE_SRC = 48    # ルーペに映す元領域の一辺（px）
    LOUPE_MARGIN = 24

    def __init__(self, master: tk.Misc, client: dict, slot_size: int,
                 on_pick: Callable[[int, int, int, int], None],
                 on_close: Optional[Callable[[], None]] = None,
                 guides: Optional[list[tuple[int, int]]] = None):
        self._client = client
        self._size = slot_size
        self._on_pick = on_pick
        self._on_close = on_close
        # 登録済みスロットの左上座標。同じ行・列に揃えるためのガイドに使う
        self._guides: list[tuple[int, int]] = list(guides or [])
        self._snapped = False
        self._pos = [0, 0]          # 選択矩形の左上（クライアント相対）
        self._photo = None
        self._loupe_photo = None

        self._shot = self._grab_client()

        self._win = tk.Toplevel(master)
        self._win.overrideredirect(True)
        self._win.geometry(
            f"{client['width']}x{client['height']}+{client['left']}+{client['top']}"
        )
        self._win.attributes("-topmost", True)
        self._win.configure(bg="black")

        self._canvas = tk.Canvas(self._win, highlightthickness=0, bd=0,
                                 width=client["width"], height=client["height"])
        self._canvas.pack(fill="both", expand=True)

        self._photo = ImageTk.PhotoImage(self._shot)
        self._canvas.create_image(0, 0, image=self._photo, anchor="nw")

        self._build_overlayed_widgets()
        self._bind_events()

        self._win.focus_force()
        self._canvas.focus_set()

    @property
    def shot(self) -> Image.Image:
        """ピッカーが表示しているクライアント領域の静止画。"""
        return self._shot

    # ------------------------------------------------------------ 構築

    def _grab_client(self) -> Image.Image:
        """クライアント領域の静止画を得る。

        まずウィンドウから直接取得する。ブラウザなどに隠れていても中身が取れるため、
        「追加ボタンを押す直前までゲームを前面にしておく」必要がなくなる。
        取得できない環境では画面キャプチャにフォールバックする。
        """
        img = capture_client(find_hwnd(), self._client["width"], self._client["height"])
        if img is not None:
            return img

        region = {
            "left": self._client["left"], "top": self._client["top"],
            "width": self._client["width"], "height": self._client["height"],
        }
        with mss.MSS() as sct:
            raw = np.array(sct.grab(region))
        return Image.fromarray(raw[:, :, 2::-1])  # BGRA → RGB

    def _build_overlayed_widgets(self) -> None:
        cw = self._client["width"]

        # 操作説明（画面上端中央）
        self._canvas.create_rectangle(cw // 2 - 260, 16, cw // 2 + 260, 56,
                                      fill=_HELP_BG, outline="", stipple="gray50")
        self._canvas.create_text(cw // 2, 36, text=HELP_TEXT, fill=_HELP_FG,
                                 font=("", 12, "bold"))

        # 選択枠とルーペ
        self._rect_id = self._canvas.create_rectangle(0, 0, 0, 0,
                                                      outline=_CURSOR_COLOR, width=2)
        self._loupe_id = self._canvas.create_image(0, 0, anchor="nw")

    def _bind_events(self) -> None:
        self._canvas.bind("<Motion>", self._on_motion)
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<Button-3>", lambda _: self.close())
        self._win.bind("<Escape>", lambda _: self.close())
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            self._win.bind(f"<{key}>", lambda _, dx=dx, dy=dy: self._nudge(dx, dy))
        self._win.bind("<Return>", lambda _: self._commit())

    # ------------------------------------------------------------ 操作

    def _on_motion(self, event: tk.Event) -> None:
        # カーソルを中心に選択枠を置く
        self._pos = [event.x - self._size // 2, event.y - self._size // 2]
        self._apply_guides()
        self._refresh()

    def _apply_guides(self) -> None:
        """登録済みスロットと近い座標なら揃える。

        クイックスロットは整列しているので、2個目以降は行・列を合わせるだけで
        きれいに揃う。画像から枠を検出する方式はアイコンの絵柄のエッジを拾って
        安定しなかったため、この方式にしている。
        """
        self._snapped = False
        for axis in (0, 1):
            for guide in {g[axis] for g in self._guides}:
                if abs(self._pos[axis] - guide) <= SNAP_DISTANCE:
                    self._pos[axis] = guide
                    self._snapped = True
                    break

    def _nudge(self, dx: int, dy: int) -> None:
        self._pos[0] += dx
        self._pos[1] += dy
        self._snapped = False   # 手動調整中は吸着させない
        self._refresh()

    def _on_click(self, event: tk.Event) -> None:
        self._on_motion(event)
        self._commit()

    def _commit(self) -> None:
        x, y = self._clamped()
        self._on_pick(x, y, self._size, self._size)
        if self._win is None:
            return   # コールバック内で閉じられた（位置の選び直しは1つで終了）
        # 登録済みの位置を残して、続けて選べるようにする
        self._canvas.create_rectangle(x, y, x + self._size, y + self._size,
                                      outline=_PICKED_COLOR, width=2)
        self._guides.append((x, y))

    def _clamped(self) -> tuple[int, int]:
        x = max(0, min(self._pos[0], self._client["width"] - self._size))
        y = max(0, min(self._pos[1], self._client["height"] - self._size))
        return (x, y)

    def _refresh(self) -> None:
        x, y = self._clamped()
        self._canvas.coords(self._rect_id, x, y, x + self._size, y + self._size)
        self._canvas.itemconfig(self._rect_id,
                                outline=_SNAPPED_COLOR if self._snapped else _CURSOR_COLOR)
        self._canvas.tag_raise(self._rect_id)
        self._update_loupe(x, y)

    def _update_loupe(self, x: int, y: int) -> None:
        """選択位置の周辺を拡大して枠の合わせ具合を確認できるようにする。"""
        half = self.LOUPE_SRC // 2
        cx = x + self._size // 2
        cy = y + self._size // 2
        box = (cx - half, cy - half, cx + half, cy + half)
        src = self._shot.crop(box).convert("RGBA")
        zoom = src.resize((self.LOUPE_SRC * self.ZOOM, self.LOUPE_SRC * self.ZOOM),
                          Image.NEAREST)

        # 拡大図の中に選択枠を描く
        draw = ImageDraw.Draw(zoom)
        left = (half - self._size // 2) * self.ZOOM
        top = (half - self._size // 2) * self.ZOOM
        draw.rectangle((left, top, left + self._size * self.ZOOM - 1,
                        top + self._size * self.ZOOM - 1),
                       outline=(255, 170, 0, 255), width=2)
        draw.rectangle((0, 0, zoom.width - 1, zoom.height - 1),
                       outline=(255, 255, 255, 200), width=1)

        self._loupe_photo = ImageTk.PhotoImage(zoom)
        self._canvas.itemconfig(self._loupe_id, image=self._loupe_photo)

        # カーソルに重ならないよう右下に置き、画面端では内側へ折り返す
        lx = cx + self.LOUPE_MARGIN
        ly = cy + self.LOUPE_MARGIN
        if lx + zoom.width > self._client["width"]:
            lx = cx - self.LOUPE_MARGIN - zoom.width
        if ly + zoom.height > self._client["height"]:
            ly = cy - self.LOUPE_MARGIN - zoom.height
        self._canvas.coords(self._loupe_id, lx, ly)
        self._canvas.tag_raise(self._loupe_id)

    # ------------------------------------------------------------ 終了

    def close(self) -> None:
        if self._win is not None:
            self._win.destroy()
            self._win = None
        if self._on_close is not None:
            self._on_close()

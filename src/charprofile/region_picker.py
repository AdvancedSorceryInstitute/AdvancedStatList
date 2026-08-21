"""識別範囲をドラッグで指定するピッカー。

スキルスロットのピッカー（overlay/picker.py）と同じく、ゲームのクライアント領域を
1枚キャプチャし、その静止画の上で選ばせる。こちらは固定サイズではなく、
クイックスロットの並び全体を囲めるよう任意サイズの矩形をドラッグで取る。
"""

import tkinter as tk
from typing import Callable, Optional

import mss
import numpy as np
from PIL import Image, ImageTk

from win.window import find_hwnd
from win.window_capture import capture_client

HELP_TEXT = "キャラクター判別に使う範囲をドラッグで囲んでください   Esc で終了"
HINT_TEXT = "スキルスロット(F1~F12)推奨"

# これより小さい範囲は判別に使えないので確定させない
MIN_SIZE = 16

_HELP_BG = "#000000"
_HELP_FG = "#ffffff"
_RECT_COLOR = "#ffaa00"
_OLD_RECT_COLOR = "#4488cc"


class RegionPicker:
    """クライアント領域の静止画上で矩形をドラッグさせる。

    確定すると on_pick(x, y, w, h) を呼んで閉じる。
    """

    def __init__(self, master: tk.Misc, client: dict,
                 on_pick: Callable[[int, int, int, int, Image.Image], None],
                 on_close: Optional[Callable[[], None]] = None,
                 current: Optional[tuple[int, int, int, int]] = None):
        self._client = client
        self._on_pick = on_pick
        self._on_close = on_close
        self._start: Optional[tuple[int, int]] = None
        self._rect = (0, 0, 0, 0)
        self._closed = False

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

        self._build_overlayed_widgets(current)
        self._bind_events()

        self._win.focus_force()
        self._canvas.focus_set()

    # ------------------------------------------------------------ 構築

    def _grab_client(self) -> Image.Image:
        """クライアント領域の静止画を得る。

        ウィンドウから直接取得するので、ゲームが背面にあっても中身が取れる。
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

    def _build_overlayed_widgets(self, current: Optional[tuple[int, int, int, int]]) -> None:
        cw = self._client["width"]

        self._canvas.create_rectangle(cw // 2 - 300, 16, cw // 2 + 300, 76,
                                      fill=_HELP_BG, outline="", stipple="gray50")
        self._canvas.create_text(cw // 2, 36, text=HELP_TEXT, fill=_HELP_FG,
                                 font=("", 12, "bold"))
        self._canvas.create_text(cw // 2, 60, text=HINT_TEXT, fill="#bbbbbb", font=("", 9))

        # 設定済みの範囲を薄く見せておくと、選び直しの目安になる
        if current is not None and current[2] > 0 and current[3] > 0:
            x, y, w, h = current
            self._canvas.create_rectangle(x, y, x + w, y + h,
                                          outline=_OLD_RECT_COLOR, width=1, dash=(4, 3))

        self._rect_id = self._canvas.create_rectangle(0, 0, 0, 0,
                                                      outline=_RECT_COLOR, width=2)
        self._size_id = self._canvas.create_text(0, 0, text="", fill=_HELP_FG,
                                                 font=("", 10, "bold"), anchor="nw")

    def _bind_events(self) -> None:
        self._canvas.bind("<Button-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Button-3>", lambda _: self.close())
        self._win.bind("<Escape>", lambda _: self.close())

    # ------------------------------------------------------------ 操作

    def _on_press(self, event: tk.Event) -> None:
        self._start = (event.x, event.y)
        self._rect = (event.x, event.y, 0, 0)
        self._refresh()

    def _on_drag(self, event: tk.Event) -> None:
        if self._start is None:
            return
        x0, y0 = self._start
        x1 = max(0, min(self._client["width"], event.x))
        y1 = max(0, min(self._client["height"], event.y))
        self._rect = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        self._refresh()

    def _on_release(self, event: tk.Event) -> None:
        if self._start is None:
            return
        self._start = None
        x, y, w, h = self._rect
        if w < MIN_SIZE or h < MIN_SIZE:
            # 誤クリックとみなして選択をやり直させる
            self._rect = (0, 0, 0, 0)
            self._refresh()
            return
        self._on_pick(x, y, w, h, self._shot)
        self.close()

    def _refresh(self) -> None:
        x, y, w, h = self._rect
        self._canvas.coords(self._rect_id, x, y, x + w, y + h)
        if w > 0 and h > 0:
            self._canvas.itemconfig(self._size_id, text=f"{w} x {h}")
            self._canvas.coords(self._size_id, x, max(0, y - 18))
        else:
            self._canvas.itemconfig(self._size_id, text="")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._win.destroy()
        if self._on_close is not None:
            self._on_close()

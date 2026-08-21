"""スロット領域のキャプチャ。

スロットごとに grab するとデバイスコンテキスト取得のオーバーヘッドが積み上がるため、
全スロットを包むバウンディング矩形を1回だけ取得して切り出す。
"""

from typing import Optional

import mss
import numpy as np
from PIL import Image

from .config import Slot


def bounding_rect(slots: list[Slot]) -> Optional[tuple[int, int, int, int]]:
    """スロット群を包む矩形 (x, y, w, h) をクライアント相対で返す。"""
    if not slots:
        return None
    left = min(s.x for s in slots)
    top = min(s.y for s in slots)
    right = max(s.x + s.w for s in slots)
    bottom = max(s.y + s.h for s in slots)
    return (left, top, right - left, bottom - top)


class SlotCapture:
    """mss インスタンスを使い回してスロット画像を取得する。

    mss はスレッドセーフではないため、生成したスレッド内でのみ使うこと。
    """

    def __init__(self):
        self._sct: Optional[mss.mss] = None

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None

    def grab_region(self, region: dict) -> Image.Image:
        """絶対座標の領域をキャプチャして RGB 画像で返す。"""
        if self._sct is None:
            self._sct = mss.MSS()
        raw = np.array(self._sct.grab(region))
        return Image.fromarray(raw[:, :, 2::-1])  # BGRA → RGB

    def grab_slots(self, client: dict, slots: list[Slot]) -> list[Image.Image]:
        """クライアント相対のスロット矩形群を切り出して返す。"""
        bounds = bounding_rect(slots)
        if bounds is None:
            return []
        bx, by, bw, bh = bounds

        region = {
            "left": client["left"] + bx,
            "top": client["top"] + by,
            "width": bw,
            "height": bh,
        }
        base = self.grab_region(region)
        return [
            base.crop((s.x - bx, s.y - by, s.x - bx + s.w, s.y - by + s.h))
            for s in slots
        ]

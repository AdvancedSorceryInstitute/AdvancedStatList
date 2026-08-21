"""ウィンドウの中身を直接取得する（PrintWindow）。

画面キャプチャと違い、他のウィンドウに隠れていても中身を取得できる。
1回あたり 40ms 程度かかるため常時の更新には向かない。ピッカーのように
「確実に最新のゲーム画面が欲しい」場面で使う。
"""

import ctypes
from typing import Optional

import numpy as np
from PIL import Image

from . import layered

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2

_setup_done = False


def _setup() -> None:
    global _setup_done
    if _setup_done:
        return
    u, g = layered.user32, layered.gdi32
    u.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    g.CreateCompatibleBitmap.restype = ctypes.c_void_p
    g.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    g.GetDIBits.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
    ]
    _setup_done = True


def capture_client(hwnd: int, width: int, height: int) -> Optional[Image.Image]:
    """クライアント領域を RGB 画像で取得する。取得できなければ None。"""
    if not hwnd or width <= 0 or height <= 0:
        return None
    _setup()
    u, g = layered.user32, layered.gdi32

    hdc = u.GetDC(hwnd)
    mem_dc = g.CreateCompatibleDC(hdc)
    hbmp = g.CreateCompatibleBitmap(hdc, width, height)
    old_bmp = g.SelectObject(mem_dc, hbmp)
    try:
        ok = u.PrintWindow(hwnd, mem_dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
        if not ok:
            return None

        bmi = layered.BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(layered.BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # トップダウン
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(width * height * 4)
        if not g.GetDIBits(mem_dc, hbmp, 0, height, buf, ctypes.byref(bmi), 0):
            return None

        arr = np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 4)
        # 描画されず真っ黒なだけの場合は取得失敗とみなす
        if not arr[:, :, :3].any():
            return None
        return Image.fromarray(arr[:, :, 2::-1])  # BGRA → RGB
    finally:
        g.SelectObject(mem_dc, old_bmp)
        g.DeleteObject(hbmp)
        g.DeleteDC(mem_dc)
        u.ReleaseDC(hwnd, hdc)

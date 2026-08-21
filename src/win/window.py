"""マビノギのウィンドウ探索と座標取得。

scanner / notifier / overlay から共通で使う Win32 ラッパー。
"""

import ctypes
from ctypes import wintypes
from typing import Optional

# マビノギ本体のウィンドウクラス名
MABINOGI_WINDOW_CLASS = "Mabinogi"

_user32_cache = None


def user32():
    """user32 の関数シグネチャを設定して返す（64bit でハンドルが切り詰められるのを防ぐ）。"""
    global _user32_cache
    if _user32_cache is None:
        u = ctypes.windll.user32
        u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u.FindWindowW.restype = wintypes.HWND
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        # ウィンドウ座標を mss のキャプチャと同じ物理ピクセルで得るために必須。
        # (未設定だと画面スケーリング率で割った論理座標が返り、位置がずれる)
        u.SetProcessDPIAware()
        _user32_cache = u
    return _user32_cache


def find_hwnd() -> Optional[int]:
    """マビノギのウィンドウハンドルを返す。見つからない・不可視・最小化なら None。"""
    u = user32()
    hwnd = u.FindWindowW(MABINOGI_WINDOW_CLASS, None)
    if not hwnd or not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd):
        return None
    return hwnd


def get_client_rect(hwnd: Optional[int] = None) -> Optional[dict]:
    """クライアント領域を絶対座標で返す。

    ウィンドウ単位で扱うことで、ゲームがどのモニターにあっても追従できる。
    """
    if hwnd is None:
        hwnd = find_hwnd()
    if hwnd is None:
        return None

    u = user32()
    rect = wintypes.RECT()
    if not u.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = wintypes.POINT(0, 0)
    if not u.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None

    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    return {"left": origin.x, "top": origin.y, "width": width, "height": height}


def get_window_rect(hwnd: Optional[int] = None) -> Optional[tuple[int, int, int, int]]:
    """ウィンドウ全体（枠込み）の (left, top, width, height) を返す。"""
    if hwnd is None:
        hwnd = find_hwnd()
    if hwnd is None:
        return None

    rect = wintypes.RECT()
    if not user32().GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def is_foreground() -> bool:
    """マビノギが現在アクティブ（最前面でフォーカスを持つ）かどうか。

    ハンドル比較ではなくクラス名で判定するため、ウィンドウを開き直されても追従する。
    """
    u = user32()
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return False
    buf = ctypes.create_unicode_buffer(256)
    if not u.GetClassNameW(hwnd, buf, 256):
        return False
    return buf.value == MABINOGI_WINDOW_CLASS

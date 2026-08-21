"""クリック透過レイヤードウィンドウの共通処理。

notifier の通知バナーと overlay のスキル表示が共有する。

64bit 環境では argtypes / restype を明示しないとハンドルやポインタが
c_int に切り詰められて OverflowError になるため、モジュール読み込み時に
まとめて設定する。
"""

import ctypes
from ctypes import wintypes
from typing import Optional

import numpy as np
from PIL import Image

# --- ウィンドウスタイル ---------------------------------------------------
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020   # クリック透過
WS_EX_NOACTIVATE = 0x08000000    # フォーカスを奪わない
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080    # タスクバー・Alt+Tab に出さない
GWL_EXSTYLE = -20

# --- メッセージ / 定数 ----------------------------------------------------
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_TIMER = 0x0113
WM_NCHITTEST = 0x0084
WM_EXITSIZEMOVE = 0x0232
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_APP = 0x8000
HTCLIENT = 1
HTCAPTION = 2                    # ここを掴むとOSがウィンドウを移動してくれる
IDC_ARROW = 32512
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 0x2

# SetWindowPos 用
HWND_TOPMOST = ctypes.c_void_p(-1)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


# --- Win32 構造体 ---------------------------------------------------------

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,  # LRESULT = LONG_PTR (64bit)
    ctypes.c_void_p,   # HWND
    ctypes.c_uint,     # UINT
    ctypes.c_size_t,   # WPARAM = UINT_PTR
    ctypes.c_ssize_t,  # LPARAM = LONG_PTR
)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
        ("hIconSm", ctypes.c_void_p),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_ulong),
        ("ptX", ctypes.c_long),
        ("ptY", ctypes.c_long),
    ]


# --- API シグネチャ設定 ---------------------------------------------------

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32


def _setup_argtypes() -> None:
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p

    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
    ]
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.CreateWindowExW.argtypes = [
        ctypes.c_ulong,    # dwExStyle
        ctypes.c_wchar_p,  # lpClassName
        ctypes.c_wchar_p,  # lpWindowName
        ctypes.c_ulong,    # dwStyle
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,  # X, Y, W, H
        ctypes.c_void_p,   # hWndParent
        ctypes.c_void_p,   # hMenu
        ctypes.c_void_p,   # hInstance
        ctypes.c_void_p,   # lpParam
    ]
    user32.DestroyWindow.argtypes = [ctypes.c_void_p]
    user32.LoadCursorW.restype = ctypes.c_void_p
    user32.LoadCursorW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetTimer.restype = ctypes.c_size_t
    user32.SetTimer.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_void_p]
    user32.KillTimer.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    user32.GetMessageW.restype = ctypes.c_int
    user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
    user32.UnregisterClassW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
    user32.SetWindowPos.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]

    user32.GetDC.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.UpdateLayeredWindow.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
        ctypes.c_void_p, ctypes.POINTER(POINT), wintypes.DWORD,
        ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
    ]

    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateDIBSection.restype = ctypes.c_void_p
    gdi32.CreateDIBSection.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint,
    ]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]


_setup_argtypes()


# --- ヘルパー -------------------------------------------------------------

def register_class(class_name: str, wnd_proc: WNDPROC):
    """ウィンドウクラスを登録して hInstance を返す。失敗時は None。

    wnd_proc は呼び出し側で参照を保持すること（GC されるとクラッシュする）。
    """
    hInstance = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = wnd_proc
    wc.hInstance = hInstance
    wc.lpszClassName = class_name
    # カーソル未設定だとウィンドウ上でカーソル形状が直前のまま残る
    wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
    if not user32.RegisterClassExW(ctypes.byref(wc)):
        return None
    return hInstance


def create_window(class_name: str, hInstance, x: int, y: int, w: int, h: int,
                  ex_style: int) -> int:
    """クリック透過レイヤードウィンドウを作成する。失敗時は 0。"""
    return user32.CreateWindowExW(
        ex_style, class_name, "", WS_POPUP, x, y, w, h,
        None, None, hInstance, None,
    ) or 0


def signed_low(value: int) -> int:
    """lParam の下位16bitを符号付きで取り出す（マルチモニタでは負になりうる）。"""
    v = value & 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


def signed_high(value: int) -> int:
    """lParam の上位16bitを符号付きで取り出す。"""
    return signed_low((value >> 16) & 0xFFFF)


def get_window_pos(hwnd: int) -> tuple[int, int]:
    """ウィンドウ左上のスクリーン座標を返す。"""
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top)


def bring_to_top(hwnd: int) -> None:
    """最前面（TOPMOST）に再配置する。他アプリが前に出た後の復帰用。"""
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def set_click_through(hwnd: int, enabled: bool) -> None:
    """クリック透過（WS_EX_TRANSPARENT）を動的に切り替える。"""
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    style = (style | WS_EX_TRANSPARENT) if enabled else (style & ~WS_EX_TRANSPARENT)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)


def get_cursor_pos() -> tuple[int, int]:
    """マウスカーソルのスクリーン座標を返す。"""
    pt = POINT(0, 0)
    user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


def update_layered(hwnd: int, img: Image.Image,
                   x: Optional[int] = None, y: Optional[int] = None,
                   alpha: int = 255) -> None:
    """RGBA 画像を UpdateLayeredWindow でピクセル単位アルファ付きに描画する。

    x, y を渡すと位置も同時に反映される（移動・リサイズは別途呼ばなくてよい）。
    省略した場合は現在の位置を維持する。ユーザーがドラッグで動かしている最中に
    描画位置を上書きして引き戻さないために使う。

    alpha は画像全体にかける不透明度（0-255）。ピクセルごとのアルファに
    さらに乗算されるので、輪郭のなめらかさは保たれる。
    """
    bw, bh = img.size

    # RGBA → 事前乗算済み BGRA（UpdateLayeredWindow が要求する形式）
    arr = np.asarray(img, dtype=np.uint16)  # H x W x 4 (R,G,B,A)
    a = arr[:, :, 3:4]
    rgb = arr[:, :, :3] * a // 255
    bgra = np.dstack([rgb[:, :, 2], rgb[:, :, 1], rgb[:, :, 0], arr[:, :, 3]]).astype(np.uint8)
    buf = np.ascontiguousarray(bgra).tobytes()

    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = bw
    bmi.bmiHeader.biHeight = -bh  # トップダウン（画像の行順とそろえる）
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB

    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    ctypes.memmove(bits, buf, len(buf))
    old_bmp = gdi32.SelectObject(mem_dc, hbmp)

    # AC_SRC_OVER, SourceConstantAlpha, AC_SRC_ALPHA
    blend = BLENDFUNCTION(0, 0, max(0, min(255, int(alpha))), 1)
    pt_dst = ctypes.byref(POINT(x, y)) if x is not None and y is not None else None
    size = SIZE(bw, bh)
    pt_src = POINT(0, 0)
    user32.UpdateLayeredWindow(
        hwnd, screen_dc, pt_dst, ctypes.byref(size),
        mem_dc, ctypes.byref(pt_src), 0, ctypes.byref(blend), ULW_ALPHA,
    )

    # システム側へコピー済みなので GDI リソースは解放してよい
    gdi32.SelectObject(mem_dc, old_bmp)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(None, screen_dc)

"""二重起動の検出。

Win32 の名前付きミューテックスで、同じユーザーのセッションに
本体がすでに常駐していないかを起動直後に判定する。
"""

import ctypes
from ctypes import wintypes

# 他アプリと衝突しないよう固有の名前にする
_MUTEX_NAME = "AdvancedStatList-SingleInstance"
_ERROR_ALREADY_EXISTS = 183

# MessageBoxW のスタイル
_MB_OK = 0x00000000
_MB_ICONWARNING = 0x00000030
_MB_SETFOREGROUND = 0x00010000

# プロセスが動いている間ミューテックスを握り続けるための参照
_mutex_handle = None


def acquire() -> bool:
    """起動権を取得できたら True、すでに起動中なら False を返す。"""
    global _mutex_handle
    if _mutex_handle is not None:
        return True

    k = ctypes.windll.kernel32
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = k.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        # ミューテックスを作れない環境では起動を妨げない
        return True
    if k.GetLastError() == _ERROR_ALREADY_EXISTS:
        k.CloseHandle(handle)
        return False

    # ハンドルはプロセス終了時に OS が解放する
    _mutex_handle = handle
    return True


def warn_already_running() -> None:
    """すでに起動している旨のダイアログを出す（GUI 起動前でも使える）。"""
    u = ctypes.windll.user32
    u.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                              wintypes.UINT]
    u.MessageBoxW(
        None,
        "AdvancedStatList はすでに起動しています。\n"
        "タスクトレイのアイコンから操作してください。",
        "AdvancedStatList",
        _MB_OK | _MB_ICONWARNING | _MB_SETFOREGROUND,
    )

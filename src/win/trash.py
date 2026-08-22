"""ファイル・フォルダをごみ箱へ移動する。

誤って消したバフを手で戻せるよう、完全削除ではなくごみ箱送りにする。
"""

import ctypes
from ctypes import wintypes
from pathlib import Path

_FO_DELETE = 0x0003
_FOF_SILENT = 0x0004          # 進捗ダイアログを出さない
_FOF_NOCONFIRMATION = 0x0010  # 確認は呼び出し側で取るので出さない
_FOF_ALLOWUNDO = 0x0040       # ごみ箱へ送る
_FOF_NOERRORUI = 0x0400       # 失敗しても戻り値で受け取る


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),   # FILEOP_FLAGS は WORD
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def send_to_trash(path: Path) -> bool:
    """path をごみ箱へ移動する。成功したら True。

    ごみ箱に入らない場合（容量超過やネットワークドライブなど）は
    完全削除されてしまうため、そのときは何もせず False を返す。
    """
    if not path.exists():
        return True
    op = _SHFILEOPSTRUCTW(
        hwnd=None,
        wFunc=_FO_DELETE,
        # pFrom は連結した複数パスを受けるため、終端に NUL がもう1つ要る
        pFrom=f"{path.resolve()}\0\0",
        pTo=None,
        fFlags=_FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI,
        fAnyOperationsAborted=False,
        hNameMappings=None,
        lpszProgressTitle=None,
    )
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return result == 0 and not op.fAnyOperationsAborted

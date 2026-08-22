"""キーの押下状態の取得。

GetAsyncKeyState はフォーカスに関係なく現在の押下状態を返すので、
マビノギを操作している最中でも押しっぱなしかどうかを見られる。
"""

import ctypes
from typing import Optional

# 選択できるキー。設定ファイルには左のキー名で保存する
KEY_CHOICES: dict[str, tuple[str, int]] = {
    "shift": ("Shift", 0x10),
    "ctrl": ("Ctrl", 0x11),
    "alt": ("Alt", 0x12),
    "tab": ("Tab", 0x09),
    "space": ("Space", 0x20),
}

DEFAULT_KEY = "shift"

# 選択肢には出さないが、内部で使うキー
VK_ESCAPE = 0x1B

_user32 = ctypes.windll.user32
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short


def normalize_key(name: Optional[str]) -> str:
    """設定値を選択肢のキー名に整える。未知の値は既定のキーにする。"""
    key = str(name).strip().lower() if name is not None else ""
    return key if key in KEY_CHOICES else DEFAULT_KEY


def key_label(name: str) -> str:
    """表示用のキー名（例: shift -> Shift）。"""
    return KEY_CHOICES[normalize_key(name)][0]


def is_key_down(name: str) -> bool:
    """そのキーが今押されているか。"""
    return is_vk_down(KEY_CHOICES[normalize_key(name)][1])


def is_vk_down(vk: int) -> bool:
    """仮想キーコードを指定して押下状態を見る。"""
    # 最上位ビットが立っていれば押下中（下位ビットは前回呼び出し以降に押されたか）
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)

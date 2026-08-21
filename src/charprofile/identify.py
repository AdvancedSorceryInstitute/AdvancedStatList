"""キャラクターの判別。

識別範囲（全プロファイル共通・解像度ごと）を切り出した画像を指紋と呼び、
プロファイルごとに記録しておいたものと相関で比べる。

絶対閾値だけで合否を決めていない。クールタイム中の暗転や残り秒数の描画で
見た目は多少変わるため、閾値を上げると判別できず、下げると別キャラに当たる。
全プロファイルを並べて比べ、1位と2位の差（マージン）で確信度を測る。
"""

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from win.window import find_hwnd, get_client_rect
from win.window_capture import capture_client

from .store import CharacterProfile, ProfileStore


@dataclass
class IdentifyResult:
    """判別の結果。profile が None なら判別できなかった。"""
    profile: Optional[CharacterProfile] = None
    score: float = 0.0
    margin: float = 0.0
    reason: str = ""
    # 時間を置いて試し直す価値があるか。設定が足りていないだけなら何度試しても同じ
    retriable: bool = True

    @property
    def ok(self) -> bool:
        return self.profile is not None


def client_key(client: dict) -> str:
    """クライアント領域から解像度キーを作る（overlay.yaml と同じ形式）。"""
    return f"{client['width']}x{client['height']}"


def current_key() -> Optional[str]:
    client = get_client_rect()
    return None if client is None else client_key(client)


def grab_region(rect: tuple[int, int, int, int]) -> Optional[Image.Image]:
    """クライアント領域を1枚取得し、識別範囲を切り出す。

    PrintWindow を使うので、ゲームが背面にあっても中身が取れる。
    GUI を操作しながら記録・判別できるのはこのため。
    """
    client = get_client_rect()
    if client is None:
        return None
    shot = capture_client(find_hwnd(), client["width"], client["height"])
    if shot is None:
        return None
    return crop_region(shot, rect)


def crop_region(shot: Image.Image, rect: tuple[int, int, int, int]) -> Optional[Image.Image]:
    """静止画から識別範囲を切り出す。画面外へはみ出す指定なら None。"""
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return None
    if x < 0 or y < 0 or x + w > shot.width or y + h > shot.height:
        return None
    return shot.crop((x, y, x + w, y + h))


def save_fingerprint(store: ProfileStore, profile_id: str, key: str,
                     shot: Optional[Image.Image] = None) -> bool:
    """現在の画面を、そのプロファイルの指紋として記録する。

    shot を渡すとその静止画から切り出す（範囲指定の直後など）。
    """
    rect = store.region(key)
    if rect is None:
        return False
    image = crop_region(shot, rect) if shot is not None else grab_region(rect)
    if image is None:
        return False
    path = store.fingerprint_path(profile_id, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path)
    return True


def load_fingerprint(store: ProfileStore, profile_id: str, key: str) -> Optional[Image.Image]:
    path = store.fingerprint_path(profile_id, key)
    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGB")
    except Exception:
        return None


def _score(current: np.ndarray, fingerprint: np.ndarray) -> Optional[float]:
    """同サイズの画像同士の相関（0〜1）。サイズが違えば比較しない。"""
    if current.shape != fingerprint.shape:
        return None
    res = cv2.matchTemplate(current, fingerprint, cv2.TM_CCOEFF_NORMED)
    return float(res[0][0])


def identify(store: ProfileStore) -> IdentifyResult:
    """現在の画面がどのプロファイルのキャラクターかを判別する。"""
    client = get_client_rect()
    if client is None:
        return IdentifyResult(reason="マビノギのウィンドウが見つかりません")

    key = client_key(client)
    rect = store.region(key)
    if rect is None:
        return IdentifyResult(reason=f"{key} の識別範囲が未設定です", retriable=False)

    image = grab_region(rect)
    if image is None:
        return IdentifyResult(reason="ゲーム画面を取得できませんでした")
    current = np.array(image)

    scores: list[tuple[float, CharacterProfile]] = []
    for profile in store.profiles:
        fingerprint = load_fingerprint(store, profile.id, key)
        if fingerprint is None:
            continue
        value = _score(current, np.array(fingerprint))
        if value is not None:
            scores.append((value, profile))

    if not scores:
        return IdentifyResult(reason=f"{key} の識別画像が未登録です", retriable=False)

    scores.sort(key=lambda s: s[0], reverse=True)
    best, profile = scores[0]
    second = scores[1][0] if len(scores) > 1 else 0.0
    margin = best - second

    if best < store.detect.min_score:
        return IdentifyResult(score=best, margin=margin,
                              reason=f"どの識別画像とも一致しません ({best:.2f})")
    if len(scores) > 1 and margin < store.detect.min_margin:
        return IdentifyResult(score=best, margin=margin,
                              reason=f"候補が絞り込めません ({best:.2f} / 差 {margin:.2f})")

    return IdentifyResult(profile=profile, score=best, margin=margin)

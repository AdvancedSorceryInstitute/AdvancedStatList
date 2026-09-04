"""ミッション中かどうかの判定。

画面右上の EXIT ボタンの有無で見る。記録しておいた見た目と相関で比べるだけの
単純な作りだが、そのままでは実用に耐えない事情が3つあるので手当てしている。

  1. mss の grab はキャプチャ面積によらず1回あたり約16.7ms（垂直同期待ち）かかる。
     描画の tick ごとに見るとオーバーレイスレッドの占有時間が倍になるため、
     判定は interval 秒ごとに間引き、その間は直前の結果を使う。
  2. EXIT ボタンにカーソルを乗せるとボタンが拡大し、ツールチップが下半分に被る。
     実測で相関は 0.40 まで落ち、テンプレートでは追随できない。変化が起きるのは
     カーソルがそこにあるときだけなので、周辺にカーソルがある間は判定を保留する。
  3. ダイアログなどで一瞬隠れたときに表示がばたつかないよう、ミッション外への
     遷移にだけ grace 秒の猶予を置く。逆向き（外→中）は即座に反映する。
"""

import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from win.layered import get_cursor_pos

from .config import MissionDetect


class MissionDetector:
    """EXIT ボタンの有無からミッション中かを判定する。

    テンプレートは解像度ごとに1枚。読み込みは使い回し、
    解像度が変わったときだけ読み直す。

    記録済みのものが無ければ同梱の既定テンプレート（assets/mission/）を使うので、
    既定の解像度なら登録しなくてもそのまま判定できる。
    """

    def __init__(self, templates_dir: Path, defaults_dir: Path,
                 settings: MissionDetect):
        self._dir = templates_dir
        self._defaults_dir = defaults_dir
        self._settings = settings

        self._loaded_key: Optional[str] = None
        self._template: Optional[np.ndarray] = None

        self._in_mission = False
        self._checked_at = 0.0     # 最後に判定した時刻
        self._seen_at = 0.0        # 最後に EXIT ボタンを見つけた時刻

    # ------------------------------------------------------------ 登録

    def template_path(self, key: str) -> Path:
        """記録先。ここに無ければ同梱の既定テンプレートを使う。"""
        return self._dir / f"exit_{key}.png"

    def _default_path(self) -> Path:
        """同梱テンプレート。解像度によらず1枚を当てる（default_mission_region と対）。"""
        return self._defaults_dir / "exit.png"

    def status(self, key: str) -> str:
        """その解像度の判定材料の出どころ。custom | default | none

        範囲とテンプレートは対で使うので、片方でも欠けていれば判定できない。
        """
        if self._settings.region(key) is None:
            return "none"
        if self.template_path(key).exists():
            return "custom"
        return "default" if self._default_path().exists() else "none"

    def configured(self, key: str) -> bool:
        """その解像度で判定できる状態か。"""
        return self.status(key) != "none"

    def save_template(self, key: str, shot: Image.Image,
                      rect: tuple[int, int, int, int]) -> bool:
        """静止画から EXIT ボタンを切り出してテンプレートとして記録する。"""
        x, y, w, h = rect
        if w <= 0 or h <= 0 or x < 0 or y < 0:
            return False
        if x + w > shot.width or y + h > shot.height:
            return False
        path = self.template_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        shot.crop((x, y, x + w, y + h)).convert("RGB").save(path)
        self._invalidate()
        return True

    def _invalidate(self) -> None:
        """テンプレートを読み直させ、判定結果も捨てる（範囲を変えたとき）。"""
        self._loaded_key = None
        self._template = None
        self._in_mission = False
        self._checked_at = 0.0
        self._seen_at = 0.0

    def _load(self, key: str) -> Optional[np.ndarray]:
        if self._loaded_key == key:
            return self._template
        path = self.template_path(key)
        if not path.exists():
            path = self._default_path()
        template = None
        if path.exists():
            try:
                template = np.array(Image.open(path).convert("RGB"))
            except Exception as e:
                print(f"EXIT ボタンのテンプレートを読み込めません: {e}")
        self._loaded_key = key
        self._template = template
        return template

    # ------------------------------------------------------------ 判定

    def in_mission(self, key: str, client: dict, capture) -> bool:
        """ミッション中か。判定できないときは True（＝表示を止めない）を返す。"""
        rect = self._settings.region(key)
        template = self._load(key)
        if rect is None or template is None:
            return True
        if template.shape[:2] != (rect[3], rect[2]):
            # 範囲だけ書き換えてテンプレートを取り直していない状態。
            # 一致しない扱いにすると永久に非表示になるので、判定不能として扱う
            return True

        now = time.time()
        if now - self._checked_at >= self._settings.interval:
            self._checked_at = now
            if not self._cursor_near(client, rect):
                self._update(now, self._match(capture, client, rect, template))
        return self._in_mission

    def _update(self, now: float, found: bool) -> None:
        if found:
            self._seen_at = now
            self._in_mission = True
        elif self._in_mission and now - self._seen_at < self._settings.grace:
            pass   # 猶予のうちは見失ってもミッション中のままにする
        else:
            self._in_mission = False

    def _cursor_near(self, client: dict, rect: tuple[int, int, int, int]) -> bool:
        """判定領域の周辺にカーソルがあるか（ホバーで見た目が変わる範囲）。"""
        x, y, w, h = rect
        m = self._settings.cursor_margin
        left = client["left"] + x - m
        top = client["top"] + y - m
        cx, cy = get_cursor_pos()
        return left <= cx < left + w + m * 2 and top <= cy < top + h + m * 2

    def _match(self, capture, client: dict, rect: tuple[int, int, int, int],
               template: np.ndarray) -> bool:
        x, y, w, h = rect
        region = {"left": client["left"] + x, "top": client["top"] + y,
                  "width": w, "height": h}
        try:
            image = np.array(capture.grab_region(region))
        except Exception as e:
            print(f"ミッション判定のキャプチャに失敗しました: {e}")
            return self._in_mission
        if image.shape != template.shape:
            return self._in_mission
        score = float(cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)[0][0])
        return score >= self._settings.threshold

import cv2
import numpy as np
import mss
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from win.window import get_client_rect


@dataclass
class ScanResult:
    buff_name: str
    is_active: bool
    icon_rect: tuple  # (x, y, w, h) キャプチャ画像内の相対座標


class Scanner:
    def __init__(self, buffs_dir: Path, match_threshold: float = 0.8, monitor_index: int = 1):
        self.buffs_dir = buffs_dir
        self.match_threshold = match_threshold
        self.monitor_index = monitor_index
        self._templates: dict[str, dict] = {}
        self._capture_offset: tuple[int, int] = (0, 0)  # (left, top) 絶対座標オフセット
        self._window_captured: Optional[bool] = None  # 直前のキャプチャ対象（ログ抑制用）
        self._load_templates()

    def _load_templates(self) -> None:
        # 他スレッドが self._templates を参照中でも空の状態を見せないよう、
        # 新しい dict を構築してからアトミックに差し替える
        templates: dict[str, dict] = {}
        for buff_dir in sorted(self.buffs_dir.iterdir()):
            if not buff_dir.is_dir():
                continue
            active_path = buff_dir / "icon_active.png"
            if not active_path.exists():
                continue
            active_img = cv2.imread(str(active_path), cv2.IMREAD_COLOR)
            if active_img is None:
                print(f"警告: アイコン画像を読み込めません: {active_path}")
                continue

            inactive_path = buff_dir / "icon_inactive.png"
            inactive_img = cv2.imread(str(inactive_path), cv2.IMREAD_COLOR) if inactive_path.exists() else None

            buff_name = buff_dir.name
            templates[buff_name] = {
                "active": active_img,
                "inactive": inactive_img,
            }
            print(f"テンプレート読み込み: {buff_name}")
        self._templates = templates

    def reload_templates(self) -> None:
        self._load_templates()

    def scan(self) -> list[ScanResult]:
        screen = self._capture_screen()
        results = []
        for buff_name, templates in self._templates.items():
            result = self._find_buff(screen, buff_name, templates)
            if result:
                results.append(result)
        return results

    def get_text_region_image(self, icon_rect: tuple, ocr_cfg: dict) -> np.ndarray:
        x, y, w, h = icon_rect
        # モニターの絶対座標オフセットを加算して正しい画面位置を算出
        abs_x = x + w + ocr_cfg.get("offset_x", 2) + self._capture_offset[0]
        abs_y = y + ocr_cfg.get("offset_y", 0) + self._capture_offset[1]
        text_w = ocr_cfg.get("width", 120)
        text_h = int(h * ocr_cfg.get("height_ratio", 1.0))

        region = {"left": abs_x, "top": abs_y, "width": text_w, "height": text_h}
        with mss.MSS() as sct:
            raw = np.array(sct.grab(region))
        return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

    def _capture_screen(self) -> np.ndarray:
        with mss.MSS() as sct:
            region = get_client_rect()
            found = region is not None
            if region is None:
                # ウィンドウが見つからない場合は従来どおり指定モニターを全面キャプチャ
                region = sct.monitors[self.monitor_index]
            if found != self._window_captured:
                if found:
                    print(f"マビノギのウィンドウを検出: {region['left']},{region['top']} "
                          f"{region['width']}x{region['height']}")
                else:
                    print(f"マビノギのウィンドウが見つかりません。モニター {self.monitor_index} を全面スキャンします")
                self._window_captured = found
            self._capture_offset = (region["left"], region["top"])
            raw = np.array(sct.grab(region))
        return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

    def _find_buff(self, screen: np.ndarray, buff_name: str, templates: dict) -> Optional[ScanResult]:
        match = self._match(screen, templates["active"])
        if match:
            return ScanResult(buff_name=buff_name, is_active=True, icon_rect=match)

        if templates["inactive"] is not None:
            match = self._match(screen, templates["inactive"])
            if match:
                return ScanResult(buff_name=buff_name, is_active=False, icon_rect=match)

        return None

    def _match(self, screen: np.ndarray, template: np.ndarray) -> Optional[tuple]:
        if template is None:
            return None
        h, w = template.shape[:2]
        res = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val >= self.match_threshold:
            return (max_loc[0], max_loc[1], w, h)
        return None

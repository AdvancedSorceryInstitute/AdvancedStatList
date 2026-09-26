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
        self._last_screen: Optional[np.ndarray] = None
        # 閾値未満も含む照合結果（スキャン記録モード用）
        self.last_match_info: dict[str, dict] = {}
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
            # 状態判定は同じ位置の画素を両テンプレートと比べるため、サイズが揃っている必要がある
            if inactive_img is not None and inactive_img.shape[:2] != active_img.shape[:2]:
                print(f"警告: 非アクティブアイコンのサイズがアクティブアイコンと異なるため使用しません: {inactive_path}")
                inactive_img = None

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
        self._last_screen = screen
        results = []
        match_info: dict[str, dict] = {}
        for buff_name, templates in self._templates.items():
            info: dict = {}
            result = self._find_buff(screen, buff_name, templates, info)
            if result:
                results.append(result)
            info["found"] = result is not None
            info["is_active"] = result.is_active if result else None
            info["icon_rect"] = result.icon_rect if result else None
            match_info[buff_name] = info
        self.last_match_info = match_info
        return results

    def last_screen(self) -> Optional[np.ndarray]:
        """直前の scan() で撮った画面（BGR）。モニター全体を撮ったときもそのまま返す。"""
        return self._last_screen

    def last_client_capture(self) -> Optional[tuple[np.ndarray, dict]]:
        """直前の scan() で撮った画面（BGR）と、そのクライアント領域の絶対座標。

        ウィンドウが見つからずモニター全体を撮ったときは、クライアント領域と
        対応が取れないので None を返す。
        """
        screen = self._last_screen
        if screen is None or not self._window_captured:
            return None
        h, w = screen.shape[:2]
        left, top = self._capture_offset
        return screen, {"left": left, "top": top, "width": w, "height": h}

    def get_text_region_image(self, icon_rect: tuple, ocr_cfg: dict) -> np.ndarray:
        # 撮り直すと照合時からバフ一覧の行が並び替わって別バフの時間を読むことがあるため、
        # アイコン照合に使った画面そのものから切り出す
        x, y, w, h = icon_rect
        left = x + w + ocr_cfg.get("offset_x", 2)
        top = y + ocr_cfg.get("offset_y", 0)
        text_w = ocr_cfg.get("width", 120)
        text_h = int(h * ocr_cfg.get("height_ratio", 1.0))

        # 後段の OCR で形状を一定に保つため、はみ出した部分は黒で埋めて常に要求サイズで返す
        out = np.zeros((text_h, text_w, 3), dtype=np.uint8)
        screen = self._last_screen
        if screen is None:
            return out
        sh, sw = screen.shape[:2]
        x0, y0 = max(left, 0), max(top, 0)
        x1, y1 = min(left + text_w, sw), min(top + text_h, sh)
        if x0 < x1 and y0 < y1:
            out[y0 - top:y1 - top, x0 - left:x1 - left] = screen[y0:y1, x0:x1]
        return out

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

    def _find_buff(self, screen: np.ndarray, buff_name: str, templates: dict,
                   info: dict) -> Optional[ScanResult]:
        active = templates["active"]
        inactive = templates["inactive"]
        info["active_size"] = (active.shape[1], active.shape[0])
        info["inactive_score"] = None
        info["inactive_loc"] = None
        info["active_diff"] = None
        info["inactive_diff"] = None

        match = self._match(screen, active, info, "active")
        if match is None and inactive is not None:
            match = self._match(screen, inactive, info, "inactive")
        if match is None:
            return None

        # TM_CCOEFF_NORMED は明るさを正規化するため、暗くしただけの非アクティブアイコンも
        # アクティブテンプレートと一致してしまう。状態は画素の差の大きさで判定する
        x, y, w, h = match
        patch = screen[y:y + h, x:x + w]
        active_diff = float(np.mean(cv2.absdiff(patch, active)))
        info["active_diff"] = active_diff
        is_active = True
        if inactive is not None:
            inactive_diff = float(np.mean(cv2.absdiff(patch, inactive)))
            info["inactive_diff"] = inactive_diff
            is_active = active_diff <= inactive_diff
        return ScanResult(buff_name=buff_name, is_active=is_active, icon_rect=match)

    def _match(self, screen: np.ndarray, template: np.ndarray,
               info: Optional[dict] = None, kind: str = "") -> Optional[tuple]:
        if template is None:
            return None
        h, w = template.shape[:2]
        res = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.nonzero(res >= self.match_threshold)
        if len(xs) == 0:
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if info is not None:
                info[f"{kind}_score"] = float(max_val)
                info[f"{kind}_loc"] = (int(max_loc[0]), int(max_loc[1]))
            return None

        # パーティメンバー一覧 (画面左上) にも同じアイコンが出るため、右側にある状態リストの候補を採る
        rightmost = xs == xs.max()
        cand = int(np.argmax(res[ys[rightmost], xs[rightmost]]))
        cx, cy = int(xs[rightmost][cand]), int(ys[rightmost][cand])
        # 同じアイコンの周辺画素もしきい値を超えるため、最も右の画素がアイコンの正しい位置とは限らない
        x0, y0 = max(0, cx - w + 1), max(0, cy - h + 1)
        window = res[y0:cy + h, x0:cx + w]
        _, max_val, _, (wx, wy) = cv2.minMaxLoc(window)
        loc = (x0 + wx, y0 + wy)
        if info is not None:
            info[f"{kind}_score"] = float(max_val)
            info[f"{kind}_loc"] = (int(loc[0]), int(loc[1]))
        return (int(loc[0]), int(loc[1]), w, h)

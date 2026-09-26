import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# 予測より大幅に短く読んだ行を誤読の疑いとして印を付ける
DROP_THRESHOLD = -5.0

# icon 画像の切り抜きでテンプレート矩形の周囲に足す余白
ICON_MARGIN = 16


class ScanLogger:
    """スキャン結果・通知イベントを debug/scan_log/{起動日時}/ に記録する調査用ロガー。

    スキャンスレッドと tick スレッドの両方から呼ばれる。
    記録の失敗で本処理を止めないよう、例外はすべて握りつぶす。
    """

    def __init__(self, base_dir: Path, image_buffs: list[str]):
        self._dir = base_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
        self._image_dir = self._dir / "images"
        self._image_buffs = set(image_buffs)
        self._lock = threading.Lock()
        self._scan_id = 0
        self._prepared = False
        # バフごとの最後に採用した値: (ts, scan_id, value)
        self._last_ok: dict[str, tuple[str, int, int]] = {}

    def next_scan_id(self) -> int:
        with self._lock:
            self._scan_id += 1
            return self._scan_id

    def wants_images(self, buff: str) -> bool:
        return buff in self._image_buffs

    def log_scan(self, scan_id: int, buff: str, match: Optional[dict],
                 ocr: Optional[dict], predicted: Optional[float]) -> None:
        try:
            self._log_scan(scan_id, buff, match or {}, ocr or {}, predicted)
        except Exception as e:
            print(f"スキャン記録: 書き込みできません: {e}")

    def _log_scan(self, scan_id: int, buff: str, match: dict, ocr: dict,
                  predicted: Optional[float]) -> None:
        value = ocr.get("value")
        diff = value - predicted if value is not None and predicted is not None else None
        ts = self._now()
        record = {
            "ts": ts,
            "event": "scan",
            "scan_id": scan_id,
            "buff": buff,
            "active_score": match.get("active_score"),
            "active_loc": match.get("active_loc"),
            "inactive_score": match.get("inactive_score"),
            "inactive_loc": match.get("inactive_loc"),
            "active_diff": match.get("active_diff"),
            "inactive_diff": match.get("inactive_diff"),
            "found": bool(match.get("found", False)),
            "is_active": match.get("is_active"),
            "icon_rect": match.get("icon_rect"),
            "ocr_raw": ocr.get("ocr_raw"),
            "parsed": ocr.get("parsed"),
            "color": ocr.get("color"),
            "value": value,
            "reject": ocr.get("reject"),
            "predicted": predicted,
            "diff": diff,
            "drop": diff is not None and diff < DROP_THRESHOLD,
        }
        with self._lock:
            if value is not None:
                self._last_ok[buff] = (ts, scan_id, value)
            self._write(record)

    def log_warning(self, event: str, buff: str, remaining: float) -> None:
        with self._lock:
            last_ok = self._last_ok.get(buff)
            record = {
                "ts": self._now(),
                "event": event,
                "buff": buff,
                "remaining": remaining,
                "last_ok_ts": last_ok[0] if last_ok else None,
                "last_ok_scan_id": last_ok[1] if last_ok else None,
                "last_ok_value": last_ok[2] if last_ok else None,
            }
            self._write(record)

    def save_images(self, scan_id: int, buff: str, screen: Optional[np.ndarray],
                    match: Optional[dict], region_img: Optional[np.ndarray],
                    binary_img: Optional[np.ndarray]) -> None:
        if not self.wants_images(buff):
            return
        try:
            with self._lock:
                self._prepare()
            prefix = f"{scan_id:05d}_{buff}"
            icon = self._crop_icon(screen, match)
            if icon is not None:
                self._imwrite(self._image_dir / f"{prefix}_icon.png", icon)
            if region_img is not None:
                self._imwrite(self._image_dir / f"{prefix}_region.png", region_img)
            if binary_img is not None:
                self._imwrite(self._image_dir / f"{prefix}_binary.png", binary_img)
        except Exception as e:
            print(f"スキャン記録: 画像を保存できません: {e}")

    @staticmethod
    def _crop_icon(screen: Optional[np.ndarray], match: Optional[dict]) -> Optional[np.ndarray]:
        if screen is None or not match:
            return None
        loc = match.get("active_loc")
        size = match.get("active_size")
        if loc is None or size is None:
            return None
        sh, sw = screen.shape[:2]
        x0 = max(0, loc[0] - ICON_MARGIN)
        y0 = max(0, loc[1] - ICON_MARGIN)
        x1 = min(sw, loc[0] + size[0] + ICON_MARGIN)
        y1 = min(sh, loc[1] + size[1] + ICON_MARGIN)
        if x0 >= x1 or y0 >= y1:
            return None
        return screen[y0:y1, x0:x1]

    @staticmethod
    def _imwrite(path: Path, img: np.ndarray) -> None:
        # cv2.imwrite は日本語パスを扱えないため imencode + tofile を使う
        ok, buf = cv2.imencode(".png", img)
        if ok:
            buf.tofile(str(path))

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def _prepare(self) -> None:
        if not self._prepared:
            self._image_dir.mkdir(parents=True, exist_ok=True)
            self._prepared = True

    def _write(self, record: dict) -> None:
        try:
            self._prepare()
            with open(self._dir / "scan.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"スキャン記録: 書き込みできません: {e}")

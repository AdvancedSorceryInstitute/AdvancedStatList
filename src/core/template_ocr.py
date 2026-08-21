import re
import cv2
import numpy as np
from pathlib import Path
from typing import Optional


class TemplateOCR:
    # テンプレートは4倍スケールのbinaryから切り出されている（3倍拡大表示は保存に含まれない）
    # 入力画像も同じ4倍スケールに揃える
    _SCALE = 4

    _PATTERN_MIN_SEC = re.compile(r"(\d+)\s*分\s*(\d+)\s*秒")
    _PATTERN_SEC = re.compile(r"(\d+)\s*秒")
    _MAX_MINUTES = 99
    _MAX_SECONDS = 59

    # 色判定の定数（残り60秒未満は赤文字で表示されるマビノギの仕様を利用）
    _COLOR_R_MIN = 150          # テキスト画素とみなすRの下限
    _COLOR_WHITE_GB_MIN = 120   # G・Bが両方これ以上なら白文字とみなす
    _COLOR_MIN_TEXT_PIXELS = 20 # 色判定に必要な最小テキスト画素数

    def __init__(self, template_dir: str, threshold: float = 0.7):
        self._threshold = threshold
        self._templates: dict[str, np.ndarray] = {}
        self._template_widths: dict[str, int] = {}
        self.last_raw_text = ""
        self.last_color = "unknown"
        self._load_templates(Path(template_dir))

    def _load_templates(self, template_dir: Path) -> None:
        names = [str(i) for i in range(10)] + ["分", "秒"]
        for name in names:
            path = template_dir / f"{name}.png"
            # cv2.imread は日本語パスを扱えないため np.fromfile + imdecode を使う
            buf = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
            if img is None:
                raise FileNotFoundError(f"テンプレート画像が見つかりません: {path}")
            self._templates[name] = img
            self._template_widths[name] = img.shape[1]

    def read_time(self, image: np.ndarray) -> Optional[int]:
        processed = self._preprocess(image)
        self.last_raw_text = self._recognize(processed)
        value = self._parse_time(self.last_raw_text)
        self.last_color = "unknown"

        # 色との整合性チェック: 60秒未満は赤文字のはず。
        # 白文字なのに60秒未満を読み取った場合は、実際は60秒以上の長いタイマーを
        # 誤読したものとみなして却下する（即時の誤通知を防ぐ）。
        if value is not None and value < 60:
            is_red = self._detect_red(image)
            if is_red is True:
                self.last_color = "red"
            elif is_red is False:
                self.last_color = "white"
                return None
            # is_red is None（判定不能）は過度に弾かず採用する
        return value

    def _detect_red(self, image: np.ndarray) -> Optional[bool]:
        """テキストが赤(True)/白(False)/判定不能(None)を返す。

        赤文字の核は R≈200+ / G・B≈30〜60、白文字は R・G・B≈240 と
        明確に分離できるため、明るいR画素（数字本体）のG・B平均で判別する。
        """
        b, g, r = cv2.split(image)
        text_mask = r > self._COLOR_R_MIN
        if int(text_mask.sum()) < self._COLOR_MIN_TEXT_PIXELS:
            return None
        mean_g = float(g[text_mask].mean())
        mean_b = float(b[text_mask].mean())
        if mean_g >= self._COLOR_WHITE_GB_MIN and mean_b >= self._COLOR_WHITE_GB_MIN:
            return False  # 白
        return True       # 赤

    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        # テンプレートが binary(4倍) → 3倍拡大 = 12倍で保存されているため合わせる
        _, _, r = cv2.split(image)
        enlarged = cv2.resize(r, None, fx=self._SCALE, fy=self._SCALE,
                              interpolation=cv2.INTER_LANCZOS4)
        blurred = cv2.GaussianBlur(enlarged, (3, 3), 0)
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    # 1列以下のギャップのみ文字内ノイズとして埋める（2列以上は文字間ギャップとして保持）
    _MIN_INTER_CHAR_GAP = 2

    def _segment_columns(self, image: np.ndarray) -> list[tuple[int, int]]:
        """列投影で文字セグメント(x_start, x_end)のリストを返す"""
        h = image.shape[0]
        col_proj = np.sum(image > 0, axis=0)
        is_char = col_proj >= max(2, h * 0.05)

        # 短いギャップを埋める（文字内のスリット等を無視）
        filled = is_char.copy()
        i = 0
        while i < len(filled):
            if not filled[i]:
                j = i
                while j < len(filled) and not filled[j]:
                    j += 1
                if 0 < (j - i) < self._MIN_INTER_CHAR_GAP:
                    filled[i:j] = True
                i = j
            else:
                i += 1

        segments: list[tuple[int, int]] = []
        in_seg = False
        seg_start = 0
        for x, has in enumerate(filled):
            if has and not in_seg:
                seg_start = x
                in_seg = True
            elif not has and in_seg:
                segments.append((seg_start, x))
                in_seg = False
        if in_seg:
            segments.append((seg_start, len(filled)))

        return segments

    def _recognize(self, image: np.ndarray) -> str:
        segments = self._segment_columns(image)
        if not segments:
            return ""

        ih, iw = image.shape[:2]

        # 全テンプレートのマッチングマップを事前に計算
        match_maps: dict[str, np.ndarray] = {}
        for char, template in self._templates.items():
            th, tw = template.shape[:2]
            if th > ih or tw > iw:
                continue
            match_maps[char] = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)

        # 各セグメントで最高スコアのテンプレートを選択
        result_chars: list[tuple[int, str]] = []
        for x_start, x_end in segments:
            best_score = -1.0
            best_char = ""
            for char, mmap in match_maps.items():
                tw = self._template_widths[char]
                # テンプレートの「中心」がセグメント内に収まる開始x範囲を検索
                # center = x + tw//2 ∈ [x_start, x_end) → x ∈ [x_start - tw//2, x_end - tw//2)
                x_lo = max(0, x_start - tw // 2)
                x_hi = min(mmap.shape[1], x_end - tw // 2 + 1)
                if x_lo >= x_hi:
                    continue
                region = mmap[:, x_lo:x_hi]
                local_max = float(region.max()) if region.size > 0 else -1.0
                if local_max > best_score:
                    best_score = local_max
                    best_char = char
            if best_score >= self._threshold and best_char:
                result_chars.append((x_start, best_char))

        result_chars.sort(key=lambda c: c[0])
        return "".join(char for _, char in result_chars)

    def _parse_time(self, text: str) -> Optional[int]:
        has_min_sec = False
        for m in self._PATTERN_MIN_SEC.finditer(text):
            has_min_sec = True
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            if minutes <= self._MAX_MINUTES and 0 <= seconds <= self._MAX_SECONDS:
                return minutes * 60 + seconds

        if has_min_sec:
            return None

        # 「分」が含まれているのに X分Y秒 パターンにマッチしない → 分の桁が欠落している可能性
        if "分" in text:
            return None

        m = self._PATTERN_SEC.search(text)
        if m:
            seconds = int(m.group(1))
            if 0 <= seconds <= self._MAX_SECONDS:
                return seconds

        return None

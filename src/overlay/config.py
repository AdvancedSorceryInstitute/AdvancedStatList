"""オーバーレイ設定（overlay.yaml）の読み書き。

スロット矩形はゲームのクライアント領域相対で保持する。
表示するスキルはキャラクターごとに違い、解像度が変わると UI レイアウト自体が
変わるため、設定は「キャラクタープロファイル ID」→「解像度」の2段で分ける。

キャラクター側の切り替えは set_current_profile() で行い、以降のスロット操作は
すべて現在のプロファイルに対して働く。

表示位置はグリッドのセル座標 (col, row) で持つ。位置調整モードで
アイコンを掴んで好きなセルへ移動でき、空きセルを作ることもできる。
"""

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# クイックスロットのアイコン実測サイズ（クライアント 2560x1440 時）。
# 28 だとアイコンのフチが切れるため 29 にしている
DEFAULT_SLOT_SIZE = 29

# 新しく登録したスキルを置くときの折り返し幅。
# 並べ替えは位置調整モードで直接行うため、設定項目にはしていない
NEW_SLOT_COLUMNS = 4

DEFAULT_SCALE = 2.0

# 旧形式（profiles 直下が解像度キー）の判定に使う
_RESOLUTION_KEY = re.compile(r"^\d+x\d+$")


def _clamp_percent(value) -> int:
    """不透明度など 0-100% で持つ値を範囲内に収める。"""
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 100


@dataclass
class Slot:
    """ミラー対象のスロット1つ。矩形はクライアント領域相対、セルは表示グリッド上の位置。"""
    id: str
    label: str
    x: int
    y: int
    w: int = DEFAULT_SLOT_SIZE
    h: int = DEFAULT_SLOT_SIZE
    col: int = 0
    row: int = 0
    enabled: bool = True

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    @property
    def cell(self) -> tuple[int, int]:
        return (self.col, self.row)


@dataclass
class Profile:
    """あるキャラクターの、ある解像度での設定。

    拡大率をここに持たせているのは、キャラクターごとにスキル数が違い、
    置き場所と大きさを別々に決めたいため。
    """
    position: list = field(default_factory=lambda: [40, 300])
    scale: float = DEFAULT_SCALE
    slots: list[Slot] = field(default_factory=list)

    # -------------------------------------------------------- グリッド操作

    def active_slots(self) -> list[Slot]:
        """表示対象（ONになっている）のスロット。

        OFF は一時的な非表示という位置づけなので、セルは占有したままにする。
        グリッド上の位置計算には self.slots（OFF 含む）を使うこと。
        """
        return [s for s in self.slots if s.enabled]

    def grid_size(self) -> tuple[int, int]:
        """使用中のセル範囲（列数, 行数）。OFF のスロットも場所を取り続ける。"""
        if not self.slots:
            return (0, 0)
        return (max(s.col for s in self.slots) + 1,
                max(s.row for s in self.slots) + 1)

    def slot_at(self, col: int, row: int) -> Optional[Slot]:
        """そのセルを使っているスロット。OFF のスロットも場所を空けない。"""
        for s in self.slots:
            if s.col == col and s.row == row:
                return s
        return None

    def find(self, slot_id: str) -> Optional[Slot]:
        for s in self.slots:
            if s.id == slot_id:
                return s
        return None

    def normalize(self) -> None:
        """左上に詰める。途中の空きセルは意図した配置なので詰めない。"""
        if not self.slots:
            return
        dc = min(s.col for s in self.slots)
        dr = min(s.row for s in self.slots)
        if dc == 0 and dr == 0:
            return
        for s in self.slots:
            s.col -= dc
            s.row -= dr

    def place(self, slot_id: str, col: int, row: int) -> bool:
        """スロットを指定セルへ移動する。移動先に別のスロットがあれば入れ替える。"""
        target = self.find(slot_id)
        if target is None:
            return False
        other = self.slot_at(col, row)
        if other is not None and other is not target:
            other.col, other.row = target.col, target.row
        target.col, target.row = col, row
        self.normalize()
        return True

    def next_cell(self, columns: int) -> tuple[int, int]:
        """新しいスロットを置く空きセルを左上から探す。"""
        used = {s.cell for s in self.slots}
        row = 0
        while True:
            for col in range(max(1, columns)):
                if (col, row) not in used:
                    return (col, row)
            row += 1


class OverlayConfig:
    """overlay.yaml の内容を保持する。

    読み書きは GUI スレッドと表示スレッドの双方から起きうるためロックで保護する。
    """

    def __init__(self, path: Path, default_profile_id: str):
        self._path = path
        self._lock = threading.RLock()

        self.enabled: bool = True
        self.anchor: str = "game"        # game | screen
        self.gap: int = 4
        self.background: str = "none"    # none | dark
        self.fps: int = 10
        self.slot_size: int = DEFAULT_SLOT_SIZE
        self.opacity: int = 100          # 表示の不透明度（%）
        self.hover_fade: bool = False    # カーソルが重なったら薄くする
        self.hover_opacity: int = 30     # 薄くしたときの不透明度（%）
        # キャラクタープロファイル ID -> 解像度キー -> 設定
        self.profiles: dict[str, dict[str, Profile]] = {}
        self._current_pid = default_profile_id

        self.load(default_profile_id)

    # ------------------------------------------------------------ 入出力

    def load(self, default_profile_id: str) -> None:
        with self._lock:
            if not self._path.exists():
                return
            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            self.enabled = bool(data.get("enabled", self.enabled))
            self.anchor = data.get("anchor", self.anchor)
            self.gap = int(data.get("gap", self.gap))
            self.background = data.get("background", self.background)
            self.fps = max(1, min(30, int(data.get("fps", self.fps))))
            self.slot_size = int(data.get("slot_size", self.slot_size))
            self.opacity = _clamp_percent(data.get("opacity", self.opacity))
            self.hover_fade = bool(data.get("hover_fade", self.hover_fade))
            self.hover_opacity = _clamp_percent(data.get("hover_opacity",
                                                         self.hover_opacity))

            raw = data.get("profiles") or {}
            if self._is_legacy(raw):
                self._load_legacy(raw, default_profile_id,
                                  float(data.get("scale", DEFAULT_SCALE)))
                return

            self.profiles = {}
            for pid, per_resolution in raw.items():
                self.profiles[str(pid)] = {
                    str(key): self._parse_profile(prof or {})
                    for key, prof in (per_resolution or {}).items()
                }

    @staticmethod
    def _is_legacy(raw: dict) -> bool:
        """旧形式（キャラクター別になる前。profiles 直下が解像度キー）か。"""
        return any(_RESOLUTION_KEY.match(str(key)) for key in raw)

    def _load_legacy(self, raw: dict, default_profile_id: str, scale: float) -> None:
        """旧形式を既定プロファイル配下へ移して保存し直す。

        拡大率も全体設定から解像度ごとの設定へ移す。
        """
        per_resolution = {}
        for key, prof in raw.items():
            profile = self._parse_profile(prof or {})
            profile.scale = scale
            per_resolution[str(key)] = profile
        self.profiles = {default_profile_id: per_resolution}
        self.save()
        print(f"overlay.yaml をプロファイル {default_profile_id} 配下へ移行しました")

    def _parse_profile(self, prof: dict) -> Profile:
        slots = []
        for i, s in enumerate(prof.get("slots") or []):
            rect = s.get("rect") or {}
            cell = s.get("cell") or {}
            slots.append(Slot(
                id=s.get("id", ""),
                label=s.get("label", ""),
                x=int(rect.get("x", 0)),
                y=int(rect.get("y", 0)),
                w=int(rect.get("w", self.slot_size)),
                h=int(rect.get("h", self.slot_size)),
                # セル未設定（旧形式）は登録順を折り返して割り当てる
                col=int(cell.get("col", i % NEW_SLOT_COLUMNS)),
                row=int(cell.get("row", i // NEW_SLOT_COLUMNS)),
                enabled=bool(s.get("enabled", True)),
            ))
        pos = prof.get("position") or {}
        profile = Profile(
            position=[int(pos.get("x", 40)), int(pos.get("y", 300))],
            scale=float(prof.get("scale", DEFAULT_SCALE)),
            slots=slots,
        )
        profile.normalize()
        return profile

    def save(self) -> None:
        with self._lock:
            data = {
                "enabled": self.enabled,
                "anchor": self.anchor,
                "gap": self.gap,
                "background": self.background,
                "fps": self.fps,
                "slot_size": self.slot_size,
                "opacity": self.opacity,
                "hover_fade": self.hover_fade,
                "hover_opacity": self.hover_opacity,
                "profiles": {
                    pid: {
                        key: {
                            "position": {"x": prof.position[0], "y": prof.position[1]},
                            "scale": prof.scale,
                            "slots": [
                                {
                                    "id": s.id,
                                    "label": s.label,
                                    "enabled": s.enabled,
                                    "rect": {"x": s.x, "y": s.y, "w": s.w, "h": s.h},
                                    "cell": {"col": s.col, "row": s.row},
                                }
                                for s in prof.slots
                            ],
                        }
                        for key, prof in per_resolution.items()
                    }
                    for pid, per_resolution in self.profiles.items()
                },
            }
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # ------------------------------------------------------------ プロファイル

    @staticmethod
    def profile_key(client: dict) -> str:
        """クライアント領域から解像度キーを作る。"""
        return f"{client['width']}x{client['height']}"

    @property
    def current_profile_id(self) -> str:
        return self._current_pid

    def set_current_profile(self, profile_id: str) -> None:
        """キャラクターを切り替える。以降のスロット操作はこのプロファイルに働く。"""
        with self._lock:
            self._current_pid = profile_id

    def remove_profile(self, profile_id: str) -> None:
        """キャラクタープロファイルごと設定を捨てる（プロファイル削除時）。"""
        with self._lock:
            if self.profiles.pop(profile_id, None) is None:
                return
        self.save()

    def get_profile(self, key: str, create: bool = False) -> Optional[Profile]:
        """現在のキャラクターの、指定解像度の設定。"""
        with self._lock:
            per_resolution = self.profiles.get(self._current_pid)
            if per_resolution is None:
                if not create:
                    return None
                per_resolution = {}
                self.profiles[self._current_pid] = per_resolution
            prof = per_resolution.get(key)
            if prof is None and create:
                prof = Profile()
                per_resolution[key] = prof
            return prof

    def scale_of(self, key: str) -> float:
        """現在のキャラクターの拡大率。未設定の解像度では既定値。"""
        prof = self.get_profile(key)
        return DEFAULT_SCALE if prof is None else prof.scale

    def set_scale(self, key: str, scale: float) -> None:
        with self._lock:
            self.get_profile(key, create=True).scale = scale
        self.save()

    # ------------------------------------------------------------ スロット操作

    def next_slot_id(self, key: str) -> str:
        prof = self.get_profile(key, create=True)
        used = {s.id for s in prof.slots}
        i = 1
        while f"slot_{i:02d}" in used:
            i += 1
        return f"slot_{i:02d}"

    def add_slot(self, key: str, slot: Slot) -> None:
        with self._lock:
            prof = self.get_profile(key, create=True)
            slot.col, slot.row = prof.next_cell(NEW_SLOT_COLUMNS)
            prof.slots.append(slot)
        self.save()

    def remove_slot(self, key: str, slot_id: str) -> None:
        with self._lock:
            prof = self.get_profile(key)
            if prof is None:
                return
            prof.slots = [s for s in prof.slots if s.id != slot_id]
            prof.normalize()
        self.save()

    def move_slot(self, key: str, slot_id: str, direction: int) -> None:
        """一覧上の並びを入れ替える。direction: -1=前へ, +1=後ろへ

        GUI の一覧を整理するためだけの操作で、オーバーレイ上の位置（セル）は変えない。
        表示位置の変更は位置調整モードで行う。
        """
        with self._lock:
            prof = self.get_profile(key)
            if prof is None:
                return
            ids = [s.id for s in prof.slots]
            if slot_id not in ids:
                return
            i = ids.index(slot_id)
            j = i + direction
            if j < 0 or j >= len(prof.slots):
                return
            prof.slots[i], prof.slots[j] = prof.slots[j], prof.slots[i]
        self.save()

    def set_slot_enabled(self, key: str, slot_id: str, enabled: bool) -> None:
        """スキルごとの表示 ON/OFF。

        一時的な非表示という位置づけなので、セルはそのまま確保しておく。
        ON に戻せば元の場所に戻り、OFF の間も他のスキルには使われない。
        """
        with self._lock:
            prof = self.get_profile(key)
            if prof is None:
                return
            slot = prof.find(slot_id)
            if slot is None:
                return
            slot.enabled = enabled
        self.save()

    def update_slot_rect(self, key: str, slot_id: str, x: int, y: int,
                         w: Optional[int] = None, h: Optional[int] = None) -> bool:
        """登録済みスロットの切り出し位置を変更する。"""
        with self._lock:
            prof = self.get_profile(key)
            if prof is None:
                return False
            slot = prof.find(slot_id)
            if slot is None:
                return False
            slot.x, slot.y = int(x), int(y)
            if w is not None:
                slot.w = int(w)
            if h is not None:
                slot.h = int(h)
        self.save()
        return True

    def place_slot(self, key: str, slot_id: str, col: int, row: int) -> bool:
        """スロットを指定セルへ移動する（位置調整モードから呼ばれる）。"""
        with self._lock:
            prof = self.get_profile(key)
            if prof is None or not prof.place(slot_id, col, row):
                return False
        self.save()
        return True

    def set_position(self, key: str, x: int, y: int) -> None:
        with self._lock:
            self.get_profile(key, create=True).position = [int(x), int(y)]
        self.save()

    def update(self, **kwargs) -> None:
        """表示設定をまとめて更新して保存する。"""
        with self._lock:
            for name, value in kwargs.items():
                if value is not None and hasattr(self, name):
                    setattr(self, name, value)
        self.save()

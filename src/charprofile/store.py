"""キャラクタープロファイルの永続化（profiles.yaml）。

プロファイルが持つのは監視バフの ON/OFF と並び順、そして識別用の指紋。
スキル表示のスロットは overlay.yaml 側がプロファイル ID で引く。

リストの先頭が既定プロファイル。プロファイルを削除したときなどの戻り先に使う。
"""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# 判別の既定値。実機に合わせて profiles.yaml 側で調整できる
DEFAULT_MIN_SCORE = 0.5      # 最高スコアがこれ未満なら判別不能
DEFAULT_MIN_MARGIN = 0.05    # 1位と2位の差がこれ未満なら判別不能
DEFAULT_RETRY_INTERVAL = 5   # ウィンドウ出現後に判別を試す間隔（秒）
# 上記の試行回数。ログイン画面からキャラクターがマップに立つまで待てる長さにする
DEFAULT_RETRY_COUNT = 120    # 5 秒 x 120 = 10 分


@dataclass
class CharacterProfile:
    """キャラクター1人分の設定。"""
    id: str
    name: str
    buff_order: list[str] = field(default_factory=list)
    # 記載の無いバフは buffs/{name}/config.yaml の enabled に従う
    buff_enabled: dict[str, bool] = field(default_factory=dict)


@dataclass
class DetectSettings:
    """判別のパラメータ。識別範囲は全プロファイル共通で、解像度ごとに持つ。"""
    min_score: float = DEFAULT_MIN_SCORE
    min_margin: float = DEFAULT_MIN_MARGIN
    retry_interval: int = DEFAULT_RETRY_INTERVAL
    retry_count: int = DEFAULT_RETRY_COUNT
    regions: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)


class ProfileStore:
    """profiles.yaml の読み書きとプロファイルの操作。

    GUI スレッドと判別処理の双方から触るためロックで保護する。
    """

    def __init__(self, path: Path, profiles_dir: Path, config_path: Optional[Path] = None):
        self._path = path
        self._dir = profiles_dir
        self._lock = threading.RLock()

        self.profiles: list[CharacterProfile] = []
        self.detect = DetectSettings()
        self.current_id: str = ""

        self.load()
        if not self.profiles:
            self._create_initial(config_path)

    # ------------------------------------------------------------ 入出力

    def load(self) -> None:
        with self._lock:
            if not self._path.exists():
                return
            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            det = data.get("detect") or {}
            regions = {}
            for key, r in (det.get("regions") or {}).items():
                r = r or {}
                regions[str(key)] = (int(r.get("x", 0)), int(r.get("y", 0)),
                                     int(r.get("w", 0)), int(r.get("h", 0)))
            self.detect = DetectSettings(
                min_score=float(det.get("min_score", DEFAULT_MIN_SCORE)),
                min_margin=float(det.get("min_margin", DEFAULT_MIN_MARGIN)),
                retry_interval=max(1, int(det.get("retry_interval", DEFAULT_RETRY_INTERVAL))),
                retry_count=max(0, int(det.get("retry_count", DEFAULT_RETRY_COUNT))),
                regions=regions,
            )

            self.profiles = []
            for p in data.get("profiles") or []:
                p = p or {}
                pid = str(p.get("id", "")).strip()
                if not pid:
                    continue
                enabled = {str(k): bool(v) for k, v in (p.get("buff_enabled") or {}).items()}
                self.profiles.append(CharacterProfile(
                    id=pid,
                    name=str(p.get("name", pid)),
                    buff_order=[str(n) for n in (p.get("buff_order") or [])],
                    buff_enabled=enabled,
                ))

            self.current_id = str(data.get("current", ""))
            if self.find(self.current_id) is None:
                self.current_id = self.profiles[0].id if self.profiles else ""

    def save(self) -> None:
        with self._lock:
            data = {
                "current": self.current_id,
                "detect": {
                    "min_score": self.detect.min_score,
                    "min_margin": self.detect.min_margin,
                    "retry_interval": self.detect.retry_interval,
                    "retry_count": self.detect.retry_count,
                    "regions": {
                        key: {"x": r[0], "y": r[1], "w": r[2], "h": r[3]}
                        for key, r in self.detect.regions.items()
                    },
                },
                "profiles": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "buff_order": p.buff_order,
                        "buff_enabled": p.buff_enabled,
                    }
                    for p in self.profiles
                ],
            }
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def _create_initial(self, config_path: Optional[Path]) -> None:
        """初回起動時に、既存の設定を取り込んだプロファイルを1つ作る。

        config.yaml の buff_order は profiles.yaml へ移し、元からは取り除く
        （二重管理になると、どちらが効いているのか分からなくなるため）。
        """
        order: list[str] = []
        if config_path is not None and config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            order = [str(n) for n in (cfg.pop("buff_order", None) or [])]
            if order:
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

        self.profiles = [CharacterProfile(id="profile_01", name="プロファイル1",
                                          buff_order=order)]
        self.current_id = "profile_01"
        self.save()

    # ------------------------------------------------------------ 参照

    def find(self, profile_id: str) -> Optional[CharacterProfile]:
        for p in self.profiles:
            if p.id == profile_id:
                return p
        return None

    def default_profile(self) -> CharacterProfile:
        """判別できなかったときに使うプロファイル（リストの先頭）。"""
        return self.profiles[0]

    def current(self) -> CharacterProfile:
        return self.find(self.current_id) or self.default_profile()

    def set_current(self, profile_id: str) -> None:
        with self._lock:
            if self.find(profile_id) is None:
                return
            self.current_id = profile_id
        self.save()

    # ------------------------------------------------------------ 操作

    def _next_id(self) -> str:
        used = {p.id for p in self.profiles}
        i = 1
        while f"profile_{i:02d}" in used:
            i += 1
        return f"profile_{i:02d}"

    def add(self, name: str) -> CharacterProfile:
        with self._lock:
            profile = CharacterProfile(id=self._next_id(), name=name)
            self.profiles.append(profile)
        self.save()
        return profile

    def duplicate(self, profile_id: str, name: str) -> Optional[CharacterProfile]:
        """バフ設定を引き継いだプロファイルを作る。指紋は引き継がない。"""
        with self._lock:
            src = self.find(profile_id)
            if src is None:
                return None
            profile = CharacterProfile(
                id=self._next_id(),
                name=name,
                buff_order=list(src.buff_order),
                buff_enabled=dict(src.buff_enabled),
            )
            self.profiles.append(profile)
        self.save()
        return profile

    def remove(self, profile_id: str) -> bool:
        """プロファイルとその指紋画像を削除する。最後の1つは消せない。"""
        with self._lock:
            if len(self.profiles) <= 1:
                return False
            profile = self.find(profile_id)
            if profile is None:
                return False
            self.profiles.remove(profile)
            if self.current_id == profile_id:
                self.current_id = self.profiles[0].id
        for path in self.fingerprint_dir(profile_id).glob("fp_*.png"):
            path.unlink(missing_ok=True)
        try:
            self.fingerprint_dir(profile_id).rmdir()
        except OSError:
            pass   # 想定外のファイルが残っている場合はフォルダを残す
        self.save()
        return True

    def rename(self, profile_id: str, name: str) -> None:
        with self._lock:
            profile = self.find(profile_id)
            if profile is None or not name:
                return
            profile.name = name
        self.save()

    def move(self, profile_id: str, direction: int) -> None:
        """並べ替える。direction: -1=上へ, +1=下へ。先頭が既定プロファイルになる。"""
        with self._lock:
            profile = self.find(profile_id)
            if profile is None:
                return
            i = self.profiles.index(profile)
            j = i + direction
            if j < 0 or j >= len(self.profiles):
                return
            self.profiles[i], self.profiles[j] = self.profiles[j], self.profiles[i]
        self.save()

    # ------------------------------------------------------------ バフ設定

    def set_buff_order(self, profile_id: str, order: list[str]) -> None:
        with self._lock:
            profile = self.find(profile_id)
            if profile is None:
                return
            profile.buff_order = list(order)
        self.save()

    def set_buff_enabled(self, profile_id: str, name: str, enabled: bool) -> None:
        with self._lock:
            profile = self.find(profile_id)
            if profile is None:
                return
            profile.buff_enabled[name] = enabled
        self.save()

    # ------------------------------------------------------------ 指紋

    def fingerprint_dir(self, profile_id: str) -> Path:
        return self._dir / profile_id

    def fingerprint_path(self, profile_id: str, key: str) -> Path:
        """解像度ごとの指紋画像のパス。"""
        return self.fingerprint_dir(profile_id) / f"fp_{key}.png"

    def has_fingerprint(self, profile_id: str, key: str) -> bool:
        return self.fingerprint_path(profile_id, key).exists()

    def region(self, key: str) -> Optional[tuple[int, int, int, int]]:
        return self.detect.regions.get(key)

    def set_region(self, key: str, rect: tuple[int, int, int, int]) -> None:
        """識別範囲を設定する。

        サイズが変わると既存の指紋は比較できなくなるため、
        呼び出し側で clear_fingerprints() と取り直しを促すこと。
        """
        with self._lock:
            self.detect.regions[key] = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
        self.save()

    def clear_fingerprints(self, key: str) -> None:
        """指定解像度の指紋をすべて破棄する（識別範囲を変えたとき）。"""
        for p in self.profiles:
            self.fingerprint_path(p.id, key).unlink(missing_ok=True)

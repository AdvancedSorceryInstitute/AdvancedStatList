import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import yaml

from .scanner import Scanner
from .ocr import OCRReader
from .timer_manager import TimerManager
from notify.notifier import Notifier
from charprofile.store import CharacterProfile, ProfileStore

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "config.yaml"
CONFIG_SAMPLE_PATH = CONFIG_DIR / "config.sample.yaml"
BUFFS_DIR = BASE_DIR / "buffs"
DEBUG_DIR = BASE_DIR / "debug" / "auto_debug"
REGION_DEBUG_DIR = BASE_DIR / "debug" / "region"

# トゥアン延長支援: 音楽バフはトゥアンの歌が掛かった状態で切れると延長される
TUAN_BUFF_NAME = "SongOfTuan"
TUAN_BANNER_NAME = "banner_tuan.png"


class ScanController:
    def __init__(self, store: ProfileStore):
        self._lock = threading.Lock()
        self._scan_active = threading.Event()
        self._scan_now = threading.Event()
        self._thread_running = False
        self._thread: Optional[threading.Thread] = None

        # 監視するバフとその並び順はプロファイル（キャラクター）ごとに持つ
        self._store = store
        self._profile: CharacterProfile = store.current()

        self._config = self._load_config()
        self._build_components()

    def _load_config(self) -> dict:
        # config.yaml は環境ごとの値が入るため配布・git 管理をしない。
        # 無ければサンプルを既定値としてコピーする（配布版は build.py が同じことをする）
        if not CONFIG_PATH.exists() and CONFIG_SAMPLE_PATH.exists():
            shutil.copy2(CONFIG_SAMPLE_PATH, CONFIG_PATH)
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_buff_configs(self) -> dict[str, dict]:
        configs = {}
        for buff_dir in BUFFS_DIR.iterdir():
            if not buff_dir.is_dir():
                continue
            config_path = buff_dir / "config.yaml"
            if not config_path.exists():
                continue
            with open(config_path, encoding="utf-8") as f:
                configs[buff_dir.name] = yaml.safe_load(f) or {}
        return configs

    def _build_components(self) -> None:
        cfg = self._config
        self._scan_interval: int = cfg.get("scan_interval", 15)
        self._default_threshold: int = cfg.get("warning_threshold", 30)
        self._ocr_cfg: dict = cfg.get("ocr_region", {})
        self._debug_save_auto: bool = cfg.get("debug_save_auto", False)

        self._tuan_support_enabled: bool = cfg.get("tuan_support_enabled", True)
        self._tuan_check_threshold: int = cfg.get("tuan_check_threshold", 10)

        volume: int = cfg.get("volume", 100)
        banner_y_offset: int = cfg.get("banner_y_offset", 80)
        self.notifier = Notifier(buffs_dir=BUFFS_DIR, volume=volume, banner_y_offset=banner_y_offset)
        self.timer_manager = TimerManager(on_warning=self.notifier.notify, on_tuan_check=self._on_tuan_check)

        monitor_index: int = cfg.get("monitor_index", 1)
        match_threshold: float = cfg.get("match_threshold", 0.8)
        self.scanner = Scanner(BUFFS_DIR, match_threshold=match_threshold, monitor_index=monitor_index)

        if getattr(sys, 'frozen', False):
            template_dir = str(Path(sys._MEIPASS) / "templates")
        else:
            template_dir = cfg.get("template_dir")
            if template_dir:
                template_dir = str(BASE_DIR / template_dir)
        self.ocr_reader = OCRReader(
            template_dir=template_dir,
            template_threshold=cfg.get("template_threshold", 0.7),
        )

        self.buff_configs: dict[str, dict] = self._load_buff_configs()
        self.timer_manager.start()
        print(f"起動完了。スキャン間隔: {self._scan_interval}秒 / 警告閾値(デフォルト): {self._default_threshold}秒")

    def start(self) -> None:
        """スキャンを開始（または一時停止から再開）する。"""
        if not self._thread_running or self._thread is None or not self._thread.is_alive():
            self._thread_running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        self._scan_active.set()

    def stop(self) -> None:
        """スキャンを一時停止する（スレッドは維持し、再開可能）。"""
        self._scan_active.clear()
        self.timer_manager.clear_all()

    def trigger_scan(self) -> None:
        """次のスキャンを即時実行させる。スキャンが停止中の場合は何もしない。"""
        if self.is_running():
            self._scan_now.set()

    def is_running(self) -> bool:
        return self._scan_active.is_set() and self._thread_running

    def shutdown(self) -> None:
        """完全に終了する。"""
        self._thread_running = False
        self._scan_active.set()  # wait() ブロックを解除してスレッドを終わらせる
        self.timer_manager.stop()

    def _loop(self) -> None:
        while self._thread_running:
            self._scan_active.wait()
            if not self._thread_running:
                break
            self._scan_now.clear()
            try:
                self._do_scan()
            except Exception as e:
                print(f"スキャンエラー: {e}")
            deadline = time.time() + self._scan_interval
            while time.time() < deadline and self._thread_running:
                if not self._scan_active.is_set() or self._scan_now.is_set():
                    break
                time.sleep(0.3)

    def _do_scan(self) -> None:
        results = self.scanner.scan()
        for result in results:
            buff_cfg = self.buff_configs.get(result.buff_name, {})
            if not self.is_buff_enabled(result.buff_name):
                continue
            # トゥアンの歌は延長支援の判定用に残り時間だけタイマー管理し、通知はしない
            is_tuan = result.buff_name == TUAN_BUFF_NAME
            threshold = None if is_tuan else buff_cfg.get("warning_threshold", self._default_threshold)

            if not result.is_active:
                print(f"[{result.buff_name}] 切れています")
                self.timer_manager.deactivate(result.buff_name)
                continue

            region_img = self.scanner.get_text_region_image(result.icon_rect, self._ocr_cfg)
            if self._ocr_cfg.get("debug_save_region", False):
                self._save_ocr_region(result.buff_name, region_img)
            remaining = self.ocr_reader.read_time(region_img)
            raw = getattr(self.ocr_reader, "last_raw_text", "")
            color = getattr(self.ocr_reader, "last_color", "?")

            if remaining is not None:
                print(f"[{result.buff_name}] 残り {remaining} 秒  (OCR: {repr(raw)}, 色: {color})")
                is_music = buff_cfg.get("type") == "music_buff"
                tuan_th = self._tuan_check_threshold if (is_music and self._tuan_support_enabled) else None
                self.timer_manager.update(result.buff_name, float(remaining), threshold, tuan_threshold=tuan_th)
            else:
                print(f"[{result.buff_name}] 読み取れず  (OCR: {repr(raw)})")
                if self._debug_save_auto:
                    self._save_debug_image(result.buff_name, region_img, raw)

    def _on_tuan_check(self, name: str, remaining: float) -> None:
        """音楽バフが残り閾値秒に達したときの トゥアンの歌 チェック（tick スレッドから呼ばれる）。"""
        if not self._tuan_support_enabled:
            return
        tuan = self.timer_manager.get_all().get(TUAN_BUFF_NAME)
        # 延長はバフが切れる瞬間に判定されるため、トゥアンが音楽バフより長く残っている必要がある
        if tuan is not None and tuan.active and tuan.remaining > remaining:
            print(f"[{name}] トゥアンの歌あり（残り {int(tuan.remaining)} 秒）。延長見込み")
            return
        print(f"[{name}] トゥアンの歌なし。再通知します")
        self.notifier.notify(name, remaining, banner_name=TUAN_BANNER_NAME)

    # ------------------------------------------------------------ プロファイル

    def apply_profile(self, profile: CharacterProfile) -> None:
        """監視対象を切り替える。前のキャラクターのタイマーは持ち越さない。"""
        with self._lock:
            self._profile = profile
        self.timer_manager.clear_all()
        self.trigger_scan()

    def is_buff_enabled(self, name: str) -> bool:
        """このバフを監視するか。

        プロファイルに記載が無いバフは buffs/{name}/config.yaml の enabled に従う。
        新しく追加したバフが、どのプロファイルでも自然に有効になる。
        """
        override = self._profile.buff_enabled.get(name)
        if override is not None:
            return override
        return self.buff_configs.get(name, {}).get("enabled", True)

    def set_buff_enabled(self, name: str, enabled: bool) -> None:
        """現在のプロファイルに記録する（バフ定義側は既定値として触らない）。"""
        self._store.set_buff_enabled(self._profile.id, name, enabled)
        if not enabled:
            self.timer_manager.deactivate(name)

    def get_timers(self):
        return self.timer_manager.get_all()

    def get_buff_order(self) -> list[str]:
        """表示順リストを返す。未登録バフはアルファベット順で末尾に補完する。"""
        order: list[str] = list(self._profile.buff_order)
        known = set(order)
        for name in sorted(self.buff_configs.keys()):
            if name not in known:
                order.append(name)
        return [n for n in order if n in self.buff_configs and n != TUAN_BUFF_NAME]

    def set_buff_order(self, order: list[str]) -> None:
        self._store.set_buff_order(self._profile.id, order)

    def reload_buffs(self) -> None:
        self.scanner.reload_templates()
        with self._lock:
            self.buff_configs = self._load_buff_configs()

    def update_settings(self, scan_interval: Optional[int] = None, volume: Optional[int] = None, banner_y_offset: Optional[int] = None, tuan_support_enabled: Optional[bool] = None) -> None:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if scan_interval is not None:
            self._scan_interval = scan_interval
            data["scan_interval"] = scan_interval
        if volume is not None:
            self.notifier._volume = max(0, min(100, volume))
            data["volume"] = volume
        if banner_y_offset is not None:
            self.notifier.banner_y_offset = banner_y_offset
            data["banner_y_offset"] = banner_y_offset
        if tuan_support_enabled is not None:
            self._tuan_support_enabled = tuan_support_enabled
            data["tuan_support_enabled"] = tuan_support_enabled
            # 既存タイマーへ即時反映（次スキャンを待たずにON/OFFを効かせる）
            new_th = self._tuan_check_threshold if tuan_support_enabled else None
            for name, cfg in self.buff_configs.items():
                if cfg.get("type") == "music_buff":
                    self.timer_manager.set_tuan_threshold(name, new_th)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    def _save_ocr_region(self, buff_name: str, region_img) -> None:
        try:
            REGION_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%H%M%S")
            cv2.imwrite(str(REGION_DEBUG_DIR / f"{ts}_{buff_name}.png"), region_img)
        except Exception:
            pass

    def _save_debug_image(self, buff_name: str, region_img, raw_text: str) -> None:
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%H%M%S")
            binary = self.ocr_reader._template_ocr._preprocess(region_img)
            filename = f"{ts}_{buff_name}_{raw_text[:20].replace(' ', '_')}.png"
            filename = "".join(c for c in filename if c.isalnum() or c in "._-")
            cv2.imwrite(str(DEBUG_DIR / filename), binary)
        except Exception:
            pass

import time
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class BuffTimer:
    name: str
    remaining: float
    warning_threshold: Optional[int]  # None なら通知しない（残り時間の管理のみ行う）
    warned: bool = False
    active: bool = True
    last_updated: float = field(default_factory=time.time)
    tuan_threshold: Optional[int] = None  # トゥアン延長支援のチェック秒数。None なら対象外
    tuan_warned: bool = False


class TimerManager:
    def __init__(
        self,
        on_warning: Callable[[str, float], None],
        tick_interval: float = 0.5,
        on_tuan_check: Optional[Callable[[str, float], None]] = None,
    ):
        self._timers: dict[str, BuffTimer] = {}
        self._lock = threading.Lock()
        self._on_warning = on_warning
        self._on_tuan_check = on_tuan_check
        self._tick_interval = tick_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def update(self, buff_name: str, remaining: float, warning_threshold: Optional[int],
               tuan_threshold: Optional[int] = None) -> None:
        with self._lock:
            timer = self._timers.get(buff_name)
            if timer is None:
                self._timers[buff_name] = BuffTimer(
                    name=buff_name,
                    remaining=remaining,
                    warning_threshold=warning_threshold,
                    tuan_threshold=tuan_threshold,
                )
            else:
                # バフが更新されて残り時間が閾値を超えた場合、通知フラグをリセット
                if timer.warning_threshold is not None and remaining > timer.warning_threshold:
                    timer.warned = False
                # 毎回上書きすることで設定ON/OFFの切替を次スキャンで反映する
                timer.tuan_threshold = tuan_threshold
                if tuan_threshold is None or remaining > tuan_threshold:
                    timer.tuan_warned = False
                timer.remaining = remaining
                timer.active = True
                timer.last_updated = time.time()

    def set_tuan_threshold(self, buff_name: str, threshold: Optional[int]) -> None:
        """既存タイマーのトゥアンチェック閾値を即時変更する（設定変更の反映用）。"""
        with self._lock:
            timer = self._timers.get(buff_name)
            if timer is not None:
                timer.tuan_threshold = threshold
                if threshold is None:
                    timer.tuan_warned = False

    def deactivate(self, buff_name: str) -> None:
        with self._lock:
            if buff_name in self._timers:
                self._timers[buff_name].active = False
                self._timers[buff_name].warned = False
                self._timers[buff_name].tuan_warned = False

    def get_all(self) -> dict[str, BuffTimer]:
        with self._lock:
            return {k: v for k, v in self._timers.items()}

    def clear_all(self) -> None:
        with self._lock:
            self._timers.clear()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _tick_loop(self) -> None:
        last = time.time()
        while self._running:
            time.sleep(self._tick_interval)
            now = time.time()
            elapsed = now - last
            last = now
            self._tick(elapsed)

    def _tick(self, elapsed: float) -> None:
        warnings = []
        tuan_checks = []
        with self._lock:
            for timer in self._timers.values():
                if not timer.active:
                    continue
                timer.remaining -= elapsed
                if timer.remaining <= 0:
                    timer.remaining = 0.0
                    timer.active = False
                    continue
                if (
                    timer.warning_threshold is not None
                    and not timer.warned
                    and timer.remaining <= timer.warning_threshold
                ):
                    timer.warned = True
                    warnings.append((timer.name, timer.remaining))
                if (
                    timer.tuan_threshold is not None
                    and not timer.tuan_warned
                    and timer.remaining <= timer.tuan_threshold
                ):
                    timer.tuan_warned = True
                    tuan_checks.append((timer.name, timer.remaining))

        for name, remaining in warnings:
            self._on_warning(name, remaining)
        if self._on_tuan_check is not None:
            for name, remaining in tuan_checks:
                self._on_tuan_check(name, remaining)

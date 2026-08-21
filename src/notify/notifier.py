import ctypes
import itertools
import queue
import threading
from pathlib import Path
from typing import Optional

from PIL import Image

from win import layered
from win.window import get_window_rect

# バナーのウィンドウクラス名用。スレッド ID は OS が使い回すため、
# 過去のバナーと名前が衝突して RegisterClassExW が
# ERROR_CLASS_ALREADY_EXISTS で失敗しないよう単調増加の番号を使う。
_banner_class_serial = itertools.count()


class Notifier:
    POPUP_DURATION = 5000  # ms

    def __init__(self, buffs_dir: Optional[Path] = None, volume: int = 100, banner_y_offset: int = 80):
        self._buffs_dir = buffs_dir
        self._volume: int = max(0, min(100, volume))
        self.banner_y_offset: int = banner_y_offset
        self._queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker_loop, daemon=True).start()

    def notify(self, buff_name: str, remaining: float, banner_name: str = "banner.png") -> None:
        self._queue.put((buff_name, remaining, banner_name))

    def _worker_loop(self) -> None:
        while True:
            buff_name, remaining, banner_name = self._queue.get()
            try:
                sound_path = self._find_sound(buff_name)
                banner_path = self._find_banner(buff_name, banner_name)

                # 音とバナーを同時に開始し、両方の完了を待つ
                threads = []
                if sound_path:
                    threads.append(threading.Thread(target=self._mp3_main, args=(sound_path,)))
                if banner_path:
                    threads.append(threading.Thread(target=self._banner_thread, args=(banner_path,)))

                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            finally:
                self._queue.task_done()

    def _find_sound(self, buff_name: str) -> Optional[Path]:
        if self._buffs_dir is None:
            return None
        buff_dir = self._buffs_dir / buff_name
        for path in buff_dir.glob("sound.*"):
            return path
        return None

    def _find_banner(self, buff_name: str, banner_name: str = "banner.png") -> Optional[Path]:
        if self._buffs_dir is None:
            return None
        path = self._buffs_dir / buff_name / banner_name
        if not path.exists():
            # 指定バナーが無ければ通常バナーにフォールバック
            path = self._buffs_dir / buff_name / "banner.png"
        return path if path.exists() else None

    def _mp3_main(self, path: Path) -> None:
        winmm = ctypes.windll.winmm
        alias = "notifier_mp3"
        winmm.mciSendStringW(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
        winmm.mciSendStringW(f"setaudio {alias} volume to {self._volume * 10}", None, 0, None)
        winmm.mciSendStringW(f"play {alias} wait", None, 0, None)
        winmm.mciSendStringW(f"close {alias}", None, 0, None)

    def _banner_thread(self, banner_path: Path) -> None:
        """Pure Win32 API でバナーウィンドウを作成・表示する。tkinter と完全に独立。"""
        try:
            img = Image.open(banner_path).convert("RGBA")
            bw, bh = img.size

            game_rect = get_window_rect()
            if game_rect:
                gx, gy, gw, _ = game_rect
                x = gx + (gw - bw) // 2
                y = gy + self.banner_y_offset
            else:
                screen_w = ctypes.windll.user32.GetSystemMetrics(0)
                x = (screen_w - bw) // 2
                y = self.banner_y_offset

            user32 = layered.user32
            class_name = f"ASLBanner{next(_banner_class_serial)}"

            def wnd_proc(hwnd, msg, wparam, lparam):
                if msg == layered.WM_TIMER:
                    user32.KillTimer(hwnd, wparam)
                    user32.DestroyWindow(hwnd)
                elif msg == layered.WM_DESTROY:
                    user32.PostQuitMessage(0)
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            # コールバックへの参照を保持（GCで回収されるとクラッシュする）
            proc_cb = layered.WNDPROC(wnd_proc)

            hInstance = layered.register_class(class_name, proc_cb)
            if hInstance is None:
                return

            hwnd = layered.create_window(
                class_name, hInstance, x, y, bw, bh,
                layered.WS_EX_LAYERED | layered.WS_EX_TRANSPARENT
                | layered.WS_EX_NOACTIVATE | layered.WS_EX_TOPMOST,
            )
            if not hwnd:
                user32.UnregisterClassW(class_name, hInstance)
                return

            layered.update_layered(hwnd, img, x, y)
            user32.ShowWindow(hwnd, layered.SW_SHOWNOACTIVATE)
            user32.SetTimer(hwnd, 1, self.POPUP_DURATION, None)

            msg = layered.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            user32.UnregisterClassW(class_name, hInstance)
        except Exception as e:
            print(f"バナー表示エラー: {e}")

"""常駐するクリック透過オーバーレイウィンドウ。

Win32 ウィンドウは作成したスレッドでメッセージを処理する必要があるため、
専用スレッドを1本立ててそこでウィンドウ作成とメッセージループを行う。
描画・表示切替もすべてこのスレッド（WM_TIMER のコールバック）から呼ぶこと。
"""

import ctypes
import itertools
import threading
from typing import Callable, Optional

from PIL import Image

from win import layered

# ウィンドウクラス名の衝突を避けるための通し番号
_class_serial = itertools.count()

EX_STYLE_BASE = (
    layered.WS_EX_LAYERED
    | layered.WS_EX_NOACTIVATE
    | layered.WS_EX_TOPMOST
    | layered.WS_EX_TOOLWINDOW
)


class OverlayWindow:
    """on_tick を一定間隔で呼び、その中から draw / hide を行うためのウィンドウ。"""

    TIMER_ID = 1

    def __init__(self, on_tick: Callable[[], None], interval_ms: int = 100,
                 on_moved: Optional[Callable[[int, int], None]] = None,
                 on_shutdown: Optional[Callable[[], None]] = None,
                 on_hittest: Optional[Callable[[int, int], bool]] = None,
                 on_click: Optional[Callable[[int, int], None]] = None,
                 on_mouse_move: Optional[Callable[[int, int], None]] = None):
        self._on_tick = on_tick
        self._on_moved = on_moved
        self._on_shutdown = on_shutdown
        # クリック透過を外している間（位置調整モード）だけ使う
        self._on_hittest = on_hittest
        self._on_click = on_click
        self._on_mouse_move = on_mouse_move
        self._interval_ms = interval_ms
        self._applied_interval: Optional[int] = None

        self._thread: Optional[threading.Thread] = None
        self._hwnd: int = 0
        self._ready = threading.Event()
        self._visible = False
        self._click_through = True
        self._proc_cb = None  # WNDPROC の参照保持（GC されるとクラッシュする）

    # ------------------------------------------------------------ 起動・停止

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(3.0)

    def stop(self) -> None:
        if self._hwnd:
            layered.user32.PostMessageW(self._hwnd, layered.WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def alive(self) -> bool:
        return bool(self._hwnd)

    def set_interval(self, interval_ms: int) -> None:
        """更新間隔を変更する。次の tick で反映される。"""
        self._interval_ms = max(16, interval_ms)

    # ------------------------------------------------------------ 描画（tick 内から）

    def draw(self, img: Image.Image, x: Optional[int] = None,
             y: Optional[int] = None, alpha: int = 255) -> None:
        """画像を描画する。x, y を省略すると現在位置を維持する。

        alpha は全体にかける不透明度（0-255）。
        """
        if not self._hwnd:
            return
        layered.update_layered(self._hwnd, img, x, y, alpha)
        if not self._visible:
            layered.user32.ShowWindow(self._hwnd, layered.SW_SHOWNOACTIVATE)
            self._visible = True
        layered.bring_to_top(self._hwnd)

    def hide(self) -> None:
        if self._hwnd and self._visible:
            layered.user32.ShowWindow(self._hwnd, layered.SW_HIDE)
            self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible

    def set_click_through(self, enabled: bool) -> None:
        if not self._hwnd or enabled == self._click_through:
            return
        layered.set_click_through(self._hwnd, enabled)
        self._click_through = enabled

    # ------------------------------------------------------------ ウィンドウスレッド

    def _run(self) -> None:
        u = layered.user32
        class_name = f"ASLOverlay{next(_class_serial)}"

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == layered.WM_TIMER:
                self._tick()
            elif msg == layered.WM_NCHITTEST and not self._click_through:
                # 掴みしろの上ならタイトルバー扱いにして OS にドラッグ移動させ、
                # それ以外はクライアント扱いにしてクリックを受け取る
                wx, wy = layered.get_window_pos(hwnd)
                x = layered.signed_low(lparam) - wx
                y = layered.signed_high(lparam) - wy
                if self._on_hittest is None or self._on_hittest(x, y):
                    return layered.HTCAPTION
                return layered.HTCLIENT
            elif msg == layered.WM_LBUTTONDOWN:
                if self._on_click is not None:
                    self._on_click(layered.signed_low(lparam), layered.signed_high(lparam))
            elif msg == layered.WM_MOUSEMOVE:
                if self._on_mouse_move is not None:
                    self._on_mouse_move(layered.signed_low(lparam), layered.signed_high(lparam))
            elif msg == layered.WM_EXITSIZEMOVE:
                if self._on_moved is not None:
                    x, y = layered.get_window_pos(hwnd)
                    self._on_moved(x, y)
            elif msg == layered.WM_DESTROY:
                u.PostQuitMessage(0)
            return u.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc_cb = layered.WNDPROC(wnd_proc)
        hInstance = layered.register_class(class_name, self._proc_cb)
        if hInstance is None:
            print("オーバーレイ: ウィンドウクラスの登録に失敗しました")
            self._ready.set()
            return

        hwnd = layered.create_window(
            class_name, hInstance, 0, 0, 1, 1,
            EX_STYLE_BASE | layered.WS_EX_TRANSPARENT,
        )
        if not hwnd:
            u.UnregisterClassW(class_name, hInstance)
            print("オーバーレイ: ウィンドウの作成に失敗しました")
            self._ready.set()
            return

        self._hwnd = hwnd
        self._click_through = True
        self._apply_interval()
        self._ready.set()

        msg = layered.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

        self._hwnd = 0
        self._visible = False
        u.UnregisterClassW(class_name, hInstance)

        # mss などスレッドに紐づくリソースはこのスレッドで解放する
        if self._on_shutdown is not None:
            try:
                self._on_shutdown()
            except Exception as e:
                print(f"オーバーレイ終了処理エラー: {e}")

    def _tick(self) -> None:
        if self._applied_interval != self._interval_ms:
            self._apply_interval()
        try:
            self._on_tick()
        except Exception as e:
            print(f"オーバーレイ更新エラー: {e}")

    def _apply_interval(self) -> None:
        # 同じタイマー ID で SetTimer し直すと間隔だけが変更される
        layered.user32.SetTimer(self._hwnd, self.TIMER_ID, self._interval_ms, None)
        self._applied_interval = self._interval_ms

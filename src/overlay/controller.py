"""オーバーレイの制御。

更新ループ（キャプチャ→合成→描画）と、マビノギがアクティブでないときの
自動オフを担当する。すべての描画はオーバーレイ専用スレッドの tick と
マウスメッセージのコールバック内で行う。

位置調整モードでは外周の掴みしろをドラッグして全体を移動でき、
アイコンをクリックで持ち上げ、もう一度クリックしてグリッドの好きなセルへ置ける。
"""

import re
from pathlib import Path
from typing import Optional

from PIL import Image

from win.layered import get_cursor_pos
from win.window import find_hwnd, get_client_rect, is_foreground
from win.window_capture import capture_client

from .capture import SlotCapture, bounding_rect
from .config import OverlayConfig, Profile, Slot
from .layout import FRAME, GridMetrics, compose, compose_adjust
from .layered_window import OverlayWindow

# キャラクター別になる前のプレビュー画像名（例 2560x1440_slot_02.png）
_LEGACY_PREVIEW = re.compile(r"^\d+x\d+_")


class OverlayController:
    def __init__(self, config_path: Path, slots_dir: Path, default_profile_id: str):
        self.config = OverlayConfig(config_path, default_profile_id)
        self.slots_dir = slots_dir
        self._migrate_previews(default_profile_id)

        self._window = OverlayWindow(
            self._tick,
            interval_ms=self._interval_ms(),
            on_moved=self._on_moved,
            on_shutdown=self._release_capture,
            on_hittest=self._on_hittest,
            on_click=self._on_click,
            on_mouse_move=self._on_mouse_move,
        )
        self._capture: Optional[SlotCapture] = None

        self._adjust_mode = False
        self._adjust_placed = False          # 調整モードに入った直後に一度だけ位置を指定する
        self._adjust_images: dict[str, Image.Image] = {}
        self._held_id: Optional[str] = None  # 持ち上げ中のスロット
        self._cursor: Optional[tuple[int, int]] = None
        self._hover_cell: Optional[tuple[int, int]] = None
        self._metrics: Optional[GridMetrics] = None

        self._suspended = False              # ピッカー表示中など、一時的に隠す
        self._last_key: Optional[bytes] = None

        # GUI 表示用。state は色分け、detail は補足説明に使う
        # disabled | waiting | visible | adjusting
        self.state: str = "waiting" if self.config.enabled else "disabled"
        self.detail: str = ""
        self.overlap_warning: bool = False

    # ------------------------------------------------------------ 起動・停止

    def start(self) -> None:
        self._window.start()

    def stop(self) -> None:
        # キャプチャの解放はウィンドウスレッド側（_release_capture）で行う。
        # mss はスレッドセーフではなく、生成したスレッド以外から close すると失敗する
        self._window.stop()

    def _migrate_previews(self, default_profile_id: str) -> None:
        """プレビュー画像の名前をキャラクター別（旧: 解像度別）へ移す。

        overlay.yaml の移行と対になる処理。旧名は先頭が解像度なので見分けられる。
        """
        if not self.slots_dir.exists():
            return
        for path in self.slots_dir.glob("*.png"):
            if _LEGACY_PREVIEW.match(path.name):
                path.rename(self.slots_dir / f"{default_profile_id}_{path.name}")

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.close()
            self._capture = None

    def _interval_ms(self) -> int:
        return max(16, int(1000 / max(1, self.config.fps)))

    # ------------------------------------------------------------ 外部操作

    def set_enabled(self, enabled: bool) -> None:
        self.config.update(enabled=enabled)
        self._invalidate()

    def refresh_slots(self) -> None:
        """スロットの構成が変わったときに呼ぶ（調整モードの画像を作り直す）。"""
        self._adjust_images.clear()
        self._held_id = None
        self._invalidate()

    def set_profile(self, profile_id: str) -> None:
        """表示するキャラクターを切り替える。"""
        if profile_id == self.config.current_profile_id:
            return
        self.config.set_current_profile(profile_id)
        self.refresh_slots()

    def apply_settings(self, scale: Optional[float] = None, **kwargs) -> bool:
        """表示設定を更新して即座に反映する。

        拡大率はキャラクターと解像度ごとの設定なので、ウィンドウが無いと
        保存先を決められない。保存できたかどうかを返す。
        """
        scale_saved = True
        if scale is not None:
            key = self.current_key()
            if key is None:
                scale_saved = False
            else:
                self.config.set_scale(key, scale)
        self.config.update(**kwargs)
        self._window.set_interval(self._interval_ms())
        self._adjust_images.clear()   # 拡大率などが変わるので取り直す
        self._invalidate()
        return scale_saved

    def suspend(self) -> None:
        """ピッカー表示中などにオーバーレイを一時的に隠す。"""
        self._suspended = True

    def resume(self) -> None:
        self._suspended = False
        self._adjust_images.clear()
        self._invalidate()

    def enter_adjust_mode(self) -> None:
        """クリック透過を外し、掴みしろのドラッグとアイコンの移動を受け付ける。"""
        self._adjust_mode = True
        self._adjust_placed = False
        self._held_id = None
        self._cursor = None
        self._hover_cell = None
        self._adjust_images.clear()
        self._invalidate()

    def exit_adjust_mode(self) -> None:
        self._adjust_mode = False
        self._held_id = None
        self._cursor = None
        self._hover_cell = None
        self._metrics = None
        self._adjust_images.clear()
        self._invalidate()

    @property
    def adjust_mode(self) -> bool:
        return self._adjust_mode

    def current_key(self) -> Optional[str]:
        """現在のクライアント解像度に対応するプロファイルキー。"""
        client = get_client_rect()
        return None if client is None else OverlayConfig.profile_key(client)

    def _invalidate(self) -> None:
        """次の tick で必ず描き直させる。"""
        self._last_key = None

    # ------------------------------------------------------------ 更新ループ

    def _tick(self) -> None:
        if self._capture is None:
            self._capture = SlotCapture()

        cfg = self.config

        if self._suspended:
            self._hide("一時停止中")
            return
        if not cfg.enabled:
            self._hide("", state="disabled")
            return

        client = get_client_rect()
        if client is None:
            self._hide("マビノギのウィンドウが見つかりません")
            return

        key = OverlayConfig.profile_key(client)
        prof = cfg.get_profile(key)
        if prof is None or not prof.slots:
            self._hide(f"{key}: スキルが未登録です")
            return

        # 調整モードは OFF のスキルも薄く表示するので、先に処理する
        if self._adjust_mode:
            self._draw_adjust(client, prof)
            return

        slots = prof.active_slots()
        if not slots:
            self._hide("表示するスキルがありません")
            return

        # マビノギが非アクティブなら自動オフ
        if not is_foreground():
            self._hide("マビノギが非アクティブ")
            return

        images = self._capture.grab_slots(client, slots)
        items = [(s.col, s.row, im) for s, im in zip(slots, images)]
        img, metrics = compose(items, prof.scale, cfg.gap, cfg.background)
        self._metrics = metrics

        x, y = self._draw_position(client, prof, metrics.pad)
        self.overlap_warning = self._overlaps_capture(client, slots, x, y, img.size)
        self.state = "visible"
        self.detail = "キャプチャ範囲と重なっています" if self.overlap_warning else ""

        self._window.set_click_through(True)

        alpha = self._alpha(x, y, img.size)

        # 変化がなければ描き直さない
        state = img.tobytes() + f"{x},{y},{alpha}".encode()
        if state == self._last_key and self._window.visible:
            return
        self._last_key = state
        self._window.draw(img, x, y, alpha)

    def _alpha(self, x: int, y: int, size: tuple[int, int]) -> int:
        """描画にかける不透明度（0-255）。

        マウスオーバーで薄くする設定のときは、カーソルが表示範囲にある間だけ
        下げた値を使う。クリック透過にしている間はマウスメッセージが届かないので、
        tick ごとにカーソル位置を見て判定する。
        """
        cfg = self.config
        percent = cfg.opacity
        if cfg.hover_fade:
            cx, cy = get_cursor_pos()
            if x <= cx < x + size[0] and y <= cy < y + size[1]:
                percent = cfg.hover_opacity
        return round(percent * 255 / 100)

    def _hide(self, detail: str, state: str = "waiting") -> None:
        self.state = state
        self.detail = detail
        self._window.set_click_through(True)
        self._window.hide()
        self._last_key = None

    # ------------------------------------------------------------ 位置調整モード

    def _draw_adjust(self, client: dict, prof: Profile) -> None:
        cfg = self.config
        images = self._adjust_images
        if not images:
            # 調整中はクールタイムを見る必要がないので、一度掴んだ絵を使い回す
            images = self._grab_slot_images(client, prof)
            self._adjust_images = images

        items = []
        disabled = []
        held = None
        for s in prof.slots:
            im = images.get(s.id)
            if im is None:
                continue
            if s.id == self._held_id:
                held = (s.col, s.row, im)
            elif s.enabled:
                items.append((s.col, s.row, im))
            else:
                # OFF でも場所は取り続けるので、埋まっているマスとして薄く見せる
                disabled.append((s.col, s.row, im))

        img, metrics = compose_adjust(items, prof.scale, cfg.gap, held, self._cursor, disabled)
        self._metrics = metrics

        self._window.set_click_through(False)
        self.state = "adjusting"
        self.detail = "持ち上げ中" if self._held_id is not None else ""

        # 調整中はアイコンを掴んで動かすので、不透明度は効かせず常にはっきり見せる。
        # ドラッグ中に位置を指定し続けると引き戻してしまうため、
        # 調整モードに入った直後の1回だけ配置し、以降は現在位置を維持する
        if self._adjust_placed:
            self._window.draw(img)
        else:
            x, y = self._draw_position(client, prof, metrics.pad)
            self._window.draw(img, x, y)
            self._adjust_placed = True

    def _grab_slot_images(self, client: dict, prof: Profile) -> dict[str, Image.Image]:
        """調整モード用にスロット画像を1回だけ取得する。

        調整中はGUIを操作するためゲームが非アクティブになり、画面キャプチャでは
        手前のウィンドウが映ってしまう。ウィンドウから直接取得する。
        """
        # 調整モードでは OFF のスキルも薄く表示するので全スロット分を取る
        slots = prof.slots
        shot = capture_client(find_hwnd(), client["width"], client["height"])
        if shot is not None:
            return {s.id: shot.crop((s.x, s.y, s.x + s.w, s.y + s.h)) for s in slots}
        grabbed = self._capture.grab_slots(client, slots)
        return {s.id: im for s, im in zip(slots, grabbed)}

    def _redraw_adjust(self) -> None:
        """マウス操作に即座に追従させる（tick を待たない）。"""
        client = get_client_rect()
        if client is None:
            return
        prof = self.config.get_profile(OverlayConfig.profile_key(client))
        if prof is None or not prof.slots:
            return
        self._draw_adjust(client, prof)

    def _on_hittest(self, x: int, y: int) -> bool:
        """外周の掴みしろの上か（True ならウィンドウのドラッグ移動になる）。"""
        if self._metrics is None:
            return True
        return self._metrics.is_frame(x, y)

    def _on_click(self, x: int, y: int) -> None:
        """アイコンを持ち上げる／置く（ウィンドウスレッドから呼ばれる）。"""
        if not self._adjust_mode or self._metrics is None:
            return
        cell = self._metrics.cell_at(x, y)
        if cell is None:
            return

        client = get_client_rect()
        if client is None:
            return
        key = OverlayConfig.profile_key(client)
        prof = self.config.get_profile(key)
        if prof is None:
            return

        if self._held_id is None:
            slot = prof.slot_at(*cell)
            if slot is not None:
                self._held_id = slot.id
        else:
            self.config.place_slot(key, self._held_id, cell[0], cell[1])
            self._held_id = None
        self._redraw_adjust()

    def _on_mouse_move(self, x: int, y: int) -> None:
        if not self._adjust_mode:
            return
        self._cursor = (x, y)
        cell = self._metrics.cell_at(x, y) if self._metrics is not None else None
        # 持ち上げ中はカーソルに追従させる。それ以外はセルが変わったときだけ描き直す
        if self._held_id is not None or cell != self._hover_cell:
            self._hover_cell = cell
            self._redraw_adjust()

    # ------------------------------------------------------------ 位置

    def _origin(self, client: dict, prof: Profile) -> tuple[int, int]:
        """グリッド左上（最初のセルの左上）の絶対座標。"""
        px, py = int(prof.position[0]), int(prof.position[1])
        if self.config.anchor == "game":
            return (client["left"] + px, client["top"] + py)
        return (px, py)

    def _draw_position(self, client: dict, prof: Profile, pad: int) -> tuple[int, int]:
        """ウィンドウ左上の絶対座標。

        設定にはグリッド原点を保存しているので、余白の分だけ左上へずらす。
        これで通常表示と調整モード（掴みしろの分だけ広い）で見た目の位置が揃う。
        """
        ox, oy = self._origin(client, prof)
        return (ox - pad, oy - pad)

    def _on_moved(self, x: int, y: int) -> None:
        """掴みしろをドラッグし終えたときに呼ばれる（ウィンドウスレッド）。"""
        client = get_client_rect()
        if client is None:
            return
        key = OverlayConfig.profile_key(client)
        pad = self._metrics.pad if self._metrics is not None else FRAME
        x += pad   # ウィンドウ左上 → グリッド原点
        y += pad
        if self.config.anchor == "game":
            x -= client["left"]
            y -= client["top"]
        self.config.set_position(key, x, y)

    def _overlaps_capture(self, client: dict, slots: list[Slot],
                          x: int, y: int, size: tuple[int, int]) -> bool:
        """オーバーレイがキャプチャ対象と重なっていないか判定する。

        重なったまま表示すると自分自身を映して入れ子になる。
        """
        bounds = bounding_rect(slots)
        if bounds is None:
            return False
        bx, by, bw, bh = bounds
        cx, cy = client["left"] + bx, client["top"] + by
        return not (x + size[0] <= cx or cx + bw <= x
                    or y + size[1] <= cy or cy + bh <= y)

import ctypes
import threading
import tkinter as tk
from tkinter import ttk
from typing import Optional

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem
from tkinterdnd2 import TkinterDnD

from version import __version__
from core.controller import ScanController, BASE_DIR, BUFFS_DIR
from overlay.controller import OverlayController
from overlay.tab import OverlayTab
from charprofile.bar import ProfileBar
from charprofile.manager import ProfileManager
from charprofile.store import CharacterProfile
from .settings_window import SettingsWindow
from . import theme as ui_theme

_ASSETS_DIR = BASE_DIR / "assets"
_ICON_PATH = _ASSETS_DIR / "icon.png"
_ICON_ICO_PATH = _ASSETS_DIR / "icon.ico"

# タスクバーのアイコンを差し替えるための Win32 定数
_WM_SETICON = 0x0080
_ICON_SMALL = 0
_ICON_BIG = 1
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010

# メインウィンドウの縦横比（黄金比）
_GOLDEN_RATIO = 1.618


class App:
    BG = ui_theme.BG
    FG = ui_theme.FG
    ACCENT = ui_theme.ACCENT
    BG_ROW = ui_theme.BG_ROW

    def __init__(self, controller: ScanController, overlay: OverlayController,
                 manager: ProfileManager):
        self.controller = controller
        self.overlay = overlay
        self.manager = manager
        self.root = TkinterDnD.Tk()
        self.root.withdraw()  # 構築完了まで非表示
        self.root.title(f"AdvancedStatList v{__version__}")
        self.root.configure(bg=self.BG)
        if _ICON_ICO_PATH.exists():
            # -default 指定にすると、以降に作る Toplevel（設定・座標指定など）にも
            # 同じアイコンが引き継がれる
            self.root.iconbitmap(default=str(_ICON_ICO_PATH))

        self._tray_icon: Icon = self._create_tray_icon()
        self._tray_running = False
        self._buff_rows: dict[str, dict] = {}
        self._icons: dict[str, object] = {}  # ImageTk.PhotoImage の参照保持用
        self._settings_window: Optional[SettingsWindow] = None

        self._apply_style()
        self._build_ui()
        self._setup_window_events()
        self.manager.add_listener(self._on_profile_changed)
        self._poll()

    def _apply_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TNotebook", background=self.BG, borderwidth=0)
        style.configure("TNotebook.Tab", background="#2a2a2a", foreground=self.FG,
                        padding=[10, 4], borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", "#3a3a3a")],
                  foreground=[("selected", "#ffffff")])
        style.configure("TFrame", background=self.BG)
        style.configure("TSeparator", background="#444444")

    def _build_ui(self) -> None:
        # タブより上の段。適用中のキャラクターと、全プロファイル共通の設定への入口
        self.profile_bar = ProfileBar(self.root, self.manager, self._open_settings)

        notebook = ttk.Notebook(self.root, width=380)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)

        tab_monitor = ttk.Frame(notebook)
        notebook.add(tab_monitor, text="  バフ管理  ")
        self._build_monitor_tab(tab_monitor)

        tab_overlay = ttk.Frame(notebook)
        notebook.add(tab_overlay, text="  オーバーレイ  ")
        self.overlay_tab = OverlayTab(tab_overlay, self.overlay)

    # ------------------------------------------------------------------ プロファイル

    def _on_profile_changed(self, profile: CharacterProfile) -> None:
        """プロファイルが切り替わった／中身が変わったときの再構築。"""
        self.profile_bar.refresh()
        self._refresh_buff_rows()
        self.overlay_tab.refresh()
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.refresh()

    def _open_settings(self) -> None:
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_force()
            return
        self._settings_window = SettingsWindow(
            self.root, self.controller, self.manager, self.overlay,
            on_buff_added=self._on_buff_added,
        )

    # ---------------------------------------------------------------- バフ管理タブ

    def _build_monitor_tab(self, parent: ttk.Frame) -> None:
        ctrl_frame = tk.Frame(parent, bg=self.BG)
        ctrl_frame.pack(fill="x", padx=12, pady=(10, 6))

        tk.Label(ctrl_frame, text="スキャン:", bg=self.BG, fg=self.FG).pack(side="left")

        self._status_lbl = tk.Label(ctrl_frame, text="● 稼働中", bg=self.BG, fg="#33cc55",
                                    font=("", 9, "bold"))
        self._status_lbl.pack(side="left", padx=(6, 12))

        self._toggle_btn = tk.Button(
            ctrl_frame, text="停止", command=self._toggle_scan,
            bg="#3a3a3a", fg=self.FG, activebackground="#4a4a4a", activeforeground=self.FG,
            relief="flat", padx=12, pady=3, cursor="hand2", bd=0,
        )
        self._toggle_btn.pack(side="left")

        tk.Button(
            ctrl_frame, text="今すぐスキャン", command=self._manual_scan,
            bg="#2a4a6a", fg=self.FG, activebackground="#3a5a7a", activeforeground=self.FG,
            relief="flat", padx=12, pady=3, cursor="hand2", bd=0,
        ).pack(side="left", padx=(8, 0))

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=12, pady=4)

        hdr = tk.Frame(parent, bg=self.BG)
        hdr.pack(fill="x", padx=12)
        tk.Label(hdr, text="バフ", bg=self.BG, fg="#888888", anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(hdr, text="残り時間", bg=self.BG, fg="#888888").pack(side="right")

        self._buff_rows_frame = tk.Frame(parent, bg=self.BG)
        self._buff_rows_frame.pack(fill="both", expand=True, padx=12, pady=(2, 10))

        self._refresh_buff_rows()

    def _load_icon(self, buff_name: str):
        """バフのアクティブアイコンを 20x20 で読み込む。失敗時は None。"""
        from PIL import ImageTk
        path = BUFFS_DIR / buff_name / "icon_active.png"
        if not path.exists():
            return None
        try:
            img = Image.open(path).convert("RGBA").resize((20, 20), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _refresh_buff_rows(self) -> None:
        for w in self._buff_rows_frame.winfo_children():
            w.destroy()
        self._buff_rows.clear()
        self._icons.clear()

        order = self.controller.get_buff_order()
        for name in order:
            cfg = self.controller.buff_configs.get(name, {})
            display_name = cfg.get("display_name", name)
            enabled = self.controller.is_buff_enabled(name)

            row = tk.Frame(self._buff_rows_frame, bg=self.BG_ROW, pady=2)
            row.pack(fill="x", pady=1)

            # 順番変更ボタン（▲▼）
            btn_frame = tk.Frame(row, bg=self.BG_ROW)
            btn_frame.pack(side="left", padx=(4, 0))
            btn_kw = dict(bg=self.BG_ROW, fg="#666666", activebackground=self.BG_ROW,
                          activeforeground=self.FG, relief="flat", bd=0,
                          font=("", 7), cursor="hand2", pady=0)
            tk.Button(btn_frame, text="▲",
                      command=lambda n=name: self._move_buff(n, -1), **btn_kw
                      ).pack()
            tk.Button(btn_frame, text="▼",
                      command=lambda n=name: self._move_buff(n, +1), **btn_kw
                      ).pack()

            # 有効/無効トグルボタン
            toggle_btn = tk.Button(
                row,
                text="ON" if enabled else "OFF",
                width=4, pady=1, relief="flat", bd=0, cursor="hand2",
                **self._toggle_btn_style(enabled),
            )
            toggle_btn.config(command=self._make_toggle_cmd(name, toggle_btn))
            toggle_btn.pack(side="left", padx=(4, 4))

            # アイコン画像
            photo = self._load_icon(name)
            if photo:
                self._icons[name] = photo
                tk.Label(row, image=photo, bg=self.BG_ROW).pack(side="left", padx=(0, 4))
            else:
                tk.Frame(row, bg=self.BG_ROW, width=24).pack(side="left")

            # 表示名
            tk.Label(row, text=display_name, bg=self.BG_ROW, fg=self.FG,
                     anchor="w", width=18).pack(side="left", padx=(0, 8))

            # 残り時間
            time_lbl = tk.Label(row, text="--", bg=self.BG_ROW, fg="#888888",
                                 width=6, anchor="e")
            time_lbl.pack(side="right", padx=(0, 8))

            self._buff_rows[name] = {"time_label": time_lbl}

    def _toggle_btn_style(self, enabled: bool) -> dict:
        return ui_theme.toggle_btn_style(enabled)

    def _make_toggle_cmd(self, name: str, btn: tk.Button):
        state = {"enabled": self.controller.is_buff_enabled(name)}

        def cmd():
            state["enabled"] = not state["enabled"]
            en = state["enabled"]
            btn.config(text="ON" if en else "OFF", **self._toggle_btn_style(en))
            self.controller.set_buff_enabled(name, en)

        return cmd

    def _move_buff(self, name: str, direction: int) -> None:
        """direction: -1=上へ, +1=下へ"""
        order = self.controller.get_buff_order()
        idx = order.index(name)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(order):
            return
        order[idx], order[new_idx] = order[new_idx], order[idx]
        self.controller.set_buff_order(order)
        self._refresh_buff_rows()

    def _manual_scan(self) -> None:
        self.controller.trigger_scan()

    def _toggle_scan(self) -> None:
        if self.controller.is_running():
            self.controller.stop()
            self._status_lbl.config(text="● 停止中", fg="#cc3333")
            self._toggle_btn.config(text="開始")
        else:
            self.controller.start()
            self._status_lbl.config(text="● 稼働中", fg="#33cc55")
            self._toggle_btn.config(text="停止")

    def _on_buff_added(self) -> None:
        self.controller.reload_buffs()
        self._refresh_buff_rows()

    # ------------------------------------------------------------------ ポーリング

    def _poll(self) -> None:
        # マビノギのウィンドウの消滅・再出現を見てキャラクターを判別する
        self.manager.poll()
        self.profile_bar.refresh_status()

        timers = self.controller.get_timers()
        for name, row_data in self._buff_rows.items():
            timer = timers.get(name)
            if timer and timer.active:
                secs = int(timer.remaining)
                fg = "#ffaa00" if secs <= 30 else self.FG
                row_data["time_label"].config(text=f"{secs}s", fg=fg)
            else:
                row_data["time_label"].config(text="--", fg="#888888")
        self.root.after(500, self._poll)

    # ------------------------------------------------------------------ システムトレイ

    def _create_tray_icon(self) -> Icon:
        if _ICON_PATH.exists():
            img = Image.open(_ICON_PATH).convert("RGBA").resize((128, 128), Image.LANCZOS)
        else:
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse((8, 8, 56, 56), fill=(0, 120, 212, 255))
        menu = Menu(
            MenuItem("表示", lambda icon, item: self.root.after(0, self._show_window), default=True),
            MenuItem(
                lambda item: "スキャン停止" if self.controller.is_running() else "スキャン開始",
                self._toggle_scan_tray,
            ),
            MenuItem("終了", lambda icon, item: self.root.after(0, self._quit)),
        )
        return Icon("AdvancedStatList", img, f"AdvancedStatList v{__version__}", menu)

    def _toggle_scan_tray(self, icon: Icon, item) -> None:
        def do() -> None:
            self._toggle_scan()
            icon.update_menu()
        self.root.after(0, do)

    def _hide_to_tray(self) -> None:
        self.root.withdraw()
        if not self._tray_running:
            self._tray_running = True
            # pystray は stop() 後に再利用できないため毎回新規作成する
            self._tray_icon = self._create_tray_icon()
            threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _show_window(self) -> None:
        self.root.deiconify()
        if self._tray_running:
            self._tray_icon.stop()
            self._tray_running = False

    def _quit(self) -> None:
        if self._tray_running:
            self._tray_icon.stop()
            self._tray_running = False
        self.controller.shutdown()
        self.overlay.stop()
        self.root.destroy()

    # ------------------------------------------------------------------ ウィンドウイベント

    def _setup_window_events(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Unmap>", self._on_unmap)

    def _on_unmap(self, event: tk.Event) -> None:
        if event.widget is self.root:
            self._hide_to_tray()

    def _on_close(self) -> None:
        self._quit()

    # ------------------------------------------------------------------ 起動

    def run(self) -> None:
        self.controller.start()
        self.overlay.start()
        self.root.deiconify()
        self.root.update_idletasks()
        self._apply_golden_geometry()
        self.root.resizable(False, False)
        self._apply_taskbar_icon()
        self.root.mainloop()

    def _apply_golden_geometry(self) -> None:
        """ウィンドウを黄金比の縦長にする。

        中身が黄金比より高いときは、見切れないよう中身の高さを優先する。
        """
        width = self.root.winfo_reqwidth()
        height = max(self.root.winfo_reqheight(), round(width * _GOLDEN_RATIO))
        self.root.geometry(f"{width}x{height}")

    def _apply_taskbar_icon(self) -> None:
        """タスクバー用のアイコンを、実際に描かれるサイズで渡し直す。

        Tk がウィンドウに設定するのは 16px のアイコンだが、タスクバーは 24px で
        描くため引き伸ばされてぼやける。描画サイズに合ったものを直接渡して防ぐ。
        """
        if not _ICON_ICO_PATH.exists():
            return
        user32 = ctypes.windll.user32
        hwnd = int(self.root.wm_frame(), 16)
        scale = self.root.winfo_fpixels("1i") / 96.0  # 96dpi を等倍とする
        for icon_type, size in ((_ICON_SMALL, 24), (_ICON_BIG, 32)):
            px = round(size * scale)
            handle = user32.LoadImageW(None, str(_ICON_ICO_PATH), _IMAGE_ICON,
                                       px, px, _LR_LOADFROMFILE)
            if handle:
                user32.SendMessageW(hwnd, _WM_SETICON, icon_type, handle)

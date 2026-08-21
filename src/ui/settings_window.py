"""設定ウィンドウ。

全プロファイル共通の設定をまとめる。メインウィンドウのタブ（バフ管理・オーバーレイ）が
キャラクターごとの内容なのと対になる。
"""

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .add_buff import AddBuffApp
from core.controller import ScanController
from charprofile.manager import ProfileManager
from charprofile.tab import ProfileTab
from overlay.config import DEFAULT_SCALE
from .scroll_frame import ScrollFrame
from .theme import ACCENT, BG, FG, LINK, MUTED, flat_btn_style, toggle_btn_style

# 背景の選択肢。設定ファイルには従来どおり none / dark で保存する
_BACKGROUND_LABELS = {"none": "なし", "dark": "ダーク"}
_BACKGROUND_VALUES = {label: value for value, label in _BACKGROUND_LABELS.items()}

# 配置基準の選択肢。設定ファイルには従来どおり game / screen で保存する
_ANCHOR_LABELS = {"game": "ゲームに追従", "screen": "画面に固定"}
_ANCHOR_VALUES = {label: value for value, label in _ANCHOR_LABELS.items()}


class SettingsWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc, controller: ScanController,
                 manager: ProfileManager, overlay, on_buff_added: Callable[[], None]):
        super().__init__(master)
        self.controller = controller
        self._overlay = overlay
        self._on_buff_added = on_buff_added

        self.title("設定")
        self.configure(bg=BG)
        self.transient(master)

        notebook = ttk.Notebook(self, width=520, height=620)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)

        tab_settings = ttk.Frame(notebook)
        notebook.add(tab_settings, text="  設定  ")
        self._build_settings_tab(tab_settings)

        tab_add = ttk.Frame(notebook)
        notebook.add(tab_add, text="  バフ追加  ")
        # バナー画像のプレビューで縦に伸びるので、はみ出したらスクロールできるようにする
        add_scroll = ScrollFrame(tab_add)
        add_scroll.pack(fill="both", expand=True)
        AddBuffApp(add_scroll.body, on_added=self._buff_added)

        tab_profile = ttk.Frame(notebook)
        notebook.add(tab_profile, text="  プロファイル  ")
        self.profile_tab = ProfileTab(tab_profile, manager, overlay)

        self.update_idletasks()
        self.geometry(f"+{master.winfo_rootx() + 40}+{master.winfo_rooty() + 40}")
        self.minsize(self.winfo_reqwidth(), 360)

    def refresh(self) -> None:
        """プロファイルが切り替わったときに呼ぶ。"""
        self.profile_tab.refresh()
        # 拡大率だけはキャラクターと解像度ごとの設定なので、表示を追随させる
        key = self._overlay.current_key()
        if key is not None:
            self.v_scale.set(str(self._overlay.config.scale_of(key)))

    def _buff_added(self) -> None:
        self._on_buff_added()

    # ------------------------------------------------------------ 設定タブ

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill="both", expand=True, padx=16, pady=16)

        self._build_common_group(frame)
        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=14)
        self._build_overlay_group(frame)

        tk.Button(
            frame, text="保存", command=self._save_settings,
            padx=18, pady=6, **flat_btn_style(bg=ACCENT, fg="white", active="#005fa3"),
        ).pack(anchor="w", pady=(18, 0))

    def _group(self, parent: tk.Frame, title: str) -> tk.Frame:
        """見出し付きの設定グループ。中身は grid で並べる。"""
        tk.Label(parent, text=title, bg=BG, fg=FG, font=("", 9, "bold"), anchor="w"
                 ).pack(fill="x", pady=(0, 6))
        box = tk.Frame(parent, bg=BG)
        box.pack(fill="x", padx=(8, 0))
        box.columnconfigure(1, weight=1)
        return box

    def _entry(self, box: tk.Frame, label: str, row: int, value,
               width: int = 8) -> tk.StringVar:
        tk.Label(box, text=label, bg=BG, fg=FG
                 ).grid(row=row, column=0, sticky="w", pady=6)
        var = tk.StringVar(value=str(value))
        tk.Entry(box, textvariable=var, bg="#2a2a2a", fg="white",
                 insertbackground="white", relief="flat", bd=4, width=width,
                 ).grid(row=row, column=1, sticky="w", padx=(12, 0))
        return var

    def _scale(self, box: tk.Frame, label: str, row: int, value: int,
               from_: int = 0, to: int = 100) -> "ValueScale":
        tk.Label(box, text=label, bg=BG, fg=FG
                 ).grid(row=row, column=0, sticky="w", pady=6)
        widget = ValueScale(box, value, from_, to, title=label)
        widget.grid(row=row, column=1, sticky="ew", padx=(12, 0))
        return widget

    def _toggle(self, box: tk.Frame, label: str, row: int, value: bool,
                command) -> tuple[tk.BooleanVar, tk.Button]:
        tk.Label(box, text=label, bg=BG, fg=FG
                 ).grid(row=row, column=0, sticky="w", pady=6)
        var = tk.BooleanVar(value=value)
        btn = tk.Button(
            box, text="ON" if value else "OFF",
            width=4, pady=1, relief="flat", bd=0, cursor="hand2",
            command=command, **toggle_btn_style(value),
        )
        btn.grid(row=row, column=1, sticky="w", padx=(12, 0))
        return var, btn

    @staticmethod
    def _flip(var: tk.BooleanVar, btn: tk.Button) -> bool:
        """ON/OFF ボタンを反転して、変更後の状態を返す。"""
        enabled = not var.get()
        var.set(enabled)
        btn.config(text="ON" if enabled else "OFF", **toggle_btn_style(enabled))
        return enabled

    def _combobox(self, box: tk.Frame, label: str, row: int,
                  labels: dict, current: str, fallback: str) -> tk.StringVar:
        tk.Label(box, text=label, bg=BG, fg=FG
                 ).grid(row=row, column=0, sticky="w", pady=6)
        var = tk.StringVar(value=labels.get(current, labels[fallback]))
        ttk.Combobox(box, textvariable=var, values=list(labels.values()),
                     state="readonly", width=12
                     ).grid(row=row, column=1, sticky="w", padx=(12, 0))
        return var

    def _build_common_group(self, parent: tk.Frame) -> None:
        box = self._group(parent, "共通設定")

        self.v_interval = self._entry(box, "スキャン間隔 (秒)", 0,
                                      self.controller._scan_interval)
        self.v_volume = self._scale(box, "通知音量", 1,
                                    self.controller.notifier._volume)
        self.v_banner_y = self._entry(box, "バナーY座標 (px)", 2,
                                      self.controller.notifier.banner_y_offset)
        self.v_tuan, self._tuan_toggle_btn = self._toggle(
            box, "トゥアン延長支援", 3, self.controller._tuan_support_enabled,
            self._toggle_tuan_support)

        tk.Label(box, text="これらの設定は全プロファイル共通です。",
                 bg=BG, fg="#777777", font=("", 8), anchor="w"
                 ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _build_overlay_group(self, parent: tk.Frame) -> None:
        cfg = self._overlay.config
        box = self._group(parent, "スキルオーバーレイ")

        key = self._overlay.current_key()
        scale = cfg.scale_of(key) if key is not None else DEFAULT_SCALE
        self.v_scale = self._entry(box, "拡大率", 0, scale, width=6)
        self.v_gap = self._entry(box, "余白 (px)", 1, cfg.gap, width=6)
        self.v_fps = self._entry(box, "更新レート (fps)", 2, cfg.fps, width=6)
        self.v_background = self._combobox(box, "背景", 3, _BACKGROUND_LABELS,
                                           cfg.background, "none")
        self.v_anchor = self._combobox(box, "配置基準", 4, _ANCHOR_LABELS,
                                       cfg.anchor, "game")

        # 完全に消えてしまうと見失うので、通常時は下限を設ける
        self.v_opacity = self._scale(box, "不透明度 (%)", 5, cfg.opacity, from_=10)
        self.v_hover_fade, self._hover_toggle_btn = self._toggle(
            box, "マウスオーバーで薄く", 6, cfg.hover_fade, self._toggle_hover_fade)
        self.v_hover_opacity = self._scale(
            box, "マウスオーバー時の不透明度 (%)", 7, cfg.hover_opacity)
        self.v_hover_opacity.set_enabled(cfg.hover_fade)

        tk.Label(box, text="拡大率はキャラクターと解像度ごとの設定です。",
                 bg=BG, fg="#777777", font=("", 8), anchor="w"
                 ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _toggle_tuan_support(self) -> None:
        self._flip(self.v_tuan, self._tuan_toggle_btn)

    def _toggle_hover_fade(self) -> None:
        # 薄くしないなら、その不透明度をいじれても意味がないので触らせない
        enabled = self._flip(self.v_hover_fade, self._hover_toggle_btn)
        self.v_hover_opacity.set_enabled(enabled)

    def _save_settings(self) -> None:
        try:
            interval = int(self.v_interval.get())
            banner_y = int(self.v_banner_y.get())
            scale = float(self.v_scale.get())
            gap = int(self.v_gap.get())
            fps = int(self.v_fps.get())
        except ValueError:
            messagebox.showerror("入力エラー", "数値の項目は数値で入力してください。",
                                 parent=self)
            return
        if interval <= 0 or scale <= 0 or gap < 0 or fps < 1:
            messagebox.showerror(
                "入力エラー",
                "スキャン間隔・拡大率・更新レートは 0 より大きい値を、\n"
                "余白は 0 以上を入力してください。",
                parent=self)
            return

        self.controller.update_settings(
            scan_interval=interval, volume=self.v_volume.get(),
            banner_y_offset=banner_y, tuan_support_enabled=self.v_tuan.get(),
        )
        saved = self._overlay.apply_settings(
            scale=scale, gap=gap, fps=min(30, fps),
            background=_BACKGROUND_VALUES.get(self.v_background.get(), "none"),
            anchor=_ANCHOR_VALUES.get(self.v_anchor.get(), "game"),
            opacity=self.v_opacity.get(),
            hover_fade=self.v_hover_fade.get(),
            hover_opacity=self.v_hover_opacity.get(),
        )
        if not saved:
            # 拡大率はキャラクターと解像度ごとの設定なので、保存先を決められない
            messagebox.showwarning("スキルオーバーレイ",
                                   "マビノギのウィンドウが見つからないため、\n"
                                   "拡大率は保存されませんでした。",
                                   parent=self)


class ValueScale(tk.Frame):
    """スライダーと現在値の組。

    値をクリックするとその場が入力欄に変わり、数値で直接指定できる。
    Enter または他所をクリックで確定、Esc で取り消す。
    """

    def __init__(self, master: tk.Misc, value: int, from_: int = 0, to: int = 100,
                 title: str = ""):
        super().__init__(master, bg=BG)
        self._from = from_
        self._to = to
        self._editing = False

        self.var = tk.IntVar(value=value)
        # つまみの上の数値は右の表示と重複するので出さない
        self._scale = tk.Scale(
            self, from_=from_, to=to, orient="horizontal", variable=self.var,
            showvalue=False, bg=BG, fg=FG, highlightthickness=0,
            troughcolor="#3a3a3a", activebackground=ACCENT, length=180,
        )
        self._scale.pack(side="left")

        self._value_lbl = tk.Label(self, textvariable=self.var, bg=BG, fg=LINK,
                                   width=4, font=("", 9, "underline"), cursor="hand2")
        self._value_lbl.pack(side="left", padx=(6, 0))
        self._value_lbl.bind("<Button-1>", self._edit)

        # 入力欄はラベルと同じ場所に出し入れするので、幅を揃えておく
        self._entry_var = tk.StringVar()
        self._entry = tk.Entry(self, textvariable=self._entry_var, width=4,
                               bg="#2a2a2a", fg="white", insertbackground="white",
                               relief="flat", bd=2, justify="center")
        self._entry.bind("<Return>", self._commit)
        self._entry.bind("<FocusOut>", self._commit)
        self._entry.bind("<Escape>", self._cancel)

    def get(self) -> int:
        return self.var.get()

    def set_enabled(self, enabled: bool) -> None:
        if not enabled:
            self._cancel()
        self._scale.config(state="normal" if enabled else "disabled")
        self._value_lbl.config(fg=LINK if enabled else MUTED,
                               cursor="hand2" if enabled else "",
                               font=("", 9, "underline") if enabled else ("", 9))

    # ------------------------------------------------------------ 直接入力

    def _edit(self, _event=None) -> None:
        if self._editing or str(self._scale.cget("state")) == "disabled":
            return
        self._editing = True
        self._entry_var.set(str(self.var.get()))
        self._value_lbl.pack_forget()
        self._entry.pack(side="left", padx=(6, 0))
        self._entry.focus_set()
        self._entry.select_range(0, "end")

    def _commit(self, _event=None) -> None:
        if not self._editing:
            return
        text = self._entry_var.get().strip()
        self._close()
        try:
            value = int(text)
        except ValueError:
            return   # 数値でなければ元の値のまま
        self.var.set(max(self._from, min(self._to, value)))

    def _cancel(self, _event=None) -> None:
        if self._editing:
            self._close()

    def _close(self) -> None:
        # 先に下ろしてから畳む。pack_forget で飛ぶ FocusOut を二重処理しない
        self._editing = False
        self._entry.pack_forget()
        self._value_lbl.pack(side="left", padx=(6, 0))

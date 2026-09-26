"""バフ設定編集ウィンドウ。

バフ管理タブの右クリックメニューから開き、buffs/{name}/ の config.yaml と
バナー・サウンドを GUI で差し替える。
"""

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Optional

from PIL import Image

from core.buff_files import install_banner, install_sound, remove_sound, write_config
from core.controller import BUFFS_DIR
from notify.notifier import Notifier
from .add_buff import DropZone
from .spin import bind_spin
from .theme import ACCENT, BG, DISABLED_FG, FG, MUTED, flat_btn_style, toggle_btn_style

_ENTRY_BG = "#2a2a2a"
_WARN_FG = "#ffaa00"
_INACTIVE_SOUND_STEM = "sound_inactive"
_TYPE_CHOICES = ["normal", "music_buff"]


def _same_file(a: Optional[Path], b: Optional[Path]) -> bool:
    if a is None or b is None:
        return False
    return a.resolve() == b.resolve()


class BuffEditWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc, name: str, cfg: dict,
                 on_saved: Callable[[], None], notifier: Notifier):
        super().__init__(master)
        self.buff_name = name
        self._cfg = cfg
        self._on_saved = on_saved
        self._notifier = notifier
        self._buff_dir = BUFFS_DIR / name
        self._sound_removed = False
        self._inactive_banner_removed = False
        self._inactive_sound_removed = False

        self.title(f"バフ設定 - {cfg.get('display_name', name)}")
        self.configure(bg=BG)
        self.transient(master)
        self.resizable(False, False)

        self._build_form()
        self._build_dropzones()
        self._build_buttons()
        self._load_current_files()

        self.update_idletasks()
        self.geometry(f"+{master.winfo_rootx() + 40}+{master.winfo_rooty() + 40}")

    # ------------------------------------------------------------------ UI構築

    def _build_form(self) -> None:
        form = tk.Frame(self, bg=BG)
        form.pack(fill="x", padx=14, pady=(14, 6))

        def label(text: str, row: int) -> None:
            tk.Label(form, text=text, bg=BG, fg=FG, anchor="w", width=10
                     ).grid(row=row, column=0, sticky="w", pady=4)

        def entry(row: int, default: str, numeric: bool = False) -> tk.StringVar:
            var = tk.StringVar(value=default)
            e = tk.Entry(form, textvariable=var, bg=_ENTRY_BG, fg="#ffffff",
                         insertbackground="white", relief="flat", bd=4, width=30)
            e.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=4)
            if numeric:
                # 選んでいる間は十字キー上下とホイールで増減できるようにする
                bind_spin(e, var, minimum=0)
            return var

        label("バフID", 0)
        tk.Label(form, text=self.buff_name, bg=BG, fg=MUTED, anchor="w"
                 ).grid(row=0, column=1, sticky="w", padx=(12, 0), pady=4)

        label("表示名", 1)
        self.v_display = entry(1, str(self._cfg.get("display_name", self.buff_name)))

        label("種別", 2)
        self.v_type = tk.StringVar(value=str(self._cfg.get("type", "normal")))
        ttk.Combobox(form, textvariable=self.v_type, values=_TYPE_CHOICES,
                     state="readonly", width=27).grid(row=2, column=1, sticky="ew",
                                                      padx=(8, 0), pady=4)

        label("通知秒数", 3)
        self.v_threshold = entry(3, str(self._cfg.get("warning_threshold", 30)),
                                 numeric=True)
        form.columnconfigure(1, weight=1)

    def _sep(self) -> None:
        tk.Frame(self, bg="#333333", height=1).pack(fill="x", padx=14, pady=4)

    def _build_dropzones(self) -> None:
        self._sep()

        self.dz_banner = DropZone(self, "バナー画像", "image",
                                  preview_size=(360, 56), height=100)
        self.dz_banner.pack(fill="x", padx=14, pady=4)

        # 10秒前バナーは音楽バフでしか使わないので、種別が music_buff のときだけ見せる。
        # 区切り線ごと 1 つの Frame にまとめて pack / pack_forget を切り替える
        self._tuan_frame = tk.Frame(self, bg=BG)
        tk.Frame(self._tuan_frame, bg="#333333", height=1).pack(fill="x", padx=14, pady=4)
        self.dz_tuan_banner = DropZone(self._tuan_frame, "10秒前バナー画像 (音楽バフ用)",
                                       "image", preview_size=(360, 56), height=100)
        self.dz_tuan_banner.pack(fill="x", padx=14, pady=4)
        self.v_type.trace_add("write", lambda *_: self._update_tuan_visibility())
        # 初期表示は config.yaml の type に従う
        self._update_tuan_visibility()

        self._sep()

        sound_row = tk.Frame(self, bg=BG)
        sound_row.pack(fill="x", padx=14, pady=4)
        self.dz_sound = DropZone(sound_row, "サウンドファイル（wav は mp3 に変換）",
                                 "audio", height=60,
                                 on_change=self._update_preview_state)
        self.dz_sound.pack(side="left", fill="both", expand=True)
        sound_btns = tk.Frame(sound_row, bg=BG)
        sound_btns.pack(side="left", padx=(8, 0))
        self._btn_preview = tk.Button(sound_btns, text="試聴", command=self._preview_sound,
                                      padx=10, pady=2, state="disabled",
                                      **flat_btn_style())
        self._btn_preview.pack(fill="x")
        tk.Button(sound_btns, text="サウンドなし", command=self._clear_sound,
                  padx=10, pady=2, **flat_btn_style()
                  ).pack(fill="x", pady=(4, 0))

        self._sep()
        self._build_inactive_group()
        self._sep()

    def _build_inactive_group(self) -> None:
        toggle_row = tk.Frame(self, bg=BG)
        toggle_row.pack(fill="x", padx=14, pady=4)
        self._inactive_alert_lbl = tk.Label(toggle_row, text="未使用状態を通知", bg=BG, fg=FG)
        self._inactive_alert_lbl.pack(side="left")
        # 数値で書かれた config.yaml もあるので、真偽値に限らず 0 以外を ON とみなす
        enabled = bool(self._cfg.get("inactive_alert"))
        self.v_inactive_alert = tk.BooleanVar(value=enabled)
        self._inactive_toggle_btn = tk.Button(
            toggle_row, text="ON" if enabled else "OFF",
            width=4, pady=1, relief="flat", bd=0, cursor="hand2",
            disabledforeground=DISABLED_FG,
            command=self._toggle_inactive_alert, **toggle_btn_style(enabled),
        )
        self._inactive_toggle_btn.pack(side="left", padx=(12, 0))
        self._inactive_warn_lbl = tk.Label(toggle_row, text="", bg=BG, fg=_WARN_FG,
                                           font=("", 8))
        self._inactive_warn_lbl.pack(side="left", padx=(8, 0))

        # 差し替えのみで削除はさせない。消すと未使用を判定できなくなる
        self.dz_inactive_icon = DropZone(self, "非アクティブアイコン", "image",
                                         preview_size=(24, 24), padx=12,
                                         on_change=self._sync_inactive_alert)
        self.dz_inactive_icon.pack(anchor="w", padx=14, pady=4)

        banner_row = tk.Frame(self, bg=BG)
        banner_row.pack(fill="x", padx=14, pady=4)
        self.dz_inactive_banner = DropZone(banner_row, "未使用通知バナー画像", "image",
                                           preview_size=(360, 56), height=100,
                                           on_change=self._sync_inactive_alert)
        self.dz_inactive_banner.pack(side="left", fill="both", expand=True)
        tk.Button(banner_row, text="バナーなし", command=self._clear_inactive_banner,
                  padx=10, pady=2, **flat_btn_style()
                  ).pack(side="left", padx=(8, 0))

        sound_row = tk.Frame(self, bg=BG)
        sound_row.pack(fill="x", padx=14, pady=4)
        self.dz_inactive_sound = DropZone(sound_row, "未使用通知サウンド（wav は mp3 に変換）",
                                          "audio", height=60,
                                          on_change=self._update_inactive_sound_state)
        self.dz_inactive_sound.pack(side="left", fill="both", expand=True)
        sound_btns = tk.Frame(sound_row, bg=BG)
        sound_btns.pack(side="left", padx=(8, 0))
        self._btn_inactive_preview = tk.Button(sound_btns, text="試聴",
                                               command=self._preview_inactive_sound,
                                               padx=10, pady=2, state="disabled",
                                               **flat_btn_style())
        self._btn_inactive_preview.pack(fill="x")
        tk.Button(sound_btns, text="サウンドなし", command=self._clear_inactive_sound,
                  padx=10, pady=2, **flat_btn_style()
                  ).pack(fill="x", pady=(4, 0))

        self._sync_inactive_alert()

    def _update_tuan_visibility(self) -> None:
        if self.v_type.get() == "music_buff":
            self._tuan_frame.pack(after=self.dz_banner, fill="x")
        else:
            # normal に戻したあと、見えない欄の値が保存されないように空にする
            self.dz_tuan_banner.reset()
            self._tuan_frame.pack_forget()

    def _build_buttons(self) -> None:
        btns = tk.Frame(self, bg=BG)
        btns.pack(pady=(4, 18))
        tk.Button(btns, text="保存", command=self._save, padx=18, pady=6,
                  **flat_btn_style(bg=ACCENT, fg="white", active="#005fa3")
                  ).pack(side="left")
        tk.Button(btns, text="キャンセル", command=self.destroy, padx=18, pady=6,
                  **flat_btn_style()).pack(side="left", padx=(10, 0))

    def _load_current_files(self) -> None:
        self._banner_orig: Optional[Path] = None
        banner = self._buff_dir / "banner.png"
        if banner.exists():
            self._banner_orig = banner
            self.dz_banner.set_path(banner)

        self._tuan_banner_orig: Optional[Path] = None
        tuan_banner = self._buff_dir / "banner_tuan.png"
        if tuan_banner.exists():
            self._tuan_banner_orig = tuan_banner
            self.dz_tuan_banner.set_path(tuan_banner)

        self._sound_orig: Optional[Path] = None
        for sound in self._buff_dir.glob("sound.*"):
            self._sound_orig = sound
            self.dz_sound.set_path(sound)
            break

        self._inactive_icon_orig: Optional[Path] = None
        inactive_icon = self._buff_dir / "icon_inactive.png"
        if inactive_icon.exists():
            self._inactive_icon_orig = inactive_icon
            self.dz_inactive_icon.set_path(inactive_icon)

        self._inactive_banner_orig: Optional[Path] = None
        inactive_banner = self._buff_dir / "banner_inactive.png"
        if inactive_banner.exists():
            self._inactive_banner_orig = inactive_banner
            self.dz_inactive_banner.set_path(inactive_banner)

        self._inactive_sound_orig: Optional[Path] = None
        for sound in self._buff_dir.glob(f"{_INACTIVE_SOUND_STEM}.*"):
            self._inactive_sound_orig = sound
            self.dz_inactive_sound.set_path(sound)
            break

    # ------------------------------------------------------------------ ロジック

    def _update_preview_state(self) -> None:
        state = "normal" if self.dz_sound.path is not None else "disabled"
        self._btn_preview.config(state=state)

    def _preview_sound(self) -> None:
        if self.dz_sound.path is not None:
            self._notifier.preview(self.dz_sound.path)

    def _clear_sound(self) -> None:
        self.dz_sound.reset()
        self._sound_removed = True

    def _toggle_inactive_alert(self) -> None:
        enabled = not self.v_inactive_alert.get()
        self.v_inactive_alert.set(enabled)
        self._inactive_toggle_btn.config(text="ON" if enabled else "OFF",
                                         **toggle_btn_style(enabled))
        self._sync_inactive_alert()

    def _sync_inactive_alert(self) -> None:
        """ON/OFF ボタンを押せるかと警告文を、保存予定の内容に合わせる。"""
        # 未使用の判定は非アクティブアイコンの検出で行うため、アイコンが無いうちは設定させない。
        # 欄は差し替えのみで空に戻せないので、欄にあれば既存かドロップ済みのどちらか
        has_icon = self.dz_inactive_icon.path is not None
        self._inactive_toggle_btn.config(state="normal" if has_icon else "disabled",
                                         cursor="hand2" if has_icon else "")
        self._inactive_alert_lbl.config(fg=FG if has_icon else DISABLED_FG)

        silent = (self.dz_inactive_banner.path is None
                  and self.dz_inactive_sound.path is None)
        warn = self.v_inactive_alert.get() and silent
        self._inactive_warn_lbl.config(text="バナーも音声も無いため通知されません" if warn else "")

    def _clear_inactive_banner(self) -> None:
        self.dz_inactive_banner.reset()
        self._inactive_banner_removed = True

    def _update_inactive_sound_state(self) -> None:
        state = "normal" if self.dz_inactive_sound.path is not None else "disabled"
        self._btn_inactive_preview.config(state=state)
        self._sync_inactive_alert()

    def _preview_inactive_sound(self) -> None:
        if self.dz_inactive_sound.path is not None:
            self._notifier.preview(self.dz_inactive_sound.path)

    def _clear_inactive_sound(self) -> None:
        self.dz_inactive_sound.reset()
        self._inactive_sound_removed = True

    def destroy(self) -> None:
        self._notifier.stop_preview()
        super().destroy()

    def _save(self) -> None:
        display_name = self.v_display.get().strip()
        if not display_name:
            messagebox.showerror("入力エラー", "表示名を入力してください。", parent=self)
            return
        threshold_text = self.v_threshold.get().strip()
        if not threshold_text.isdigit():
            messagebox.showerror("入力エラー", "通知秒数は整数で入力してください。",
                                 parent=self)
            return

        # 試聴中は MCI が sound.* / sound_inactive.* を開いたままで消せないので、先に止める
        self._notifier.stop_preview()

        # 元のファイルと同じパスなら触らない。同じ sound.* を消してからコピーすると
        # 元が無くなって失敗するし、更新日時も変えたくない
        sound_src = self.dz_sound.path
        if sound_src is not None:
            if not _same_file(sound_src, self._sound_orig):
                try:
                    install_sound(self._buff_dir, sound_src)
                except Exception as e:
                    messagebox.showerror("変換エラー",
                                         f"WAV を MP3 に変換できませんでした:\n{e}",
                                         parent=self)
                    return
        elif self._sound_removed:
            remove_sound(self._buff_dir)

        inactive_sound_src = self.dz_inactive_sound.path
        if inactive_sound_src is not None:
            if not _same_file(inactive_sound_src, self._inactive_sound_orig):
                try:
                    install_sound(self._buff_dir, inactive_sound_src, _INACTIVE_SOUND_STEM)
                except Exception as e:
                    messagebox.showerror("変換エラー",
                                         f"WAV を MP3 に変換できませんでした:\n{e}",
                                         parent=self)
                    return
        elif self._inactive_sound_removed:
            remove_sound(self._buff_dir, _INACTIVE_SOUND_STEM)

        banner_src = self.dz_banner.path
        if banner_src is not None and not _same_file(banner_src, self._banner_orig):
            install_banner(self._buff_dir, banner_src)

        tuan_src = self.dz_tuan_banner.path
        if tuan_src is not None and not _same_file(tuan_src, self._tuan_banner_orig):
            install_banner(self._buff_dir, tuan_src, "banner_tuan.png")

        icon_src = self.dz_inactive_icon.path
        if icon_src is not None and not _same_file(icon_src, self._inactive_icon_orig):
            # Scanner は icon_inactive.png の固定名でしか読まないので、元の形式に関わらず PNG に揃える
            Image.open(icon_src).convert("RGBA").save(self._buff_dir / "icon_inactive.png")

        inactive_banner_src = self.dz_inactive_banner.path
        if inactive_banner_src is not None:
            if not _same_file(inactive_banner_src, self._inactive_banner_orig):
                install_banner(self._buff_dir, inactive_banner_src, "banner_inactive.png")
        elif self._inactive_banner_removed:
            (self._buff_dir / "banner_inactive.png").unlink(missing_ok=True)

        write_config(
            self._buff_dir, self.buff_name,
            display_name=display_name,
            type_=self.v_type.get(),
            warning_threshold=int(threshold_text),
            enabled=bool(self._cfg.get("enabled", True)),
            inactive_alert=self.v_inactive_alert.get(),
        )

        self.destroy()
        self._on_saved()

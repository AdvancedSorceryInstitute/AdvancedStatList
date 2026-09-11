"""バフ設定編集ウィンドウ。

バフ管理タブの右クリックメニューから開き、buffs/{name}/ の config.yaml と
バナー・サウンドを GUI で差し替える。
"""

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Optional

from core.buff_files import install_banner, install_sound, remove_sound, write_config
from core.controller import BUFFS_DIR
from notify.notifier import Notifier
from .add_buff import DropZone
from .spin import bind_spin
from .theme import ACCENT, BG, FG, MUTED, flat_btn_style

_ENTRY_BG = "#2a2a2a"
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

        self._sound_orig: Optional[Path] = None
        for sound in self._buff_dir.glob("sound.*"):
            self._sound_orig = sound
            self.dz_sound.set_path(sound)
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

        # 試聴中は MCI が sound.* を開いたままで消せないので、先に止める
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

        banner_src = self.dz_banner.path
        if banner_src is not None and not _same_file(banner_src, self._banner_orig):
            install_banner(self._buff_dir, banner_src)

        write_config(
            self._buff_dir, self.buff_name,
            display_name=display_name,
            type_=self.v_type.get(),
            warning_threshold=int(threshold_text),
            enabled=bool(self._cfg.get("enabled", True)),
        )

        self.destroy()
        self._on_saved()

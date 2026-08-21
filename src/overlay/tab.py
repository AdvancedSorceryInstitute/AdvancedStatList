"""GUI の「オーバーレイ」タブ。

オーバーレイの ON/OFF と、スロットの登録・編集・削除を行う。
一覧の並べ替えは表示順を整えるためのもので、オーバーレイ上の位置は変わらない
（位置は「位置調整」から動かす）。
拡大率などの表示設定は設定ウィンドウの「設定」タブにある。
"""

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from PIL import Image, ImageTk

from win.window import find_hwnd, get_client_rect
from win.window_capture import capture_client

from .config import OverlayConfig, Slot
from .controller import OverlayController
from .picker import SlotPicker

_BG = "#1e1e1e"
_BG_ROW = "#252525"
_FG = "#cccccc"
_ACCENT = "#0078d4"
_PREVIEW = 28

# 状態表示（バフ管理タブの「● 稼働中」と同じ体裁）
_STATE_TEXT = {
    "visible": ("● 表示中", "#33cc55"),
    "adjusting": ("● 調整中", "#ffaa00"),
    "waiting": ("● 待機中", "#ffaa00"),
    "disabled": ("● 停止中", "#cc3333"),
}


class OverlayTab:
    def __init__(self, master: tk.Misc, overlay: OverlayController):
        self._overlay = overlay
        self._master = master
        self._rows: dict[str, dict] = {}
        self._previews: dict[str, ImageTk.PhotoImage] = {}

        self._build()
        self._refresh_rows()
        self._poll()

    @property
    def _config(self) -> OverlayConfig:
        return self._overlay.config

    def refresh(self) -> None:
        """キャラクタープロファイルが切り替わったときに作り直す。"""
        self._refresh_rows()

    # ------------------------------------------------------------ UI構築

    def _build(self) -> None:
        frame = tk.Frame(self._master, bg=_BG)
        frame.pack(fill="both", expand=True)

        # 状態表示と一括 ON/OFF
        head = tk.Frame(frame, bg=_BG)
        head.pack(fill="x", padx=12, pady=(10, 6))

        tk.Label(head, text="オーバーレイ:", bg=_BG, fg=_FG).pack(side="left")
        self._state_lbl = tk.Label(head, text="", bg=_BG, fg="#33cc55", font=("", 9, "bold"))
        self._state_lbl.pack(side="left", padx=(6, 12))

        self._toggle_btn = tk.Button(
            head, text="停止" if self._config.enabled else "開始",
            command=self._toggle_enabled,
            bg="#3a3a3a", fg=_FG, activebackground="#4a4a4a", activeforeground=_FG,
            relief="flat", padx=12, pady=3, cursor="hand2", bd=0,
        )
        self._toggle_btn.pack(side="left")

        self._detail_lbl = tk.Label(head, text="", bg=_BG, fg="#888888",
                                    anchor="w", font=("", 8))
        self._detail_lbl.pack(side="left", fill="x", expand=True, padx=(8, 0))

        ttk.Separator(frame, orient="horizontal").pack(fill="x", padx=12, pady=4)

        tk.Label(frame, text="アイコンをクリックで選び直し / 座標をクリックで数値指定",
                 bg=_BG, fg="#777777", anchor="w", font=("", 8)
                 ).pack(fill="x", padx=12)

        # スロット一覧
        self._rows_frame = tk.Frame(frame, bg=_BG)
        self._rows_frame.pack(fill="both", expand=True, padx=12, pady=(2, 6))

        # 操作ボタン（プロファイルタブと同じく一覧の下に置く）
        btns = tk.Frame(frame, bg=_BG)
        btns.pack(fill="x", padx=12, pady=(8, 4))
        tk.Button(
            btns, text="スキル追加", command=self._add_slot,
            bg="#2a4a6a", fg=_FG, activebackground="#3a5a7a", activeforeground=_FG,
            relief="flat", padx=12, pady=3, cursor="hand2", bd=0,
        ).pack(side="left")
        self._adjust_btn = tk.Button(
            btns, text="位置調整", command=self._toggle_adjust,
            bg="#3a3a3a", fg=_FG, activebackground="#4a4a4a", activeforeground=_FG,
            relief="flat", padx=12, pady=3, cursor="hand2", bd=0,
        )
        self._adjust_btn.pack(side="left", padx=(8, 0))

        self._hint_lbl = tk.Label(frame, text="", bg=_BG, fg="#8a8a8a", anchor="w",
                                  justify="left", wraplength=360, font=("", 8))
        self._hint_lbl.pack(fill="x", padx=12, pady=(0, 10))

    def _btn_style(self, enabled: bool) -> dict:
        if enabled:
            return {"bg": "#1a5c1a", "fg": "white",
                    "activebackground": "#236b23", "activeforeground": "white"}
        return {"bg": "#3a3a3a", "fg": "#888888",
                "activebackground": "#4a4a4a", "activeforeground": "#aaaaaa"}

    # ------------------------------------------------------------ スロット一覧

    def _refresh_rows(self) -> None:
        for w in self._rows_frame.winfo_children():
            w.destroy()
        self._rows.clear()
        self._previews.clear()

        key = self._overlay.current_key()
        if key is None:
            tk.Label(self._rows_frame, text="マビノギのウィンドウが見つかりません",
                     bg=_BG, fg="#888888").pack(anchor="w", pady=6)
            return

        prof = self._config.get_profile(key)
        slots = prof.slots if prof else []
        if not slots:
            tk.Label(self._rows_frame,
                     text=f"{key} のスキルは未登録です。「スキル追加」から登録してください。",
                     bg=_BG, fg="#888888", wraplength=340, justify="left"
                     ).pack(anchor="w", pady=6)
            return

        for slot in slots:
            self._build_row(key, slot)

    def _build_row(self, key: str, slot: Slot) -> None:
        row = tk.Frame(self._rows_frame, bg=_BG_ROW, pady=2)
        row.pack(fill="x", pady=1)

        # 並べ替え（表示順のみ）
        btn_kw = dict(bg=_BG_ROW, fg="#666666", activebackground=_BG_ROW,
                      activeforeground=_FG, relief="flat", bd=0,
                      font=("", 7), cursor="hand2", pady=0)
        arrows = tk.Frame(row, bg=_BG_ROW)
        arrows.pack(side="left", padx=(4, 0))
        tk.Button(arrows, text="▲", command=lambda: self._move(key, slot.id, -1), **btn_kw).pack()
        tk.Button(arrows, text="▼", command=lambda: self._move(key, slot.id, +1), **btn_kw).pack()

        # スキルごとの表示 ON/OFF
        toggle_btn = tk.Button(
            row, text="ON" if slot.enabled else "OFF",
            width=4, pady=1, relief="flat", bd=0, cursor="hand2",
            **self._btn_style(slot.enabled),
        )
        toggle_btn.config(command=lambda: self._toggle_slot(key, slot, toggle_btn))
        toggle_btn.pack(side="left", padx=(4, 4))

        # プレビュー（クリックで選び直し）
        photo = self._load_preview(key, slot)
        if photo is not None:
            self._previews[slot.id] = photo
            preview = tk.Label(row, image=photo, bg=_BG_ROW, cursor="hand2")
        else:
            preview = tk.Label(row, text="?", width=3, bg=_BG_ROW, fg="#666666", cursor="hand2")
        preview.pack(side="left", padx=(2, 6))
        preview.bind("<Button-1>", lambda _, s=slot: self._reselect(key, s))

        var = tk.StringVar(value=slot.label)
        ent = tk.Entry(row, textvariable=var, bg="#2a2a2a", fg="white",
                       insertbackground="white", relief="flat", bd=3, width=11)
        ent.pack(side="left")
        ent.bind("<FocusOut>", lambda _, s=slot, v=var: self._rename(s, v))
        ent.bind("<Return>", lambda _, s=slot, v=var: self._rename(s, v))

        # 座標（クリックで数値指定）
        pos_lbl = tk.Label(row, text=f"({slot.x}, {slot.y})", bg=_BG_ROW, fg="#8899aa",
                           font=("", 8, "underline"), cursor="hand2")
        pos_lbl.pack(side="left", padx=(8, 0))
        pos_lbl.bind("<Button-1>", lambda _, s=slot: self._edit_position(key, s))

        tk.Button(
            row, text="削除", command=lambda: self._remove(key, slot.id),
            bg="#4a2a2a", fg="#ccaaaa", activebackground="#5a3a3a", activeforeground="white",
            relief="flat", bd=0, padx=8, cursor="hand2",
        ).pack(side="right", padx=(0, 6))

        self._rows[slot.id] = {"label_var": var}

    def _load_preview(self, key: str, slot: Slot) -> Optional[ImageTk.PhotoImage]:
        path = self._preview_path(key, slot.id)
        if not path.exists():
            return None
        try:
            img = Image.open(path).convert("RGBA").resize((_PREVIEW, _PREVIEW), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _preview_path(self, key: str, slot_id: str):
        # スロットはキャラクターごとに違うので、プロファイル ID も名前に含める
        return self._overlay.slots_dir / f"{self._config.current_profile_id}_{key}_{slot_id}.png"

    # ------------------------------------------------------------ 操作

    def _toggle_enabled(self) -> None:
        enabled = not self._config.enabled
        self._overlay.set_enabled(enabled)
        self._toggle_btn.config(text="停止" if enabled else "開始")

    def _toggle_slot(self, key: str, slot: Slot, btn: tk.Button) -> None:
        enabled = not slot.enabled
        self._config.set_slot_enabled(key, slot.id, enabled)
        btn.config(text="ON" if enabled else "OFF", **self._btn_style(enabled))
        self._overlay.refresh_slots()

    def _toggle_adjust(self) -> None:
        if self._overlay.adjust_mode:
            self._overlay.exit_adjust_mode()
            self._adjust_btn.config(text="位置調整", bg="#3a3a3a", fg=_FG)
            self._hint_lbl.config(text="")
        else:
            self._overlay.enter_adjust_mode()
            self._adjust_btn.config(text="調整を終了", bg="#8a5a00", fg="white")
            self._hint_lbl.config(
                text="外周の枠をドラッグすると全体を移動できます。"
                     "アイコンをクリックで持ち上げ、もう一度クリックで置きます。")

    def _move(self, key: str, slot_id: str, direction: int) -> None:
        self._config.move_slot(key, slot_id, direction)
        self._refresh_rows()

    def _remove(self, key: str, slot_id: str) -> None:
        self._config.remove_slot(key, slot_id)
        # 同じ ID が再利用されたときに古い画像が残らないよう消しておく
        self._preview_path(key, slot_id).unlink(missing_ok=True)
        self._overlay.refresh_slots()
        self._refresh_rows()

    def _rename(self, slot: Slot, var: tk.StringVar) -> None:
        label = var.get().strip()
        if label and label != slot.label:
            slot.label = label
            self._config.save()

    # ------------------------------------------------------------ 位置の変更

    def _reselect(self, key: str, slot: Slot) -> None:
        """プレビューをクリックしたとき: ピッカーで切り出し位置を選び直す。"""
        client = get_client_rect()
        if client is None:
            self._warn_no_window()
            return
        self._overlay.suspend()
        self._open_picker(client, key, target=slot)

    def _edit_position(self, key: str, slot: Slot) -> None:
        """座標をクリックしたとき: 数値で直接指定する。"""
        result = PositionDialog(self._master.winfo_toplevel(), slot).result
        if result is None:
            return
        x, y = result
        self._config.update_slot_rect(key, slot.id, x, y)
        self._update_preview_from_window(key, slot)
        self._overlay.refresh_slots()
        self._refresh_rows()

    def _update_preview_from_window(self, key: str, slot: Slot) -> None:
        """変更後の矩形でプレビューを取り直す。"""
        client = get_client_rect()
        if client is None:
            return
        shot = capture_client(find_hwnd(), client["width"], client["height"])
        if shot is not None:
            self._save_preview(key, slot, shot)

    # ------------------------------------------------------------ ピッカー

    def _add_slot(self) -> None:
        client = get_client_rect()
        if client is None:
            self._warn_no_window()
            return

        key = OverlayConfig.profile_key(client)
        # ピッカーはウィンドウから直接キャプチャするため、
        # ゲームを前面に出したり自分のウィンドウを退けたりする必要はない
        self._overlay.suspend()
        self._open_picker(client, key)

    def _warn_no_window(self) -> None:
        messagebox.showwarning("オーバーレイ",
                               "マビノギのウィンドウが見つかりません。\n"
                               "ゲームを起動した状態で実行してください。")

    def _open_picker(self, client: dict, key: str, target: Optional[Slot] = None) -> None:
        """target を渡すとそのスロットの位置を選び直す（未指定なら新規登録）。"""
        cfg = self._config
        root = self._master.winfo_toplevel()

        def on_pick(x: int, y: int, w: int, h: int) -> None:
            if target is None:
                slot_id = cfg.next_slot_id(key)
                index = len(cfg.get_profile(key, create=True).slots) + 1
                slot = Slot(id=slot_id, label=f"スキル{index}", x=x, y=y, w=w, h=h)
                cfg.add_slot(key, slot)
                self._save_preview(key, slot, picker.shot)
            else:
                cfg.update_slot_rect(key, target.id, x, y, w, h)
                self._save_preview(key, target, picker.shot)
                picker.close()   # 選び直しは1つ選んだら終了

        def on_close() -> None:
            self._overlay.resume()
            self._overlay.refresh_slots()
            self._refresh_rows()

        prof = cfg.get_profile(key)
        guides = [(s.x, s.y) for s in prof.slots if s is not target] if prof else []
        picker = SlotPicker(root, client, cfg.slot_size, on_pick, on_close, guides)

    def _save_preview(self, key: str, slot: Slot, shot: Image.Image) -> None:
        try:
            self._overlay.slots_dir.mkdir(parents=True, exist_ok=True)
            crop = shot.crop((slot.x, slot.y, slot.x + slot.w, slot.y + slot.h))
            crop.save(self._preview_path(key, slot.id))
        except Exception as e:
            print(f"プレビュー保存エラー: {e}")

    # ------------------------------------------------------------ ポーリング

    def _poll(self) -> None:
        text, color = _STATE_TEXT.get(self._overlay.state, ("● 待機中", "#ffaa00"))
        self._state_lbl.config(text=text, fg=color)
        self._detail_lbl.config(text=self._overlay.detail)
        self._master.after(500, self._poll)


class PositionDialog(tk.Toplevel):
    """切り出し位置を数値で指定する小さなダイアログ。"""

    def __init__(self, master: tk.Misc, slot: Slot):
        super().__init__(master)
        self.result: Optional[tuple[int, int]] = None

        self.title(f"{slot.label} の位置")
        self.configure(bg=_BG)
        self.resizable(False, False)
        self.transient(master)

        body = tk.Frame(self, bg=_BG)
        body.pack(padx=16, pady=(14, 8))

        tk.Label(body, text="ゲーム画面の左上からの座標（px）", bg=_BG, fg="#888888",
                 font=("", 8)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self._vars = {}
        for i, (name, label, value) in enumerate((("x", "X", slot.x), ("y", "Y", slot.y))):
            tk.Label(body, text=label, bg=_BG, fg=_FG, width=2, anchor="w"
                     ).grid(row=1 + i, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=str(value))
            ent = tk.Entry(body, textvariable=var, bg="#2a2a2a", fg="white",
                           insertbackground="white", relief="flat", bd=4, width=8)
            ent.grid(row=1 + i, column=1, sticky="w", padx=(8, 0))
            self._vars[name] = var
            if i == 0:
                ent.focus_set()
                ent.select_range(0, "end")

        tk.Label(body, text=f"サイズ {slot.w}x{slot.h}", bg=_BG, fg="#777777",
                 font=("", 8)).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        btns = tk.Frame(self, bg=_BG)
        btns.pack(fill="x", padx=16, pady=(0, 14))
        tk.Button(btns, text="OK", command=self._ok, bg=_ACCENT, fg="white",
                  activebackground="#005fa3", activeforeground="white",
                  relief="flat", padx=16, pady=4, cursor="hand2", bd=0).pack(side="left")
        tk.Button(btns, text="キャンセル", command=self.destroy, bg="#3a3a3a", fg=_FG,
                  activebackground="#4a4a4a", activeforeground=_FG,
                  relief="flat", padx=12, pady=4, cursor="hand2", bd=0
                  ).pack(side="left", padx=(8, 0))

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())

        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + 80
        self.geometry(f"+{x}+{y}")

        self.grab_set()
        self.wait_window(self)

    def _ok(self) -> None:
        try:
            x = int(self._vars["x"].get())
            y = int(self._vars["y"].get())
        except ValueError:
            messagebox.showerror("入力エラー", "座標は整数で入力してください。", parent=self)
            return
        if x < 0 or y < 0:
            messagebox.showerror("入力エラー", "座標は 0 以上で入力してください。", parent=self)
            return
        self.result = (x, y)
        self.destroy()

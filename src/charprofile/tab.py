"""設定ウィンドウの「プロファイル」タブ。

キャラクタープロファイルの追加・削除・並べ替えと、判別に使う識別範囲の指定、
指紋の記録を行う。
"""

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from PIL import Image, ImageTk

from ui.theme import BG, BG_BTN, BG_ROW, FG, MUTED, flat_btn_style
from win.window import get_client_rect

from .identify import client_key, save_fingerprint
from .manager import ProfileManager
from .region_picker import RegionPicker
from .store import CharacterProfile

# 一覧に出す指紋プレビューの寸法。
# 幅は行の余白（名前欄と右側のボタンを除いた分）に収まる範囲にしている
_PREVIEW_H = 24
_PREVIEW_MAX_W = 96


class ProfileTab:
    def __init__(self, master: tk.Misc, manager: ProfileManager, overlay):
        self._master = master
        self._manager = manager
        self._overlay = overlay
        self._previews: dict[str, ImageTk.PhotoImage] = {}

        self._build()
        self.refresh()

    @property
    def _store(self):
        return self._manager.store

    # ------------------------------------------------------------ UI構築

    def _build(self) -> None:
        frame = tk.Frame(self._master, bg=BG)
        frame.pack(fill="both", expand=True)

        # 識別範囲（全プロファイル共通）
        head = tk.Frame(frame, bg=BG)
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(head, text="識別範囲:", bg=BG, fg=FG).pack(side="left")
        self._region_lbl = tk.Label(head, text="", bg=BG, fg=MUTED, font=("", 8))
        self._region_lbl.pack(side="left", padx=(6, 0))
        tk.Button(head, text="範囲を指定", command=self._pick_region,
                  padx=10, pady=2, **flat_btn_style(bg="#2a4a6a", active="#3a5a7a"),
                  ).pack(side="right")

        tk.Label(frame,
                 text="キャラクターごとに中身が違う場所（クイックスロットなど）を囲みます。"
                      "全プロファイル共通で、解像度ごとに持ちます。",
                 bg=BG, fg="#777777", anchor="w", justify="left",
                 wraplength=420, font=("", 8)
                 ).pack(fill="x", padx=12)

        ttk.Separator(frame, orient="horizontal").pack(fill="x", padx=12, pady=6)

        self._rows_frame = tk.Frame(frame, bg=BG)
        self._rows_frame.pack(fill="both", expand=True, padx=12)

        btns = tk.Frame(frame, bg=BG)
        btns.pack(fill="x", padx=12, pady=(8, 4))
        tk.Button(btns, text="追加", command=self._add,
                  padx=12, pady=3, **flat_btn_style(bg="#2a4a6a", active="#3a5a7a"),
                  ).pack(side="left")
        tk.Button(btns, text="現在のプロファイルを複製", command=self._duplicate,
                  padx=12, pady=3, **flat_btn_style(bg=BG_BTN),
                  ).pack(side="left", padx=(8, 0))

        tk.Label(frame,
                 text="一番上が既定プロファイルです。キャラクターを判別できなかったときに使われます。",
                 bg=BG, fg="#777777", anchor="w", justify="left",
                 wraplength=420, font=("", 8)
                 ).pack(fill="x", padx=12, pady=(0, 10))

    # ------------------------------------------------------------ 一覧

    def refresh(self) -> None:
        key = self._current_key()
        if key is None:
            self._region_lbl.config(text="マビノギのウィンドウが見つかりません")
        else:
            rect = self._store.region(key)
            if rect is None:
                self._region_lbl.config(text=f"{key}: 未設定")
            else:
                self._region_lbl.config(
                    text=f"{key}: ({rect[0]}, {rect[1]}) {rect[2]}x{rect[3]}")

        for w in self._rows_frame.winfo_children():
            w.destroy()
        self._previews.clear()

        current_id = self._store.current_id
        for i, profile in enumerate(self._store.profiles):
            self._build_row(profile, key, is_current=profile.id == current_id, index=i)

    def _build_row(self, profile: CharacterProfile, key: Optional[str],
                   is_current: bool, index: int) -> None:
        row = tk.Frame(self._rows_frame, bg=BG_ROW, pady=3)
        row.pack(fill="x", pady=1)

        # ボタンを先に確保しておく。指紋プレビューは幅が可変なので、
        # 先に pack すると横長のときにボタンを押し出してしまう
        tk.Button(row, text="削除", command=lambda: self._remove(profile),
                  padx=8, pady=1,
                  **flat_btn_style(bg="#4a2a2a", fg="#ccaaaa", active="#5a3a3a"),
                  ).pack(side="right", padx=(0, 6))
        tk.Button(row, text="今のキャラを記録", command=lambda: self._record(profile),
                  padx=8, pady=1, **flat_btn_style(bg=BG_BTN),
                  ).pack(side="right", padx=(0, 6))

        arrows = tk.Frame(row, bg=BG_ROW)
        arrows.pack(side="left", padx=(4, 0))
        btn_kw = dict(bg=BG_ROW, fg="#666666", activebackground=BG_ROW,
                      activeforeground=FG, relief="flat", bd=0,
                      font=("", 7), cursor="hand2", pady=0)
        tk.Button(arrows, text="▲", command=lambda: self._move(profile.id, -1), **btn_kw).pack()
        tk.Button(arrows, text="▼", command=lambda: self._move(profile.id, +1), **btn_kw).pack()

        # 適用中の印。既定プロファイル（先頭）も分かるようにしておく
        mark = "●" if is_current else ("既定" if index == 0 else "")
        tk.Label(row, text=mark, bg=BG_ROW, fg="#33cc55" if is_current else MUTED,
                 width=3, font=("", 8)).pack(side="left", padx=(4, 2))

        var = tk.StringVar(value=profile.name)
        ent = tk.Entry(row, textvariable=var, bg="#2a2a2a", fg="white",
                       insertbackground="white", relief="flat", bd=3, width=14)
        ent.pack(side="left")
        ent.bind("<FocusOut>", lambda _, p=profile, v=var: self._rename(p, v))
        ent.bind("<Return>", lambda _, p=profile, v=var: self._rename(p, v))

        # 指紋（プレビュー、無ければ状態を文字で）
        preview = self._load_preview(profile.id, key) if key else None
        if preview is not None:
            photo, truncated = preview
            self._previews[profile.id] = photo
            lbl = tk.Label(row, image=photo, bg=BG_ROW)
            if truncated:
                # 全体はもっと横長で、続きがあることを示す
                # （compound は「テキストに対する画像の位置」なので left で画像が先）
                lbl.config(text="…", compound="left", fg=MUTED)
            lbl.pack(side="left", padx=(8, 0))
        else:
            text = "識別画像なし" if key else "-"
            tk.Label(row, text=text, bg=BG_ROW, fg=MUTED, font=("", 8)
                     ).pack(side="left", padx=(8, 0))

    def _load_preview(self, profile_id: str,
                      key: str) -> Optional[tuple[ImageTk.PhotoImage, bool]]:
        """指紋のプレビューと、横に長すぎて切り詰めたかどうかを返す。

        識別範囲はクイックスロットの並びのように横長になりがちなので、
        縦に合わせて縮小したうえで、はみ出す分は切り落とす
        （幅を潰すと何が写っているのか分からなくなる）。
        """
        path = self._store.fingerprint_path(profile_id, key)
        if not path.exists():
            return None
        try:
            img = Image.open(path).convert("RGB")
            scale = _PREVIEW_H / img.height
            width = max(1, int(img.width * scale))
            img = img.resize((width, _PREVIEW_H), Image.LANCZOS)
            truncated = width > _PREVIEW_MAX_W
            if truncated:
                img = img.crop((0, 0, _PREVIEW_MAX_W, _PREVIEW_H))
            return (ImageTk.PhotoImage(img), truncated)
        except Exception:
            return None

    def _current_key(self) -> Optional[str]:
        client = get_client_rect()
        return None if client is None else client_key(client)

    # ------------------------------------------------------------ 操作

    def _add(self) -> None:
        self._store.add(f"キャラクター{len(self._store.profiles) + 1}")
        self.refresh()
        self._manager.notify_updated()

    def _duplicate(self) -> None:
        current = self._manager.current
        self._store.duplicate(current.id, f"{current.name} のコピー")
        self.refresh()
        self._manager.notify_updated()

    def _remove(self, profile: CharacterProfile) -> None:
        if len(self._store.profiles) <= 1:
            messagebox.showwarning("プロファイル", "最後のプロファイルは削除できません。",
                                   parent=self._master)
            return
        if not messagebox.askyesno(
                "プロファイルの削除",
                f"「{profile.name}」を削除します。\n"
                "このキャラクターのバフ設定・オーバーレイ・識別画像がすべて消えます。",
                parent=self._master):
            return

        was_current = profile.id == self._store.current_id
        if not self._store.remove(profile.id):
            return
        # スキル表示の設定とプレビュー画像も道連れにする
        self._overlay.config.remove_profile(profile.id)
        for path in self._overlay.slots_dir.glob(f"{profile.id}_*.png"):
            path.unlink(missing_ok=True)

        if was_current:
            # 削除で current が移っているので、その内容を各所へ反映させる
            self._manager.apply(self._store.default_profile().id)
        self.refresh()
        self._manager.notify_updated()

    def _rename(self, profile: CharacterProfile, var: tk.StringVar) -> None:
        name = var.get().strip()
        if not name or name == profile.name:
            return
        self._store.rename(profile.id, name)
        self._manager.notify_updated()

    def _move(self, profile_id: str, direction: int) -> None:
        self._store.move(profile_id, direction)
        self.refresh()
        self._manager.notify_updated()

    # ------------------------------------------------------------ 識別範囲・指紋

    def _pick_region(self) -> None:
        client = get_client_rect()
        if client is None:
            self._warn_no_window()
            return

        key = client_key(client)
        if self._store.region(key) is not None and not messagebox.askyesno(
                "識別範囲の変更",
                f"{key} の識別範囲を選び直すと、この解像度の識別画像はすべて破棄されます。\n"
                "各プロファイルで記録し直してください。\n\n続けますか？",
                parent=self._master):
            return

        def on_pick(x: int, y: int, w: int, h: int, shot: Image.Image) -> None:
            self._store.set_region(key, (x, y, w, h))
            self._store.clear_fingerprints(key)
            # 範囲を決めた直後の画面は今のキャラクターのものなので、そのまま記録しておく
            save_fingerprint(self._store, self._store.current_id, key, shot=shot)

        self._overlay.suspend()   # オーバーレイが範囲に重なって写り込むのを避ける
        RegionPicker(self._master.winfo_toplevel(), client, on_pick,
                     on_close=self._on_picker_closed, current=self._store.region(key))

    def _on_picker_closed(self) -> None:
        self._overlay.resume()
        self.refresh()

    def _record(self, profile: CharacterProfile) -> None:
        client = get_client_rect()
        if client is None:
            self._warn_no_window()
            return
        key = client_key(client)
        if self._store.region(key) is None:
            messagebox.showwarning("識別画像の記録",
                                   f"{key} の識別範囲が未設定です。\n"
                                   "先に「範囲を指定」で範囲を決めてください。",
                                   parent=self._master)
            return
        # 記録は既存の識別画像を上書きしてしまうので、誤クリックには一度止まってもらう
        if self._store.has_fingerprint(profile.id, key) and not messagebox.askyesno(
                "識別画像の記録",
                f"「{profile.name}」には {key} の識別画像がすでに登録されています。\n"
                "いまのゲーム画面で上書きします。\n\n続けますか？",
                parent=self._master):
            return
        if not save_fingerprint(self._store, profile.id, key):
            messagebox.showerror("識別画像の記録", "ゲーム画面を取得できませんでした。",
                                 parent=self._master)
            return
        self.refresh()

    def _warn_no_window(self) -> None:
        messagebox.showwarning("プロファイル",
                               "マビノギのウィンドウが見つかりません。\n"
                               "ゲームを起動した状態で実行してください。",
                               parent=self._master)

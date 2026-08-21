"""ウィンドウ上部のプロファイルバー。

左に現在のキャラクター名（クリックで手動切り替え）、その右に自動識別、
右端に設定ウィンドウを開くボタンを置く。
"""

import tkinter as tk
from typing import Callable

from ui.theme import ACCENT, BG, BG_BTN, FG, MUTED, flat_btn_style

from .manager import ProfileManager

# 判別結果のメッセージを消すまでの時間
_MESSAGE_MS = 6000


class ProfileBar:
    def __init__(self, master: tk.Misc, manager: ProfileManager,
                 on_open_settings: Callable[[], None]):
        self._manager = manager
        self._master = master
        self._message_after: str = ""

        self._frame = tk.Frame(master, bg=BG)
        self._frame.pack(fill="x", padx=8, pady=(8, 0))

        self._name_btn = tk.Menubutton(
            self._frame, text="", anchor="w",
            padx=8, pady=3, **flat_btn_style(bg="#2a2a2a", fg="white")
        )
        # メニューは Menubutton の子として作る。別の親にすると Tk が
        # 「it isn't a descendant of ...」で post を拒否し、クリックしても開かない
        self._menu = tk.Menu(self._name_btn, tearoff=0, bg="#2a2a2a", fg=FG,
                             activebackground=ACCENT, activeforeground="white",
                             bd=0, relief="flat")
        self._name_btn.config(menu=self._menu)
        self._name_btn.pack(side="left")

        self._detect_btn = tk.Button(
            self._frame, text="自動識別", command=self._identify,
            padx=10, pady=3, **flat_btn_style(bg="#2a4a6a", active="#3a5a7a"),
        )
        self._detect_btn.pack(side="left", padx=(6, 0))

        tk.Button(
            self._frame, text="設定", command=on_open_settings,
            padx=12, pady=3, **flat_btn_style(bg=BG_BTN),
        ).pack(side="right")

        self._message_lbl = tk.Label(self._frame, text="", bg=BG, fg=MUTED,
                                     anchor="w", font=("", 8))
        self._message_lbl.pack(side="left", fill="x", expand=True, padx=(8, 8))

        self.refresh()

    # ------------------------------------------------------------ 更新

    def refresh(self) -> None:
        """キャラクター名とプロファイル一覧を作り直す。"""
        current = self._manager.current
        self._name_btn.config(text=f"{current.name}  ▼")

        self._menu.delete(0, "end")
        for profile in self._manager.store.profiles:
            mark = "・" if profile.id == current.id else "　"
            self._menu.add_command(
                label=f"{mark}{profile.name}",
                command=lambda pid=profile.id: self._manager.apply(pid),
            )

    def refresh_status(self) -> None:
        """判別中かどうかの表示を更新する（GUI のポーリングから呼ぶ）。"""
        if self._message_after:
            return   # 判別結果を出している間は上書きしない
        text = "キャラクターを判別中..." if self._manager.detecting else ""
        self._message_lbl.config(text=text, fg=MUTED)

    # ------------------------------------------------------------ 操作

    def _identify(self) -> None:
        result = self._manager.identify_now()
        if result.ok:
            self._show_message(f"{result.profile.name} （一致度 {result.score:.2f}）", "#33cc55")
        else:
            self._show_message(f"判別できませんでした: {result.reason}", "#ffaa00")

    def _show_message(self, text: str, color: str) -> None:
        self._message_lbl.config(text=text, fg=color)
        if self._message_after:
            self._master.after_cancel(self._message_after)
        self._message_after = self._master.after(_MESSAGE_MS, self._clear_message)

    def _clear_message(self) -> None:
        self._message_after = ""
        self._message_lbl.config(text="")

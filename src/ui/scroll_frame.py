"""縦スクロール可能なコンテナ。

中身が親の高さを超えたときだけスクロールバーを出す。ウィジェットは self.body に配置する。
"""

import tkinter as tk
from tkinter import ttk

from .theme import BG

_STYLE_NAME = "Dark.Vertical.TScrollbar"


class ScrollFrame(tk.Frame):
    def __init__(self, master, bg: str = BG, **kw):
        super().__init__(master, bg=bg, **kw)
        self._configure_style()

        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self._bar = ttk.Scrollbar(self, orient="vertical", style=_STYLE_NAME,
                                  command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._on_scroll_set)
        self._canvas.pack(side="left", fill="both", expand=True)
        self._bar_shown = False

        self.body = tk.Frame(self._canvas, bg=bg)
        self._win = self._canvas.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", self._on_body_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        # ホイールはマウスがこのフレーム上にある間だけ拾う
        self.bind("<Enter>", self._bind_wheel)
        self.bind("<Leave>", self._unbind_wheel)

    @staticmethod
    def _configure_style() -> None:
        style = ttk.Style()
        style.configure(_STYLE_NAME, background="#3a3a3a", troughcolor="#252525",
                        bordercolor="#252525", arrowcolor="#aaaaaa", relief="flat")
        style.map(_STYLE_NAME, background=[("active", "#4a4a4a")])

    # -------------------------------------------------------------- イベント

    def _on_body_configure(self, _=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        # 中身の幅をキャンバスに合わせる（横スクロールは使わない）
        self._canvas.itemconfigure(self._win, width=event.width)

    def _on_scroll_set(self, first: str, last: str) -> None:
        """スクロールが不要なときはバーを隠す。"""
        need_bar = not (float(first) <= 0.0 and float(last) >= 1.0)
        if need_bar and not self._bar_shown:
            self._bar.pack(side="right", fill="y")
            self._bar_shown = True
        elif not need_bar and self._bar_shown:
            self._bar.pack_forget()
            self._bar_shown = False
        self._bar.set(first, last)

    def _bind_wheel(self, _=None) -> None:
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _=None) -> None:
        self._canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event) -> None:
        if not self._bar_shown:
            return
        self._canvas.yview_scroll(-int(event.delta / 120), "units")

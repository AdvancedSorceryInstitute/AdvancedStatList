"""数値の入力欄をキーボードとマウスホイールで増減できるようにする。

入力欄を選んでいる間、十字キーの上下で 1 段階ずつ動かす。
マウスホイールも同じだが、周りのスクロールを妨げないよう、
ポインタがその入力欄の上にあるときだけ拾う。
"""

import tkinter as tk
from typing import Callable, Optional, Union

Number = Union[int, float]


def bind_spin(widget: tk.Misc, var: tk.Variable, *, step: Number = 1,
              minimum: Optional[Number] = None, maximum: Optional[Number] = None,
              decimals: int = 0,
              active: Optional[Callable[[], bool]] = None) -> None:
    """widget を選んでいる間、十字キー上下とホイールで var の数値を増減する。

    step は 1 回あたりの増減幅、decimals は小数点以下の桁数。
    minimum / maximum を渡すとその範囲に収める。
    active を渡すと、それが False を返す間は受け付けない。
    """

    def apply(direction: int) -> str:
        if active is not None and not active():
            return "break"
        value = _parse(var)
        if value is None:
            return "break"   # 数値として読めないものは触らない
        value += direction * step
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        _store(var, value, decimals)
        if isinstance(widget, tk.Entry):
            widget.icursor("end")
        return "break"

    def on_wheel(event) -> Optional[str]:
        # ホイールはウィジェットを選んでいて、かつその上にポインタがあるときだけ拾う。
        # それ以外は ScrollFrame などのスクロールに譲る（"break" を返さない）
        try:
            focused = widget.focus_get()
        except KeyError:   # Tk 側にしかないウィジェットに焦点があるとき
            return None
        if focused is not widget:
            return None
        if widget.winfo_containing(event.x_root, event.y_root) is not widget:
            return None
        return apply(+1 if event.delta > 0 else -1)

    widget.bind("<Up>", lambda _e: apply(+1))
    widget.bind("<Down>", lambda _e: apply(-1))
    widget.bind("<MouseWheel>", on_wheel)


def _parse(var: tk.Variable) -> Optional[Number]:
    try:
        text = str(var.get()).strip()
    except tk.TclError:
        return None
    if not text:
        return 0   # 空欄からは 0 を起点にする
    try:
        return float(text)
    except ValueError:
        return None


def _store(var: tk.Variable, value: Number, decimals: int) -> None:
    if decimals <= 0:
        var.set(int(round(value)))
    else:
        var.set(f"{round(value, decimals):.{decimals}f}")

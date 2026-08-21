"""GUI の配色とボタンスタイル。

メインウィンドウと設定ウィンドウで同じ見た目にするために共有する。
"""

BG = "#1e1e1e"
BG_ROW = "#252525"
BG_BTN = "#3a3a3a"
FG = "#cccccc"
MUTED = "#888888"
ACCENT = "#0078d4"
LINK = "#8899aa"   # クリックすると編集できる文字（オーバーレイタブの座標と同じ）


def toggle_btn_style(enabled: bool) -> dict:
    """ON/OFF ボタンの配色。"""
    if enabled:
        return {"bg": "#1a5c1a", "fg": "white",
                "activebackground": "#236b23", "activeforeground": "white"}
    return {"bg": BG_BTN, "fg": MUTED,
            "activebackground": "#4a4a4a", "activeforeground": "#aaaaaa"}


def flat_btn_style(bg: str = BG_BTN, fg: str = FG, active: str = "#4a4a4a") -> dict:
    """枠なしボタンの共通指定。"""
    return {"bg": bg, "fg": fg, "activebackground": active, "activeforeground": fg,
            "relief": "flat", "bd": 0, "cursor": "hand2"}

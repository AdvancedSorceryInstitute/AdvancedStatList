"""
バフ追加GUIツール。
アイコン・バナー・サウンドをドラッグ&ドロップし、フォームに入力して「追加」ボタンを押すだけ。
"""

import re
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from PIL import Image, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD

from core.buff_files import install_banner, install_sound, write_config
from core.controller import BUFFS_DIR
from .spin import bind_spin

# システム予約バフID（上書きすると専用の config が壊れるため追加禁止）
RESERVED_BUFF_IDS = {"SongOfTuan"}


def _parse_drop_path(data: str) -> Path:
    """tkinterdnd2 のイベントデータからパスを取り出す。"""
    data = data.strip()
    if data.startswith("{") and data.endswith("}"):
        data = data[1:-1]
    return Path(data)


class DropZone(tk.Frame):
    """ドラッグ&ドロップ + クリックでファイルを受け取るウィジェット。"""

    IDLE_FG = "#555555"
    SET_FG = "#cccccc"
    LABEL_IDLE = "#777777"
    LABEL_SET = "#aaaaaa"
    BG = "#252525"

    def __init__(self, master, label: str, accept: str,
                 preview_size: tuple[int, int] | None = None,
                 on_change: Callable[[], None] | None = None, **kw):
        super().__init__(master, relief="groove", bd=2, bg=self.BG, **kw)
        self.accept = accept          # "image" or "audio"
        self.preview_size = preview_size
        self._on_change = on_change
        self.path: Path | None = None
        self._photo = None

        self._lbl = tk.Label(self, text=label, bg=self.BG, fg=self.LABEL_IDLE, font=("", 9))
        self._lbl.pack(pady=(8, 2))

        self._info = tk.Label(self, text="ドロップ  /  クリック",
                              bg=self.BG, fg=self.IDLE_FG, font=("", 8))
        self._info.pack(pady=(0, 6))

        if preview_size:
            self._prev = tk.Label(self, bg=self.BG)
            self._prev.pack(pady=(0, 8))
            self._prev.bind("<Button-1>", self._on_click)

        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_drop)
        for w in (self, self._lbl, self._info):
            w.bind("<Button-1>", self._on_click)

    def _on_drop(self, event) -> None:
        self.set_path(_parse_drop_path(event.data))

    def _on_click(self, _=None) -> None:
        if self.accept == "image":
            ft = [("画像ファイル", "*.png *.jpg *.jpeg *.bmp"), ("すべて", "*.*")]
        else:
            ft = [("音声ファイル", "*.mp3 *.wav *.ogg"), ("すべて", "*.*")]
        p = filedialog.askopenfilename(filetypes=ft)
        if p:
            self.set_path(Path(p))

    def set_path(self, path: Path) -> None:
        if not path.exists():
            messagebox.showerror("エラー", f"ファイルが見つかりません:\n{path}")
            return
        self.path = path
        self._info.config(text=path.name, fg=self.SET_FG)
        self._lbl.config(fg=self.LABEL_SET)
        if self.preview_size and self.accept == "image":
            self._refresh_preview(path)
        if self._on_change:
            self._on_change()

    def _refresh_preview(self, path: Path) -> None:
        pw, ph = self.preview_size
        img = Image.open(path).convert("RGBA")
        img.thumbnail((pw, ph), Image.LANCZOS)
        bg = Image.new("RGBA", (pw, ph), (37, 37, 37, 255))
        ox = (pw - img.width) // 2
        oy = (ph - img.height) // 2
        bg.paste(img, (ox, oy), img)
        self._photo = ImageTk.PhotoImage(bg)
        self._prev.config(image=self._photo)

    def reset(self) -> None:
        self.path = None
        self._info.config(text="ドロップ  /  クリック", fg=self.IDLE_FG)
        self._lbl.config(fg=self.LABEL_IDLE)
        if self.preview_size and self._photo:
            self._prev.config(image="")
            self._photo = None
        if self._on_change:
            self._on_change()


class AddBuffApp:
    BG = "#1e1e1e"
    FG = "#cccccc"
    ENTRY_BG = "#2a2a2a"

    def __init__(self, master, on_added=None):
        self.root = master
        self._on_added = on_added
        # Tk/Toplevel のときのみウィンドウ設定を行う
        if hasattr(master, "title"):
            master.title("バフ追加")
            master.configure(bg=self.BG)
            master.resizable(False, False)

        self._build_form()
        self._build_dropzones()
        self._build_button()

    # ------------------------------------------------------------------ UI構築

    def _build_form(self) -> None:
        form = tk.Frame(self.root, bg=self.BG)
        form.pack(fill="x", padx=14, pady=(14, 6))

        def field(text: str, row: int, default="", numeric: bool = False) -> tk.StringVar:
            tk.Label(form, text=text, bg=self.BG, fg=self.FG,
                     anchor="w", width=10).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=default)
            e = tk.Entry(form, textvariable=var, bg=self.ENTRY_BG, fg="#ffffff",
                         insertbackground="white", relief="flat", bd=4, width=30)
            e.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=4)
            if numeric:
                # 選んでいる間は十字キー上下とホイールで増減できるようにする
                bind_spin(e, var, minimum=0)
            return var

        self.v_name = field("バフID *", 0)
        self.v_display = field("表示名 *", 1)
        self.v_threshold = field("通知秒数", 2, "30", numeric=True)

        tk.Label(form, text="種別", bg=self.BG, fg=self.FG, anchor="w",
                 width=10).grid(row=3, column=0, sticky="w", pady=4)
        self.v_type = tk.StringVar(value="normal")
        ttk.Combobox(form, textvariable=self.v_type, values=["normal", "music_buff"],
                     state="readonly", width=27).grid(row=3, column=1, sticky="ew",
                                                      padx=(8, 0), pady=4)
        form.columnconfigure(1, weight=1)

    def _sep(self) -> None:
        tk.Frame(self.root, bg="#333333", height=1).pack(fill="x", padx=14, pady=4)

    def _build_dropzones(self) -> None:
        self._sep()

        icons = tk.Frame(self.root, bg=self.BG)
        icons.pack(fill="x", padx=14, pady=4)

        self.dz_active = DropZone(icons, "アクティブアイコン *", "image",
                                  preview_size=(80, 80), width=180, height=160)
        self.dz_active.pack(side="left", expand=True, fill="both", padx=(0, 6))

        self.dz_inactive = DropZone(icons, "非アクティブアイコン", "image",
                                    preview_size=(80, 80), width=180, height=160)
        self.dz_inactive.pack(side="left", expand=True, fill="both")

        self._sep()

        self.dz_banner = DropZone(self.root, "バナー画像(png) *", "image",
                                  preview_size=(360, 56), height=100)
        self.dz_banner.pack(fill="x", padx=14, pady=4)

        # 10秒前バナーは音楽バフでしか使わないので、種別が music_buff のときだけ見せる。
        # 区切り線ごと 1 つの Frame にまとめて pack / pack_forget を切り替える
        self._tuan_frame = tk.Frame(self.root, bg=self.BG)
        tk.Frame(self._tuan_frame, bg="#333333", height=1).pack(fill="x", padx=14, pady=4)
        self.dz_tuan_banner = DropZone(self._tuan_frame, "10秒前バナー画像 (音楽バフ用)",
                                       "image", preview_size=(360, 56), height=100)
        self.dz_tuan_banner.pack(fill="x", padx=14, pady=4)
        # Combobox 選択だけでなく _reset() の v_type.set("normal") にも追随させるため trace で拾う
        self.v_type.trace_add("write", lambda *_: self._update_tuan_visibility())

        self._sep()

        self.dz_sound = DropZone(self.root, "サウンドファイル（wav / mp3）",
                                 "audio", height=60)
        self.dz_sound.pack(fill="x", padx=14, pady=4)

        self._sep()

    def _update_tuan_visibility(self) -> None:
        if self.v_type.get() == "music_buff":
            self._tuan_frame.pack(after=self.dz_banner, fill="x")
        else:
            # normal に戻したあと、見えない欄の値が保存されないように空にする
            self.dz_tuan_banner.reset()
            self._tuan_frame.pack_forget()

    def _build_button(self) -> None:
        self.btn = tk.Button(
            self.root, text="追加", command=self._execute,
            bg="#0078d4", fg="white", activebackground="#005fa3", activeforeground="white",
            relief="flat", padx=24, pady=9, font=("", 11, "bold"), cursor="hand2",
        )
        self.btn.pack(pady=(4, 18))

    # ------------------------------------------------------------------ ロジック

    def _validate(self) -> list[str]:
        errors = []
        name = self.v_name.get().strip()
        if not name:
            errors.append("バフIDを入力してください。")
        elif not re.match(r"^[A-Za-z0-9_]+$", name):
            errors.append("バフIDは半角英数字・アンダースコアのみ使用できます。")
        elif name in RESERVED_BUFF_IDS:
            errors.append(f"バフID '{name}' はシステム予約のため使用できません。")
        if not self.v_display.get().strip():
            errors.append("表示名を入力してください。")
        if not self.v_threshold.get().strip().isdigit():
            errors.append("通知秒数は整数で入力してください。")
        if not self.dz_active.path:
            errors.append("アクティブアイコンを指定してください。")
        if not self.dz_banner.path:
            errors.append("バナー画像を指定してください。")
        return errors

    def _execute(self) -> None:
        errors = self._validate()
        if errors:
            messagebox.showerror("入力エラー", "\n".join(errors))
            return

        name = self.v_name.get().strip()
        buff_dir = BUFFS_DIR / name
        if (buff_dir / "config.yaml").exists():
            if not messagebox.askyesno("上書き確認",
                                       f"buffs/{name}/ が既に存在します。上書きしますか？"):
                return

        buff_dir.mkdir(parents=True, exist_ok=True)

        def cp(src: Path, stem: str) -> None:
            shutil.copy2(src, buff_dir / f"{stem}{src.suffix}")

        cp(self.dz_active.path, "icon_active")
        if self.dz_inactive.path:
            cp(self.dz_inactive.path, "icon_inactive")
        install_banner(buff_dir, self.dz_banner.path)
        if self.v_type.get() == "music_buff" and self.dz_tuan_banner.path:
            install_banner(buff_dir, self.dz_tuan_banner.path, "banner_tuan.png")
        if self.dz_sound.path:
            try:
                install_sound(buff_dir, self.dz_sound.path)
            except Exception as e:
                # config を書かずに戻れば、中途半端なフォルダはバフとして読み込まれない
                messagebox.showerror("変換エラー",
                                     f"WAV を MP3 に変換できませんでした:\n{e}")
                return

        write_config(
            buff_dir, name,
            display_name=self.v_display.get().strip(),
            type_=self.v_type.get(),
            warning_threshold=int(self.v_threshold.get().strip()),
        )

        messagebox.showinfo("完了", f"buffs/{name}/ を生成しました。")
        self._reset()
        if self._on_added:
            self._on_added()

    def _reset(self) -> None:
        self.v_name.set("")
        self.v_display.set("")
        self.v_threshold.set("30")
        self.v_type.set("normal")
        for dz in (self.dz_active, self.dz_inactive, self.dz_banner,
                   self.dz_tuan_banner, self.dz_sound):
            dz.reset()


def main() -> None:
    root = TkinterDnD.Tk()
    AddBuffApp(root)
    root.mainloop()



if __name__ == "__main__":
    main()

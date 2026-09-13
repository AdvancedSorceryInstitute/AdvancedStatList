"""buffs/{name}/ 以下のファイル配置。

バフの追加と設定編集の両方から使う。
"""

import shutil
from pathlib import Path

from PIL import Image

from notify.audio_convert import wav_to_mp3

CONFIG_TEMPLATE = """\
name: {name}
display_name: {display_name}
type: {type}
enabled: {enabled}              # false にするとスキャン・通知をスキップ
warning_threshold: {warning_threshold}      # 何秒前に通知するか
"""


def write_config(buff_dir: Path, name: str, display_name: str, type_: str,
                 warning_threshold: int, enabled: bool = True) -> None:
    (buff_dir / "config.yaml").write_text(
        CONFIG_TEMPLATE.format(
            name=name,
            display_name=display_name,
            type=type_,
            enabled=str(enabled).lower(),
            warning_threshold=warning_threshold,
        ),
        encoding="utf-8",
    )


def install_banner(buff_dir: Path, src: Path, filename: str = "banner.png") -> None:
    # Notifier は banner.png / banner_tuan.png しか探さないので、元の拡張子に関わらず PNG に揃える
    Image.open(src).convert("RGBA").save(buff_dir / filename)


def install_sound(buff_dir: Path, src: Path) -> None:
    """通知音を置く。wav は mp3 に変換する。

    変換に失敗したときは例外を投げ、既存の sound.* には触らない。
    """
    mp3_data: bytes | None = None
    if src.suffix.lower() == ".wav":
        mp3_data = wav_to_mp3(src)

    # 拡張子が変わっても古い音が残らないよう、既存の sound.* を消してから置く
    remove_sound(buff_dir)
    if mp3_data is not None:
        (buff_dir / "sound.mp3").write_bytes(mp3_data)
    else:
        shutil.copy2(src, buff_dir / f"sound{src.suffix}")


def remove_sound(buff_dir: Path) -> None:
    for old in buff_dir.glob("sound.*"):
        old.unlink()

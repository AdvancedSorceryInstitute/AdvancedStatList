import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.controller import ScanController, CONFIG_DIR, CONFIG_PATH
from ui.app import App
from overlay.controller import OverlayController
from charprofile.manager import ProfileManager
from charprofile.store import ProfileStore
from win import single_instance

OVERLAY_CONFIG_PATH = CONFIG_DIR / "overlay.yaml"
OVERLAY_SLOTS_DIR = CONFIG_DIR / "overlay" / "slots"
PROFILES_PATH = CONFIG_DIR / "profiles.yaml"
PROFILES_DIR = CONFIG_DIR / "profiles"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AdvancedStatList")
    parser.add_argument(
        "--allow-multiple", action="store_true",
        help="すでに起動していても二重起動の警告を出さずに起動する（デバッグ用）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    # 二重起動するとスキャンも通知もオーバーレイも二重に動くので既定では止める
    if not args.allow_multiple and not single_instance.acquire():
        single_instance.warn_already_running()
        return

    # プロファイルは監視・スキル表示の双方が参照するので最初に読む
    store = ProfileStore(PROFILES_PATH, PROFILES_DIR, config_path=CONFIG_PATH)
    controller = ScanController(store)
    overlay = OverlayController(OVERLAY_CONFIG_PATH, OVERLAY_SLOTS_DIR,
                                store.default_profile().id)
    manager = ProfileManager(store, controller, overlay)
    manager.start()

    app = App(controller, overlay, manager)
    app.run()


if __name__ == "__main__":
    main()

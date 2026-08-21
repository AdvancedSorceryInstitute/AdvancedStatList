"""配布用の zip を作るスクリプト。

tools/build.py は手元の config/ をそのまま同梱する開発用ビルドなので、
その成果物を配布すると個人の設定（キャラクター名や画面座標）が混ざる。
こちらは git 管理下のファイルだけを集めるため、公開していないバフや
手元だけの設定が zip に入ることがない。

使い方:
    python tools/release.py               # src/version.py の値をバージョンにする
    python tools/release.py --version dev # 試し焼き用に名前だけ変える
"""

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

# このスクリプトは tools/ にあるのでリポジトリのルートは1つ上
ROOT = Path(__file__).parent.parent
APP_NAME = "AdvancedStatList"
# 開発用ビルド（dist/AdvancedStatList）を上書きしないよう出力先を分ける
RELEASE_DIR = ROOT / "dist" / "release"

# exe と一緒に zip へ入れる、git 管理下のパス
BUNDLE_PATHS = ["buffs", "assets", "docs", "LICENSE", "README.md"]


def git(*args: str) -> str:
    """リポジトリのルートで git を実行して標準出力を返す"""
    result = subprocess.run(
        ["git", *args], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip())
    # 日本語のファイル名があるので locale ではなく UTF-8 として解釈する
    return result.stdout.decode("utf-8")


def resolve_version(specified: str | None) -> str:
    """zip 名に使うバージョンを決める。既定は src/version.py の値"""
    if specified:
        return specified
    # アプリ本体を import すると依存ライブラリまで読み込むので、version.py だけを読む
    spec = importlib.util.spec_from_file_location(
        "version", ROOT / "src" / "version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return f"v{module.__version__}"


def warn_if_dirty() -> None:
    """未コミットの変更があれば知らせる（zip には作業ツリーの内容が入るため）"""
    if git("status", "--porcelain", "--untracked-files=no").strip():
        # PyInstaller の出力に埋もれないよう即座に出す
        print("警告: 未コミットの変更があります。zip にはその内容が入ります", flush=True)


def tracked_files(rel_path: str) -> list[str]:
    """rel_path 以下の git 管理下のファイルをリポジトリ相対パスで返す"""
    # -z を付けると日本語のファイル名がクォートされずそのまま出る
    return [p for p in git("ls-files", "-z", "--", rel_path).split("\0") if p]


def copy_files(rel_paths: list[str], dest_root: Path) -> None:
    """リポジトリ相対パスのファイルを、同じ構成で dest_root 以下へ複製する"""
    for rel in rel_paths:
        dst = dest_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)


def build_exe() -> Path:
    """PyInstaller で exe 一式を作り、その出力先を返す"""
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "main.spec", "--clean", "--noconfirm",
         "--distpath", str(RELEASE_DIR)],
        cwd=ROOT / "src",
    )
    if result.returncode != 0:
        print("ビルド失敗")
        sys.exit(1)
    return RELEASE_DIR / APP_NAME


def main() -> None:
    parser = argparse.ArgumentParser(description="配布用の zip を作る")
    parser.add_argument(
        "--version", help="zip 名に使うバージョン（省略時は src/version.py の値）")
    args = parser.parse_args()

    version = resolve_version(args.version)
    warn_if_dirty()

    # 前回の成果物が残っていると混ざるので作り直す
    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR)

    app_dir = build_exe()

    # config.yaml は初回起動時に config.sample.yaml から生成されるので同梱しない
    config_dst = app_dir / "config"
    config_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "config" / "config.sample.yaml",
                 config_dst / "config.sample.yaml")

    total = 0
    buff_names: list[str] = []
    for rel_path in BUNDLE_PATHS:
        files = tracked_files(rel_path)
        copy_files(files, app_dir)
        total += len(files)
        if rel_path == "buffs":
            buff_names = sorted({f.split("/")[1] for f in files})

    zip_path = Path(shutil.make_archive(
        str(ROOT / "dist" / f"{APP_NAME}-{version}"), "zip",
        root_dir=RELEASE_DIR, base_dir=APP_NAME))

    print()
    print(f"同梱したバフ({len(buff_names)}種): {', '.join(buff_names)}")
    print(f"同梱ファイル数: {total} + config.sample.yaml")
    print(f"完了: {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()

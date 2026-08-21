"""配布用の zip を作り、必要なら GitHub Release まで作るスクリプト。

tools/build.py は手元の config/ をそのまま同梱する開発用ビルドなので、
その成果物を配布すると個人の設定（キャラクター名や画面座標）が混ざる。
こちらは git 管理下のファイルだけを集めるため、公開していないバフや
手元だけの設定が zip に入ることがない。

バージョンは src/version.py の値を使うので、どこにも書かずに実行できる。

使い方:
    python tools/release.py               # zip を作るだけ
    python tools/release.py --publish     # タグ・GitHub Release まで作る
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


def fail(message: str) -> None:
    print(message)
    sys.exit(1)


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
    """zip 名とタグに使うバージョンを決める。既定は src/version.py の値"""
    if specified:
        return specified
    # アプリ本体を import すると依存ライブラリまで読み込むので、version.py だけを読む
    spec = importlib.util.spec_from_file_location(
        "version", ROOT / "src" / "version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return f"v{module.__version__}"


def is_dirty() -> bool:
    """追跡中のファイルに未コミットの変更があるか"""
    return bool(git("status", "--porcelain", "--untracked-files=no").strip())


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
        fail("ビルド失敗")
    return RELEASE_DIR / APP_NAME


def build_zip(version: str) -> Path:
    """exe 一式と同梱物をまとめた配布用 zip を作る"""
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
    return zip_path


# ---------------------------------------------------------------- GitHub Release


def check_publishable(version: str) -> None:
    """公開してよい状態か、ビルド前に確かめる"""
    if shutil.which("gh") is None:
        fail("gh コマンドが見つかりません。GitHub CLI を入れて gh auth login してください")
    if is_dirty():
        fail("未コミットの変更があります。コミットしてから公開してください")

    # 同じタグが別のコミットに付いていたら、バージョンの上げ忘れの可能性が高い
    if git("tag", "--list", version).strip():
        tagged = git("rev-list", "-n", "1", version).strip()
        if tagged != git("rev-parse", "HEAD").strip():
            fail(f"タグ {version} は HEAD 以外のコミットを指しています。"
                 "src/version.py を上げるか、タグを付け直してください")

    if release_exists(version):
        fail(f"リリース {version} は既にあります。"
             "src/version.py を上げるか、gh release delete で消してください")

    # タグを push すると HEAD のコミットも一緒に送られるので、
    # main を push し忘れているとリリースだけ先行してしまう
    if git("rev-list", "--count", "origin/main..HEAD").strip() != "0":
        print("警告: origin/main に push していないコミットがあります")


def release_exists(version: str) -> bool:
    result = subprocess.run(
        ["gh", "release", "view", version], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def push_tag(version: str) -> None:
    """version のタグが無ければ HEAD に作り、リモートへ送る"""
    if not git("tag", "--list", version).strip():
        git("tag", "-a", version, "-m", version)
        print(f"タグを作成: {version}")
    git("push", "origin", version)
    print(f"タグを push: {version}")


def create_release(version: str, zip_path: Path, draft: bool,
                   notes_file: str | None) -> None:
    cmd = ["gh", "release", "create", version, str(zip_path),
           "--title", f"{APP_NAME} {version}"]
    if notes_file:
        cmd += ["--notes-file", notes_file]
    else:
        # コミット履歴から自動生成する。内容は後から Web で直せる
        cmd.append("--generate-notes")
    if draft:
        cmd.append("--draft")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        fail("リリースの作成に失敗しました")


def main() -> None:
    parser = argparse.ArgumentParser(description="配布用の zip を作る")
    parser.add_argument(
        "--version", help="zip 名とタグに使うバージョン（省略時は src/version.py の値）")
    parser.add_argument(
        "--publish", action="store_true",
        help="zip を作ったあと、タグを push して GitHub Release を作る")
    parser.add_argument(
        "--draft", action="store_true", help="--publish のとき下書きとして作る")
    parser.add_argument(
        "--notes-file", help="リリース説明文のファイル（省略時はコミットから自動生成）")
    args = parser.parse_args()

    version = resolve_version(args.version)
    print(f"バージョン: {version}", flush=True)

    if args.publish:
        # ビルドには時間がかかるので、公開できない状態なら先に止める
        check_publishable(version)
    elif is_dirty():
        # PyInstaller の出力に埋もれないよう即座に出す
        print("警告: 未コミットの変更があります。zip にはその内容が入ります", flush=True)

    zip_path = build_zip(version)

    if args.publish:
        print()
        push_tag(version)
        create_release(version, zip_path, args.draft, args.notes_file)


if __name__ == "__main__":
    main()

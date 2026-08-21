import subprocess
import shutil
import sys
from pathlib import Path

# このスクリプトは tools/ にあるのでリポジトリのルートは1つ上
root = Path(__file__).parent.parent

result = subprocess.run(
    [sys.executable, '-m', 'PyInstaller', 'main.spec', '--clean', '--noconfirm',
     '--distpath', str(root / 'dist')],
    cwd=root / 'src',
)
if result.returncode != 0:
    print('ビルド失敗')
    sys.exit(1)

dist = root / 'dist' / 'AdvancedStatList'

# 設定は手元の config/ をそのまま複製する。
# config.yaml の解像度依存の座標も、profiles.yaml / overlay.yaml と
# それらが参照する profiles/・overlay/slots/ の画像も含めるので、
# ソースから動かしていたときと同じ状態で exe が起動する。
# 個人の設定が入るため、この成果物をそのまま配布しないこと
config_src = root / 'config'
config_dst = dist / 'config'
if config_dst.exists():
    shutil.rmtree(config_dst)
shutil.copytree(config_src, config_dst,
                ignore=shutil.ignore_patterns('__pycache__'))

# config.yaml をまだ生成していない環境からビルドしても起動できるようにする
config_yaml = config_dst / 'config.yaml'
if not config_yaml.exists():
    shutil.copy2(config_src / 'config.sample.yaml', config_yaml)

buffs_dst = dist / 'buffs'
if buffs_dst.exists():
    shutil.rmtree(buffs_dst)
shutil.copytree(root / 'buffs', buffs_dst)

assets_dst = dist / 'assets'
if assets_dst.exists():
    shutil.rmtree(assets_dst)
shutil.copytree(root / 'assets', assets_dst)

print(f'完了: {dist / "AdvancedStatList.exe"}')

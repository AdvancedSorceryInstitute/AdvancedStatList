"""プロファイルの切り替えと自動判別のトリガー。

切り替えの入口をここ1つにまとめ、バフ監視・スキル表示・GUI はここからの
通知を受けて更新する。判別そのものは identify.py が持ち、
どのプロファイルかを返すだけにしてある。

判別のきっかけは3つ。
  1. アプリ起動時
  2. マビノギのウィンドウが消滅 -> 再出現したとき
  3. 「自動識別」ボタン
"""

import time
from typing import Callable, Optional

from win.window import find_hwnd

from .identify import IdentifyResult, identify
from .store import CharacterProfile, ProfileStore


class ProfileManager:
    def __init__(self, store: ProfileStore, controller, overlay):
        self._store = store
        self._controller = controller
        self._overlay = overlay
        self._listeners: list[Callable[[CharacterProfile], None]] = []

        self._last_hwnd: Optional[int] = None
        self._retries_left = 0        # 0 なら判別待ちではない
        self._next_try_at = 0.0

        self.last_result: Optional[IdentifyResult] = None

    # ------------------------------------------------------------ 参照

    @property
    def store(self) -> ProfileStore:
        return self._store

    @property
    def current(self) -> CharacterProfile:
        return self._store.current()

    @property
    def detecting(self) -> bool:
        """ウィンドウ出現後の判別リトライ中か。"""
        return self._retries_left > 0

    def add_listener(self, callback: Callable[[CharacterProfile], None]) -> None:
        """プロファイルが切り替わったときに呼ばれる。GUI の再構築に使う。"""
        self._listeners.append(callback)

    # ------------------------------------------------------------ 起動

    def start(self) -> None:
        """保存されていたプロファイルを適用し、判別を予約する。

        GUI 構築前に呼ぶ（listeners はまだ登録されていない）。
        """
        self._apply_to_components(self.current)
        self._last_hwnd = find_hwnd()
        if self._last_hwnd is not None:
            self._begin_detect()

    # ------------------------------------------------------------ 切り替え

    def apply(self, profile_id: str) -> bool:
        """プロファイルを適用する（手動選択・自動判別の共通の入口）。"""
        profile = self._store.find(profile_id)
        if profile is None:
            return False
        if profile.id == self._store.current_id:
            return True   # 同じものへの切り替えでタイマーを流さない

        self._store.set_current(profile.id)
        self._apply_to_components(profile)
        for callback in self._listeners:
            callback(profile)
        print(f"プロファイル切り替え: {profile.name}")
        return True

    def _apply_to_components(self, profile: CharacterProfile) -> None:
        self._controller.apply_profile(profile)
        self._overlay.set_profile(profile.id)

    def notify_updated(self) -> None:
        """プロファイルの中身（名前・並び順など）が変わったことを GUI へ伝える。"""
        for callback in self._listeners:
            callback(self.current)

    # ------------------------------------------------------------ 判別

    def identify_now(self) -> IdentifyResult:
        """即座に判別する（「自動識別」ボタン）。成功すれば切り替える。"""
        result = identify(self._store)
        self.last_result = result
        if result.ok:
            self.apply(result.profile.id)
        return result

    def _begin_detect(self) -> None:
        """ウィンドウ出現後の判別を始める。

        出現直後はログイン画面やロード中でクイックスロットがまだ描かれていない。
        確定するまで一定間隔で試し、上限まで確定しなければ諦める。
        諦めても切り替えは行わず、今のプロファイルをそのまま使う。
        """
        self._retries_left = max(1, self._store.detect.retry_count)
        self._next_try_at = time.time()

    def _end_detect(self) -> None:
        self._retries_left = 0

    def poll(self) -> None:
        """GUI のポーリング（500ms）から呼ぶ。

        ウィンドウの消滅 -> 再出現を検出して判別を始め、リトライを進める。
        ハンドル値の変化も見るのは、500ms 以内に終了と起動が続いた場合を
        取りこぼさないため。
        """
        hwnd = find_hwnd()
        if hwnd != self._last_hwnd:
            self._last_hwnd = hwnd
            if hwnd is None:
                self._end_detect()
            else:
                self._begin_detect()

        if self._retries_left <= 0 or time.time() < self._next_try_at:
            return

        result = identify(self._store)
        self.last_result = result
        if result.ok:
            self._end_detect()
            self.apply(result.profile.id)
            return

        self._retries_left -= 1
        # 識別範囲や指紋が未設定なら、待っても状況は変わらないので粘らない
        if not result.retriable or self._retries_left <= 0:
            print(f"キャラクターを判別できませんでした: {result.reason}")
            # 別キャラの設定を勝手に当てるより、今のプロファイルを残すほうが害が小さい
            self._end_detect()
            return
        self._next_try_at = time.time() + self._store.detect.retry_interval

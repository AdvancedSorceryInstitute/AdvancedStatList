"""音声ファイルの変換ユーティリティ。

通知音の再生は MCI の mpegvideo デバイス（MP3 前提）で行うため、
WAV を登録するときはここで MP3 に変換してから保存する。
エンコーダ（lameenc）は wheel に同梱されているので外部ツールは不要。
"""

import wave
from pathlib import Path

import lameenc
import numpy as np

MP3_BITRATE = 128        # kbps
MP3_QUALITY = 2          # 0=最高品質/低速, 9=低品質/高速

# LAME が出力できるサンプリングレート。これ以外は近いレートへリサンプルさせる
_LAME_RATES = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)


def _to_int16(raw: bytes, sample_width: int) -> np.ndarray:
    """WAV の生データを 16bit PCM の配列に変換する。"""
    if sample_width == 1:
        # 8bit WAV は符号なし（0-255）
        return (np.frombuffer(raw, dtype=np.uint8).astype(np.int16) - 128) << 8
    if sample_width == 2:
        return np.frombuffer(raw, dtype="<i2").copy()
    if sample_width == 3:
        # 24bit はリトルエンディアン3バイト詰め。上位2バイトだけ使う
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        return (b[:, 1].astype(np.int16) | (b[:, 2].astype(np.int8).astype(np.int16) << 8))
    if sample_width == 4:
        return (np.frombuffer(raw, dtype="<i4") >> 16).astype(np.int16)
    raise ValueError(f"対応していないビット深度です（{sample_width * 8}bit）")


def wav_to_mp3(src: Path, bitrate: int = MP3_BITRATE) -> bytes:
    """WAV ファイルを読み込み、MP3 のバイト列を返す。"""
    with wave.open(str(src), "rb") as w:
        channels = w.getnchannels()
        sample_width = w.getsampwidth()
        sample_rate = w.getframerate()
        raw = w.readframes(w.getnframes())

    if channels < 1:
        raise ValueError("チャンネル数を取得できませんでした。")

    samples = _to_int16(raw, sample_width)
    if channels > 2:
        # LAME はモノラルかステレオのみ。先頭2chだけ残す
        samples = samples.reshape(-1, channels)[:, :2].reshape(-1)
        channels = 2

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(bitrate)
    encoder.set_in_sample_rate(sample_rate)
    encoder.set_out_sample_rate(min(_LAME_RATES, key=lambda r: abs(r - sample_rate)))
    encoder.set_channels(channels)
    encoder.set_quality(MP3_QUALITY)
    return bytes(encoder.encode(samples.tobytes())) + bytes(encoder.flush())

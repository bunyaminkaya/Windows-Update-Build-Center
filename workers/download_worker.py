from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import requests
from PySide6.QtCore import QObject, Signal


class DownloadWorker(QObject):
    progress = Signal(str, int, int, float, float)
    status = Signal(str, str)
    finished = Signal(str, str)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, job_id: str, url: str, target_path: str):
        super().__init__()
        self.job_id = job_id
        self.url = url
        self.target_path = Path(target_path)
        self.part_path = Path(str(target_path) + ".part")
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._cancel_event = threading.Event()

    def pause(self):
        self._pause_event.clear()
        self.status.emit(self.job_id, "Duraklatıldı")

    def resume(self):
        self._pause_event.set()
        self.status.emit(self.job_id, "İndiriliyor")

    def cancel(self):
        self._cancel_event.set()
        self._pause_event.set()

    def run(self):
        try:
            self.target_path.parent.mkdir(parents=True, exist_ok=True)
            existing = self.part_path.stat().st_size if self.part_path.exists() else 0
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            }
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"

            with requests.get(
                self.url,
                headers=headers,
                stream=True,
                timeout=(20, 60),
                allow_redirects=True,
            ) as response:
                response.raise_for_status()

                # Some servers ignore Range. Restart safely in that case.
                if existing > 0 and response.status_code != 206:
                    existing = 0

                content_length = int(response.headers.get("Content-Length", 0) or 0)
                total = existing + content_length if content_length else 0
                mode = "ab" if existing > 0 else "wb"
                downloaded = existing
                started = time.monotonic()
                last_time = started
                last_bytes = downloaded
                last_emit_time = started
                smoothed_speed = 0.0
                smoothed_eta = -1.0
                speed_alpha = 0.22
                eta_alpha = 0.16

                self.status.emit(self.job_id, "İndiriliyor")

                with open(self.part_path, mode) as file:
                    for chunk in response.iter_content(chunk_size=512 * 1024):
                        if self._cancel_event.is_set():
                            self.cancelled.emit(self.job_id)
                            return

                        self._pause_event.wait()
                        if self._cancel_event.is_set():
                            self.cancelled.emit(self.job_id)
                            return

                        if not chunk:
                            continue

                        file.write(chunk)
                        downloaded += len(chunk)
                        now = time.monotonic()
                        elapsed = max(now - last_time, 0.001)
                        instant_speed = (downloaded - last_bytes) / elapsed
                        last_time = now
                        last_bytes = downloaded

                        # IDM-benzeri daha kararlı hız/kalan süre görünümü:
                        # Anlık hızdaki sıçramaları EMA ile yumuşat, fakat kullanıcıya
                        # hala gerçek zamanlı tepki verecek kadar hızlı güncelle.
                        if instant_speed > 0:
                            if smoothed_speed <= 0:
                                smoothed_speed = instant_speed
                            else:
                                smoothed_speed = (
                                    speed_alpha * instant_speed
                                    + (1.0 - speed_alpha) * smoothed_speed
                                )

                        raw_eta = (
                            (total - downloaded) / smoothed_speed
                            if total > 0 and smoothed_speed > 0
                            else -1.0
                        )
                        if raw_eta >= 0:
                            if smoothed_eta < 0:
                                smoothed_eta = raw_eta
                            else:
                                # Kalan süre yukarı/aşağı zıplamasın. Büyük ağ değişimlerinde
                                # yine kademeli şekilde yeni değere yaklaşır.
                                smoothed_eta = (
                                    eta_alpha * raw_eta
                                    + (1.0 - eta_alpha) * smoothed_eta
                                )

                        # UI'yi yaklaşık 4 kez/sn güncelle. Bu hem gerçek zamanlı görünür,
                        # hem de yüzlerce UUP dosyasında ana arayüzü gereksiz yormaz.
                        if now - last_emit_time >= 0.25 or (total > 0 and downloaded >= total):
                            self.progress.emit(
                                self.job_id,
                                downloaded,
                                total,
                                smoothed_speed,
                                smoothed_eta,
                            )
                            last_emit_time = now

            if self.target_path.exists():
                self.target_path.unlink()
            os.replace(self.part_path, self.target_path)
            self.finished.emit(self.job_id, str(self.target_path))
        except Exception as exc:
            self.failed.emit(self.job_id, str(exc))

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
import logging

from PySide6.QtCore import QObject, QThread, Signal, QTimer

from workers.download_worker import DownloadWorker
from services.windows_update_service import WindowsUpdateService
from app.paths import DOWNLOAD_STATE_PATH

logger = logging.getLogger(__name__)


@dataclass
class DownloadJob:
    id: str
    filename: str
    url: str
    target_path: str
    architecture: str = ""
    size_label: str = "—"
    status: str = "Kuyrukta"
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0
    eta: float = -1.0
    error: str = ""
    retry_count: int = 0
    max_retries: int = 5
    batch_id: str = ""
    batch_kind: str = ""
    batch_meta: dict = field(default_factory=dict)
    verification_status: str = "Bekleniyor"
    sha256: str = ""
    signature: str = ""
    verification_message: str = ""
    source: str = ""


class DownloadManager(QObject):
    RUNNING_STATUSES = {"Başlatılıyor", "İndiriliyor", "Devam ediyor"}
    QUEUED_STATUSES = {"Kuyrukta"}
    PAUSED_STATUSES = {"Duraklatıldı"}
    COMPLETED_STATUSES = {"Tamamlandı"}
    CANCELLED_STATUSES = {"İptal edildi", "İptal Edildi"}
    FAILED_STATUSES = {"Hata"}
    job_added = Signal(str)
    job_updated = Signal(str)
    request_open_manager = Signal()
    batch_completed = Signal(str, object)
    job_schedule_changed = Signal()

    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.jobs: dict[str, DownloadJob] = {}
        self._threads: dict[str, QThread] = {}
        self._workers: dict[str, DownloadWorker] = {}
        self._queue: list[str] = []
        self.max_concurrent = 3
        # Global queue control used by the IDM-style toolbar.  While paused,
        # active workers stay suspended and _pump_queue never starts a new job.
        self._global_paused = False
        self._shutting_down = False
        self._schedule_enabled = False
        self._schedule_start = 1 * 60
        self._schedule_end = 7 * 60
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(30000)
        self._schedule_timer.timeout.connect(self._pump_queue)
        self._state_file = DOWNLOAD_STATE_PATH
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

        # Download progress may arrive many times per second. Writing the full
        # state file on every progress signal blocks the GUI thread badly for
        # large UUP batches. Persist changes in a single delayed write instead.
        self._state_save_timer = QTimer(self)
        self._state_save_timer.setSingleShot(True)
        self._state_save_timer.setInterval(1200)
        self._state_save_timer.timeout.connect(self._flush_state)
        self._state_dirty = False

        self._load_state()
        self._pump_queue()

    def _part_path_for(self, job: DownloadJob) -> Path:
        return Path(str(job.target_path) + ".part")

    def _save_state(self, immediate: bool = False):
        """Schedule state persistence without blocking frequent progress events."""
        self._state_dirty = True
        if immediate:
            self._flush_state()
            return
        if not self._state_save_timer.isActive():
            self._state_save_timer.start()

    def _flush_state(self):
        if not self._state_dirty:
            return
        try:
            payload = {
                "jobs": [asdict(job) for job in self.jobs.values()],
                "queue": list(self._queue),
            }
            # Compact JSON reduces both serialization time and disk I/O.
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            temp_file = self._state_file.with_suffix(".json.tmp")
            temp_file.write_text(encoded, encoding="utf-8")
            temp_file.replace(self._state_file)
            self._state_dirty = False
        except Exception:
            # Keep the dirty flag so the next scheduled save can retry.
            self._state_dirty = True

    def _load_state(self):
        if not self._state_file.exists():
            return
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception:
            return

        for item in payload.get("jobs", []):
            try:
                job = DownloadJob(**item)
            except TypeError:
                # backward compatibility with older saved states
                item.setdefault("retry_count", 0)
                item.setdefault("max_retries", 5)
                item.setdefault("batch_id", "")
                item.setdefault("batch_kind", "")
                item.setdefault("batch_meta", {})
                item.setdefault("verification_status", "Bekleniyor")
                item.setdefault("sha256", "")
                item.setdefault("signature", "")
                item.setdefault("verification_message", "")
                item.setdefault("source", "")
                job = DownloadJob(**item)
            self.jobs[job.id] = job

        saved_queue = payload.get("queue", [])
        queue_candidates = [jid for jid in saved_queue if jid in self.jobs]
        seen = set(queue_candidates)

        resumable_statuses = self.RUNNING_STATUSES | self.QUEUED_STATUSES
        resumable_statuses |= {"Devam için yeniden deneniyor"}

        for jid, job in self.jobs.items():
            target = Path(job.target_path)
            part = self._part_path_for(job)
            status = str(job.status or "").strip()

            if target.exists() and status == "Tamamlandı":
                continue
            if status in self.CANCELLED_STATUSES | self.FAILED_STATUSES | self.COMPLETED_STATUSES:
                continue
            if status == "Duraklatıldı":
                # Explicitly paused jobs stay paused across restarts.
                continue

            should_resume = status in resumable_statuses or status.startswith("Devam için yeniden deneniyor")
            if should_resume or part.exists():
                job.status = "Kuyrukta"
                job.speed = 0
                job.eta = -1
                if part.exists():
                    try:
                        job.downloaded = part.stat().st_size
                    except Exception:
                        pass
                if jid not in seen:
                    queue_candidates.append(jid)
                    seen.add(jid)

        self._queue = queue_candidates

    @staticmethod
    def _normalize_batch_value(value) -> str:
        return str(value or "").strip().lower()

    def build_batch_key(self, batch_meta=None, batch_kind="") -> str:
        meta = dict(batch_meta or {})
        kind = self._normalize_batch_value(batch_kind or meta.get("batch_kind"))
        if kind != "uup_iso":
            return ""
        parts = [
            kind,
            self._normalize_batch_value(meta.get("build")),
            self._normalize_batch_value(meta.get("architecture")),
            self._normalize_batch_value(meta.get("language")),
            self._normalize_batch_value(meta.get("edition")),
        ]
        if any(not value for value in parts[1:]):
            return ""
        return "|".join(parts)

    def _batch_jobs(self, batch_id: str):
        return [job for job in self.jobs.values() if job.batch_id == batch_id]

    def _describe_batch_state(self, jobs) -> dict:
        statuses = {str(job.status or "") for job in jobs}
        completed = sum(1 for job in jobs if job.status == "Tamamlandı")
        total = len(jobs)

        if total and completed == total:
            state = "completed"
            message = "Bu sürüm daha önce tamamen indirildi."
        elif any(status in {"İndiriliyor", "Başlatılıyor", "Devam ediyor"} for status in statuses):
            state = "downloading"
            message = "Bu indirme şu anda devam ediyor."
        elif any(status.startswith("Devam için yeniden deneniyor") for status in statuses):
            state = "retrying"
            message = "Bu indirme yarım kaldı ve otomatik olarak devam etmeyi bekliyor."
        elif any(status == "Duraklatıldı" for status in statuses):
            state = "paused"
            message = "Bu indirme duraklatılmış durumda. Mevcut indirmeye devam edebilirsiniz."
        elif any(status == "Kuyrukta" for status in statuses):
            state = "queued"
            message = "Bu indirme zaten kuyrukta bekliyor."
        elif any(status == "Hata" for status in statuses):
            state = "failed"
            message = "Bu indirme daha önce hata verdi. Yeni kopya eklemek yerine mevcut indirmeyi yeniden deneyin."
        elif any(status in {"İptal edildi", "İptal Edildi"} for status in statuses):
            state = "cancelled"
            message = "Bu indirme daha önce iptal edildi. Yeni kopya eklemek yerine mevcut indirmeyi yeniden deneyin."
        else:
            state = "existing"
            message = "Bu indirme grubu zaten mevcut."

        return {
            "state": state,
            "message": message,
            "completed": completed,
            "total": total,
            "statuses": sorted(statuses),
        }

    def find_existing_batch(self, batch_meta=None, batch_kind=""):
        wanted_key = self.build_batch_key(batch_meta, batch_kind)
        if not wanted_key:
            return None

        grouped = {}
        for job in self.jobs.values():
            if not job.batch_id:
                continue
            grouped.setdefault(job.batch_id, []).append(job)

        matches = []
        for batch_id, jobs in grouped.items():
            first = jobs[0]
            current_key = self.build_batch_key(first.batch_meta, first.batch_kind)
            if current_key != wanted_key:
                continue
            info = self._describe_batch_state(jobs)
            info.update({
                "batch_id": batch_id,
                "batch_key": wanted_key,
                "batch_meta": dict(first.batch_meta or {}),
                "batch_kind": first.batch_kind,
            })
            matches.append(info)

        if not matches:
            return None

        priority = {
            "downloading": 0,
            "retrying": 1,
            "paused": 2,
            "queued": 3,
            "completed": 4,
            "failed": 5,
            "cancelled": 6,
            "existing": 7,
        }
        matches.sort(key=lambda item: priority.get(item["state"], 99))
        return matches[0]

    def add_download(self, package, target_path: str) -> str:
        job_id = uuid.uuid4().hex
        precheck = None
        if str(getattr(package, "source", "")) == "Microsoft Update Catalog":
            precheck = WindowsUpdateService.pre_download_check(package, WindowsUpdateService.snapshot())
        job = DownloadJob(
            id=job_id,
            filename=package.filename,
            url=package.direct_url,
            target_path=target_path,
            architecture=getattr(package, "architecture", ""),
            size_label=getattr(package, "size", "—"),
            source=getattr(package, "source", ""),
        )
        if precheck is False:
            job.status = "Hata"
            job.error = "İndirme ön kontrolü başarısız: HTTPS/Microsoft kaynağı, mimari veya paket rolü uygun değil."
            job.verification_status = "Ön kontrol başarısız"
        else:
            self._queue.append(job_id)
        self.jobs[job_id] = job
        self._save_state()
        self.job_added.emit(job_id)
        self.job_updated.emit(job_id)
        self._pump_queue()
        self.request_open_manager.emit()
        return job_id

    def add_downloads(self, items, batch_meta=None, batch_kind="", open_manager=True) -> list[str]:
        ids = []
        batch_meta = dict(batch_meta or {})
        # Duplicate UUP/ISO groups are intentionally allowed. Each request
        # receives a new batch id so users can download the same build,
        # architecture, language and edition as many times as they want.
        batch_id = uuid.uuid4().hex if batch_meta else ""
        for package, target_path in items:
            job_id = uuid.uuid4().hex
            precheck = None
            if str(getattr(package, "source", "")) == "Microsoft Update Catalog":
                precheck = WindowsUpdateService.pre_download_check(package, WindowsUpdateService.snapshot())
            job = DownloadJob(
                id=job_id,
                filename=package.filename,
                url=package.direct_url,
                target_path=target_path,
                architecture=getattr(package, "architecture", ""),
                size_label=getattr(package, "size", "—"),
                source=getattr(package, "source", ""),
                batch_id=batch_id,
                batch_kind=batch_kind,
                batch_meta=batch_meta,
            )
            if precheck is False:
                job.status = "Hata"
                job.error = "İndirme ön kontrolü başarısız: HTTPS/Microsoft kaynağı, mimari veya paket rolü uygun değil."
                job.verification_status = "Ön kontrol başarısız"
            else:
                self._queue.append(job_id)
            self.jobs[job_id] = job
            ids.append(job_id)
            self.job_added.emit(job_id)
            self.job_updated.emit(job_id)
        self._save_state()
        self._pump_queue()
        if ids and open_manager:
            self.request_open_manager.emit()
        return ids

    # ── Hız sınırı ve zamanlama (ayarlardan) ──
    def apply_settings(self, downloads: dict) -> None:
        """Ayarlar > İndirme: eşzamanlı sayı, hız sınırı ve gece zamanlaması."""
        downloads = downloads or {}
        self.set_max_concurrent(downloads.get("max_concurrent", self.max_concurrent))
        try:
            kbps = int(downloads.get("speed_limit_kbps", 0) or 0)
        except (TypeError, ValueError):
            kbps = 0
        DownloadWorker.speed_limit_bps = max(0, kbps) * 1024
        self._schedule_enabled = bool(downloads.get("schedule_enabled", False))
        self._schedule_start = self._parse_clock(downloads.get("schedule_start"), 1 * 60)
        self._schedule_end = self._parse_clock(downloads.get("schedule_end"), 7 * 60)
        if self._schedule_enabled and not self._schedule_timer.isActive():
            self._schedule_timer.start()
        elif not self._schedule_enabled:
            self._schedule_timer.stop()
        self._pump_queue()
        self.job_schedule_changed.emit()

    @staticmethod
    def _parse_clock(value, default_minutes: int) -> int:
        try:
            hours, minutes = str(value).split(":", 1)
            return max(0, min(23, int(hours))) * 60 + max(0, min(59, int(minutes)))
        except Exception:
            return default_minutes

    def schedule_open(self, now=None) -> bool:
        """Zamanlama kapalıysa ya da şu an izin verilen aralıktaysa True."""
        if not self._schedule_enabled:
            return True
        if now is None:
            from datetime import datetime
            now = datetime.now()
        current = now.hour * 60 + now.minute
        start, end = self._schedule_start, self._schedule_end
        if start == end:
            return True
        if start < end:
            return start <= current < end
        return current >= start or current < end  # gece yarısını aşan aralık

    def schedule_text(self) -> str:
        if not self._schedule_enabled:
            return ""
        window = f"{self._schedule_start // 60:02d}:{self._schedule_start % 60:02d}–{self._schedule_end // 60:02d}:{self._schedule_end % 60:02d}"
        if self.schedule_open():
            return f"Zamanlama açık ({window})."
        return f"Zamanlı indirme: yeni indirmeler yalnızca {window} arasında başlar."

    def shutdown(self, timeout_ms: int = 2500) -> None:
        """Program kapanırken çalışan indirmeleri güvenle durdurur (yarım dosyalar sonra devam eder)."""
        self._shutting_down = True
        self._schedule_timer.stop()
        for worker in list(self._workers.values()):
            try:
                worker.stop_silently()
            except RuntimeError:
                pass
        for thread in list(self._threads.values()):
            try:
                thread.quit()
                if not thread.wait(timeout_ms):
                    logger.warning("İndirme iş parçacığı zamanında durmadı; süreç sonlanırken bırakılacak.")
            except RuntimeError:
                pass
        for job in self.jobs.values():
            part = self._part_path_for(job)
            if job.status in self.RUNNING_STATUSES and part.exists():
                try:
                    job.downloaded = part.stat().st_size
                except OSError:
                    pass
            job.speed = 0
        self._state_dirty = True
        self._flush_state()

    def _pump_queue(self):
        if self._global_paused or getattr(self, "_shutting_down", False):
            return
        DownloadWorker.active_count = max(1, len(self._threads))
        if not self.schedule_open():
            self._save_state()
            return
        while len(self._threads) < self.max_concurrent and self._queue:
            job_id = self._queue.pop(0)
            job = self.jobs.get(job_id)
            if not job or job.status == "İptal edildi":
                continue
            self._start(job_id)
        self._save_state()

    def _start(self, job_id: str):
        if job_id in self._threads:
            return
        job = self.jobs[job_id]
        thread = QThread(self)
        worker = DownloadWorker(job_id, job.url, job.target_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.status.connect(self._on_status)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.finished.connect(lambda jid=job_id: self._cleanup(jid))
        self._threads[job_id] = thread
        self._workers[job_id] = worker
        if job.downloaded > 0:
            job.status = "Devam ediyor"
        else:
            job.status = "Başlatılıyor"
        self.job_updated.emit(job_id)
        self._save_state()
        DownloadWorker.active_count = max(1, len(self._threads))
        thread.start()

    @property
    def global_paused(self) -> bool:
        return self._global_paused

    def set_max_concurrent(self, value: int):
        """Change simultaneous download limit without restarting the app."""
        try:
            value = int(value)
        except (TypeError, ValueError):
            return
        self.max_concurrent = max(1, min(value, 8))
        if not self._global_paused:
            self._pump_queue()

    def pause_all(self) -> dict:
        """Pause the whole queue and all currently running workers."""
        self._global_paused = True
        paused = 0
        for job_id, worker in list(self._workers.items()):
            job = self.jobs.get(job_id)
            if not job or job.status == "Tamamlandı":
                continue
            worker.pause()
            paused += 1
        self._save_state(immediate=True)
        return {"paused": paused, "queued": len(self._queue)}

    def resume_all(self) -> dict:
        """Resume suspended workers and allow queued jobs to start again."""
        self._global_paused = False
        resumed = 0
        for job_id, worker in list(self._workers.items()):
            job = self.jobs.get(job_id)
            if not job or job.status == "Tamamlandı":
                continue
            worker.resume()
            resumed += 1
        self._pump_queue()
        self._save_state(immediate=True)
        return {"resumed": resumed, "queued": len(self._queue)}

    def cancel_all(self) -> dict:
        """Cancel every unfinished download, including items waiting in queue."""
        self._global_paused = False
        cancelled_queue = 0
        for job_id in list(self._queue):
            job = self.jobs.get(job_id)
            if not job or job.status == "Tamamlandı":
                continue
            job.status = "İptal edildi"
            job.speed = 0
            job.eta = -1
            self.job_updated.emit(job_id)
            cancelled_queue += 1
        self._queue.clear()

        cancelled_active = 0
        for job_id, worker in list(self._workers.items()):
            job = self.jobs.get(job_id)
            if not job or job.status == "Tamamlandı":
                continue
            worker.cancel()
            cancelled_active += 1

        self._save_state(immediate=True)
        return {
            "active": cancelled_active,
            "queued": cancelled_queue,
            "total": cancelled_active + cancelled_queue,
        }

    def pause(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job:
            return
        if job_id in self._queue:
            self._queue = [jid for jid in self._queue if jid != job_id]
            job.status = "Duraklatıldı"
            job.speed = 0
            job.eta = -1
            self.job_updated.emit(job_id)
            self._save_state()
            return
        worker = self._workers.get(job_id)
        if worker:
            worker.pause()

    def resume(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job:
            return
        worker = self._workers.get(job_id)
        if worker:
            worker.resume()
            return
        if job.status in self.COMPLETED_STATUSES:
            return
        if job_id not in self._threads and job_id not in self._queue:
            job.status = "Kuyrukta"
            job.error = ""
            self._queue.append(job_id)
            self.job_updated.emit(job_id)
            self._save_state()
            self._pump_queue()

    def cancel(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job or job.status in self.COMPLETED_STATUSES:
            return
        if job_id in self._queue:
            self._queue = [jid for jid in self._queue if jid != job_id]
            job.status = "İptal edildi"
            job.speed = 0
            job.eta = -1
            self.job_updated.emit(job_id)
            self._save_state()
            return
        worker = self._workers.get(job_id)
        if worker:
            worker.cancel()
        elif job.status == "Duraklatıldı":
            job.status = "İptal edildi"
            self.job_updated.emit(job_id)
            self._save_state()

    def retry(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job or job_id in self._threads or job_id in self._queue:
            return
        job.status = "Kuyrukta"
        job.error = ""
        job.speed = 0
        job.eta = -1
        job.retry_count = 0
        part = self._part_path_for(job)
        if part.exists():
            try:
                job.downloaded = part.stat().st_size
            except Exception:
                pass
        else:
            job.downloaded = 0
            job.total = 0
        self._queue.append(job_id)
        self.job_updated.emit(job_id)
        self._save_state()
        self._pump_queue()

    def _on_progress(self, job_id, downloaded, total, speed, eta):
        job = self.jobs.get(job_id)
        if not job:
            return
        job.downloaded = downloaded
        job.total = total
        job.speed = speed
        job.eta = eta
        job.status = "İndiriliyor"
        self.job_updated.emit(job_id)
        self._save_state()

    def _on_status(self, job_id, status):
        job = self.jobs.get(job_id)
        if job:
            job.status = status
            self.job_updated.emit(job_id)
            self._save_state()

    def _on_finished(self, job_id, path):
        job = self.jobs.get(job_id)
        if not job:
            return
        job.target_path = path
        job.speed = 0
        job.eta = 0
        job.verification_status = "Doğrulanıyor"
        self.job_updated.emit(job_id)
        self._save_state(immediate=True)
        try:
            result = WindowsUpdateService.verify_file(path)
            job.sha256 = result.get("sha256", "")
            job.signature = result.get("signature", "")
            job.verification_message = result.get("message", "")
            if result.get("valid"):
                job.verification_status = "Doğrulandı"
                job.status = "Tamamlandı"
                job.retry_count = 0
                self.job_updated.emit(job_id)
                self._save_state()
                self._check_batch_complete(job.batch_id)
            else:
                job.verification_status = "BAŞARISIZ"
                job.error = "İndirme tamamlandı ancak güvenlik doğrulaması başarısız: " + (result.get("message") or "bilinmeyen hata")
                job.status = "Hata"
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass
                self.job_updated.emit(job_id)
                self._save_state()
                if job.retry_count < job.max_retries:
                    job.retry_count += 1
                    job.status = f"Doğrulama başarısız — yeniden indiriliyor ({job.retry_count}/{job.max_retries})"
                    self.job_updated.emit(job_id)
                    self._save_state()
                    QTimer.singleShot(min(15000, 1500 * job.retry_count), lambda jid=job_id: self._enqueue_automatic_retry(jid))
        except Exception as exc:
            job.verification_status = "Kontrol hatası"
            job.error = "İndirme sonrası doğrulama çalıştırılamadı: " + str(exc)
            job.status = "Hata"
            self.job_updated.emit(job_id)
            self._save_state()

    def _on_failed(self, job_id, message):
        job = self.jobs.get(job_id)
        if not job:
            return

        job.error = message
        job.speed = 0
        job.eta = -1
        part_exists = self._part_path_for(job).exists()

        if job.retry_count < job.max_retries:
            job.retry_count += 1
            job.status = f"Devam için yeniden deneniyor ({job.retry_count}/{job.max_retries})"
            self.job_updated.emit(job_id)
            self._save_state()
            # failed signal is emitted before QThread cleanup. Queueing immediately
            # was ineffective because the old thread was still registered. Retry
            # after cleanup and use a small backoff for transient network errors.
            delay_ms = min(15000, 1500 * job.retry_count)
            QTimer.singleShot(delay_ms, lambda jid=job_id: self._enqueue_automatic_retry(jid))
            return

        job.status = "Hata"
        self.job_updated.emit(job_id)
        self._save_state()

    def _enqueue_automatic_retry(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job or job.status in self.COMPLETED_STATUSES | self.CANCELLED_STATUSES:
            return
        if job_id in self._threads:
            QTimer.singleShot(500, lambda jid=job_id: self._enqueue_automatic_retry(jid))
            return
        if job_id not in self._queue:
            job.status = "Kuyrukta"
            job.error = ""
            self._queue.append(job_id)
            self.job_updated.emit(job_id)
            self._save_state()
        self._pump_queue()

    def _on_cancelled(self, job_id):
        job = self.jobs.get(job_id)
        if job:
            job.status = "İptal edildi"
            job.speed = 0
            self.job_updated.emit(job_id)
            self._save_state()

    def _cleanup(self, job_id: str):
        worker = self._workers.pop(job_id, None)
        thread = self._threads.pop(job_id, None)
        if worker:
            worker.deleteLater()
        if thread:
            thread.deleteLater()
        self._save_state()
        self._pump_queue()

    def _check_batch_complete(self, batch_id: str):
        if not batch_id:
            return
        jobs = [job for job in self.jobs.values() if job.batch_id == batch_id]
        if not jobs:
            return
        if all(job.status == "Tamamlandı" for job in jobs):
            metadata = dict(jobs[0].batch_meta or {})
            metadata.setdefault("batch_kind", jobs[0].batch_kind)
            self.batch_completed.emit(batch_id, metadata)

    def completed_batches(self, batch_kind: str = ""):
        grouped = {}
        for job in self.jobs.values():
            if not job.batch_id:
                continue
            if batch_kind and job.batch_kind != batch_kind:
                continue
            grouped.setdefault(job.batch_id, []).append(job)
        result = []
        for batch_id, jobs in grouped.items():
            if jobs and all(job.status == "Tamamlandı" for job in jobs):
                metadata = dict(jobs[0].batch_meta or {})
                metadata.setdefault("batch_kind", jobs[0].batch_kind)
                result.append((batch_id, metadata))
        return result

    def remove_jobs(self, job_ids, delete_files: bool = False):
        """Remove finished/inactive jobs from history, optionally deleting files.

        Active jobs are deliberately protected so a cleanup action cannot
        accidentally interrupt a running or queued download.
        """
        active_statuses = {
            "Kuyrukta", "Başlatılıyor", "İndiriliyor", "Duraklatıldı", "Devam ediyor"
        }
        removed = []
        skipped = []
        errors = []

        for job_id in list(dict.fromkeys(job_ids or [])):
            job = self.jobs.get(job_id)
            if not job:
                continue

            status = str(job.status or "")
            if status in active_statuses or status.startswith("Devam için yeniden deneniyor"):
                skipped.append((job_id, job.filename, status))
                continue

            if delete_files:
                for candidate in (Path(job.target_path), self._part_path_for(job)):
                    try:
                        if candidate.exists() and candidate.is_file():
                            candidate.unlink()
                    except Exception as exc:
                        errors.append((job_id, str(candidate), str(exc)))

            self._queue = [jid for jid in self._queue if jid != job_id]
            self.jobs.pop(job_id, None)
            removed.append(job_id)

        if removed:
            self._save_state()
        return {"removed": removed, "skipped": skipped, "errors": errors}

    def status_counts(self) -> dict:
        jobs = list(self.jobs.values())
        running = sum(1 for job in jobs if job.status in self.RUNNING_STATUSES)
        queued = sum(1 for job in jobs if job.status == "Kuyrukta" or job.status.startswith("Devam için yeniden deneniyor"))
        paused = sum(1 for job in jobs if job.status == "Duraklatıldı")
        completed = sum(1 for job in jobs if job.status == "Tamamlandı")
        failed = sum(1 for job in jobs if job.status == "Hata")
        cancelled = sum(1 for job in jobs if job.status in self.CANCELLED_STATUSES)
        return {
            "total": len(jobs),
            "running": running,
            "queued": queued,
            "paused": paused,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
        }

    def queue_position(self, job_id: str) -> int:
        try:
            return self._queue.index(job_id) + 1
        except ValueError:
            return 0

    def pause_many(self, job_ids):
        for job_id in list(dict.fromkeys(job_ids or [])):
            self.pause(job_id)

    def resume_many(self, job_ids):
        for job_id in list(dict.fromkeys(job_ids or [])):
            self.resume(job_id)

    def cancel_many(self, job_ids):
        for job_id in list(dict.fromkeys(job_ids or [])):
            self.cancel(job_id)

    def retry_many(self, job_ids):
        for job_id in list(dict.fromkeys(job_ids or [])):
            self.retry(job_id)

    def completed_job_ids(self):
        return [job.id for job in self.jobs.values() if job.status == "Tamamlandı"]

    def get(self, job_id: str):
        return self.jobs.get(job_id)

    def all_jobs(self):
        return list(self.jobs.values())

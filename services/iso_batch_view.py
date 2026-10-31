"""İndirme Yöneticisi'ndeki 'ISO Oluşturma' kartlarının durum mantığı (arayüzden bağımsız, test edilebilir)."""
from __future__ import annotations

from dataclasses import dataclass, field

DONE = "Tamamlandı"
FAILED = {"Hata"}
CANCELLED = {"İptal edildi", "İptal Edildi"}
BUILDING = {"Bekliyor", "Hazırlanıyor", "Dönüştürülüyor", "Doğrulanıyor", "İptal ediliyor"}
READY_STATUS = "İndirme Tamamlandı"

# Aşama anahtarları
DOWNLOADING = "downloading"
DOWNLOAD_PROBLEM = "download_problem"
READY = "ready"            # indirme bitti, ISO henüz başlamadı (manuel mod)
STARTING = "starting"      # indirme bitti, otomatik başlayacak
BUILDING_PHASE = "building"
BUILT = "built"
BUILD_FAILED = "build_failed"
BUILD_CANCELLED = "build_cancelled"


@dataclass
class BatchView:
    batch_id: str
    title: str
    phase: str
    text: str
    primary_action: str = ""        # start | retry_downloads | retry_build | open_folder | ""
    primary_label: str = ""
    primary_enabled: bool = False
    actions: list[str] = field(default_factory=list)   # ek düğmeler: details, cancel, open_iso_center, open_folder
    done: int = 0
    total: int = 0
    failed_ids: list[str] = field(default_factory=list)


def _title(jobs, state) -> str:
    meta = dict(jobs[0].batch_meta or {}) if jobs else {}
    meta = {**dict((state or {}).get("metadata", {}) or {}), **meta}
    build = meta.get("build") or "Windows"
    parts = [f"Windows 11 {build}" if build != "Windows" else "Windows"]
    for key in ("architecture", "language"):
        if meta.get(key):
            parts.append(str(meta[key]))
    return " · ".join(parts)


def compute_view(batch_id: str, jobs: list, state: dict | None, auto_enabled: bool) -> BatchView:
    """Bir UUP grubunun (batch) indirme işleri ve ISO durumundan kart içeriğini üretir."""
    state = dict(state or {})
    status = state.get("status", "")
    total = len(jobs)
    done = sum(1 for j in jobs if j.status == DONE)
    failed_ids = [j.id for j in jobs if j.status in FAILED or j.status in CANCELLED]
    active = total - done - len(failed_ids)
    view = BatchView(batch_id, _title(jobs, state), DOWNLOADING, "", done=done, total=total, failed_ids=failed_ids)

    if status == "Hazır":
        iso_name = ""
        iso_path = state.get("iso_path", "")
        if iso_path:
            iso_name = iso_path.replace("\\", "/").rsplit("/", 1)[-1]
        view.phase = BUILT
        view.text = f"ISO hazır{': ' + iso_name if iso_name else ''}. ISO Merkezi'nde görebilir, USB'ye yazabilirsiniz."
        view.primary_action, view.primary_label, view.primary_enabled = "open_folder", "ISO Klasörünü Aç", True
        view.actions = ["open_iso_center"]
        return view

    if status in BUILDING:
        view.phase = BUILDING_PHASE
        view.text = "ISO oluşturuluyor. Bu işlem uzun sürebilir; pencereyi kapatsanız da arka planda devam eder."
        view.primary_action, view.primary_label, view.primary_enabled = "", "ISO Oluşturuluyor…", False
        view.actions = ["details", "cancel"]
        return view

    if status == "Hata":
        view.phase = BUILD_FAILED
        view.text = "ISO oluşturulamadı. Ayrıntılardan nedeni görebilir, düzelttikten sonra yeniden deneyebilirsiniz."
        view.primary_action, view.primary_label, view.primary_enabled = "retry_build", "ISO Oluşturmayı Yeniden Dene", True
        view.actions = ["details"]
        return view

    if status == "İptal":
        view.phase = BUILD_CANCELLED
        view.text = "ISO oluşturma durduruldu. Dosyalar duruyor; istediğinizde yeniden başlatabilirsiniz."
        view.primary_action, view.primary_label, view.primary_enabled = "retry_build", "ISO'yu Şimdi Oluştur", True
        view.actions = ["details"]
        return view

    # ISO durumu yok ya da bekliyor: indirmelere bakılır.
    if active > 0:
        view.phase = DOWNLOADING
        view.text = f"Dosyalar indiriliyor: {done}/{total}. İndirme bitince " + (
            "ISO kendiliğinden oluşturulacak." if auto_enabled else "bu düğme etkinleşecek."
        )
        view.primary_label = "ISO Oluştur (indirme sürüyor)"
        return view
    if failed_ids:
        view.phase = DOWNLOAD_PROBLEM
        view.text = f"{len(failed_ids)} dosya indirilemedi. ISO için tüm dosyalar gerekli; başarısızları yeniden deneyin."
        view.primary_action, view.primary_label, view.primary_enabled = "retry_downloads", "Başarısızları Yeniden Dene", True
        return view

    # Tüm dosyalar indi.
    if auto_enabled and status != READY_STATUS:
        view.phase = STARTING
        view.text = "İndirme tamamlandı. ISO oluşturma başlıyor (yönetici izni istenebilir)."
        view.primary_label, view.primary_enabled = "ISO Oluşturuluyor…", False
        return view
    view.phase = READY
    view.text = "İndirme tamamlandı. ISO'yu oluşturmak için butona basın (yönetici izni istenir)."
    view.primary_action, view.primary_label, view.primary_enabled = "start", "ISO'yu Şimdi Oluştur", True
    return view

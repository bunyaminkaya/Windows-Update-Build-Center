"""Açılış süresi ölçümü.

``main.py`` en başta bu modülü içe aktarır; ``mark("ad")`` çağrıları süreç başlangıcından
(bu modülün yüklendiği andan) itibaren geçen süreyi kaydeder. Açılış bitince ``report()`` tek
satırlık bir özeti günlüğe (app.log) yazar. Ölçüm çok hafiftir; kapatma seçeneği gerekmez.
"""
from __future__ import annotations

import time

_T0 = time.perf_counter()
_marks: list[tuple[str, float]] = []
_pages: list[tuple[str, float]] = []
_reported = False

SLOW_START_MS = 5000  # bunun üstündeki açılış uyarı olarak yazılır


def mark(name: str) -> None:
    """Şu ana kadar geçen süreyi (ms) ``name`` adıyla kaydeder."""
    _marks.append((name, (time.perf_counter() - _T0) * 1000.0))


def page_built(name: str, seconds: float) -> None:
    """Bir sayfanın oluşturulma süresini kaydeder."""
    _pages.append((name, seconds * 1000.0))


def elapsed_ms() -> float:
    return (time.perf_counter() - _T0) * 1000.0


def summary() -> str:
    """Örnek: ``Qt hazır 120 ms | pencere hazır 1840 ms (en yavaş sayfalar: Ana Sayfa 310, …)``."""
    parts = [f"{name} {ms:.0f} ms" for name, ms in _marks]
    text = " | ".join(parts) if parts else "ölçüm yok"
    if _pages:
        slowest = sorted(_pages, key=lambda item: item[1], reverse=True)[:3]
        total = sum(ms for _n, ms in _pages)
        detail = ", ".join(f"{n} {ms:.0f}" for n, ms in slowest)
        text += f" | sayfalar toplam {total:.0f} ms (en yavaş: {detail})"
    return text


def report(logger) -> str:
    """Özeti bir kez günlüğe yazar; yazılan metni döner."""
    global _reported
    text = summary()
    if _reported:
        return text
    _reported = True
    total = _marks[-1][1] if _marks else elapsed_ms()
    if total > SLOW_START_MS:
        logger.warning("Yavaş açılış (%.1f sn): %s", total / 1000.0, text)
    else:
        logger.info("Açılış süreleri: %s", text)
    return text


def reset() -> None:
    """Yalnızca testler için."""
    global _reported
    _marks.clear()
    _pages.clear()
    _reported = False

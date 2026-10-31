"""İngilizce çeviri sözlüğü (A+B+C+D+E birleşimi). Eksik metin Türkçe kalır."""
from app.i18n_en_a import A
from app.i18n_en_b import B
from app.i18n_en_c import C
from app.i18n_en_d import D

try:
    from app.i18n_en_e import E
except ImportError:  # E henüz yoksa
    E = {}

EN: dict[str, str] = {**A, **B, **C, **D, **E}

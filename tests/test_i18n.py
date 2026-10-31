import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import i18n
from app.i18n_en import EN


class TranslateEngineTests(unittest.TestCase):
    def setUp(self):
        self._old = (i18n._lang, dict(i18n._exact), list(i18n._patterns), dict(i18n._cache))
        i18n._exact.clear(); i18n._patterns.clear(); i18n._cache.clear()
        i18n._compile(EN)
        i18n._lang = "en"

    def tearDown(self):
        i18n._lang, exact, patterns, cache = self._old
        i18n._exact.clear(); i18n._exact.update(exact)
        i18n._patterns[:] = patterns
        i18n._cache.clear(); i18n._cache.update(cache)

    def test_exact_and_whitespace(self):
        self.assertEqual(i18n.tr("Ayarlar"), "Settings")
        self.assertEqual(i18n.tr("  Yenile"), "  Refresh")

    def test_unknown_stays_turkish_and_non_str_untouched(self):
        self.assertEqual(i18n.tr("Bu metin sözlükte yok"), "Bu metin sözlükte yok")
        self.assertIsNone(i18n.tr(None))
        self.assertEqual(i18n.tr(5), 5)

    def test_number_and_text_patterns(self):
        self.assertEqual(i18n.tr("41 üçüncü taraf sürücü paketi bulundu · 38 seçili"),
                         "41 third-party driver packages found · 38 selected")
        self.assertEqual(i18n.tr("Tümü (12)"), "All (12)")
        self.assertEqual(i18n.tr("Adım 2 / 3"), "Step 2 / 3")

    def test_pattern_does_not_hijack_words(self):
        self.assertEqual(i18n.tr("bilgi amaçlı kayıt"), "informational entries")
        self.assertNotEqual(i18n.tr("3 kayıt"), "3 kayıt")

    def test_html_and_multiline(self):
        self.assertEqual(i18n.tr("<b>Destek ve geri bildirim</b><br>Bilinmeyen metin"),
                         "<b>Support and feedback</b><br>Bilinmeyen metin")
        text = "Seçilen USB bellekteki TÜM veriler silinecek.\n\nHEDEF DİSK: Disk 2 — Kingston\nBOYUT: 32 GB"
        out = i18n.tr(text)
        self.assertIn("ALL data on the selected USB drive will be erased.", out)
        self.assertIn("TARGET DISK: Disk 2 — Kingston", out)
        self.assertIn("SIZE: 32 GB", out)

    def test_label_value_rule(self):
        self.assertEqual(i18n.tr("Dosya Çakışması: Üzerine yazma"), "File conflict: Overwrite")
        self.assertEqual(i18n.tr("Son kontrol: 26.10.2026 10:00"), "Last check: 26.10.2026 10:00")

    def test_problem_device_line(self):
        out = i18n.tr("(Ağ · kod 28: Sürücü yüklü değil)")
        self.assertEqual(out, "(Network · code 28: The driver is not installed)")

    def test_turkish_mode_is_passthrough(self):
        i18n._lang = "tr"
        self.assertEqual(i18n.tr("Ayarlar"), "Ayarlar")

    def test_dictionary_sanity(self):
        for key, value in EN.items():
            import re
            n = key.count("{}") + key.count("{#}")
            positional = re.findall(r"\{(\d)\}", value)
            if positional:  # sırası değişen kalıp: {0}..{n-1} hepsi bir kez
                self.assertEqual(sorted(positional), [str(i) for i in range(n)], f"sıra numaraları hatalı: {key!r}")
            else:
                self.assertEqual(n, value.count("{}") + value.count("{#}"),
                                 f"yer tutucu sayısı uyuşmuyor: {key!r}")

    def test_positional_pattern(self):
        self.assertEqual(i18n.translate("Seçilen 3 kayıt için dosyaları diskten silmek istediğinize emin misiniz?"),
                         "Are you sure you want to delete the files from disk for the 3 selected records?")

    def test_dynamic_messages(self):
        self.assertEqual(i18n.translate("Eşzamanlı indirme sınırı 3 olarak ayarlandı."),
                         "Concurrent download limit set to 3.")
        self.assertEqual(i18n.translate("Açıklama: Güvenlik Güncellemesi\n\nDurum: Yüklü"),
                         "Description: Security Update\n\nStatus: Installed")

    def test_release_chart_months_english(self):
        from ui.widgets import release_chart
        self.assertIn(release_chart._MONTHS[0], ("Jan", "Oca"))


if __name__ == "__main__":
    unittest.main()

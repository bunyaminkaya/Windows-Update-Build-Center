import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.driver_backup_service import (
    BackupResult, DriverBackupService as S, DriverInfo, count_inf_files,
    format_size, is_third_party_inf,
)

SAMPLE = json.dumps([
    {"InfName": "oem12.inf", "DeviceName": "NVIDIA GeForce RTX 3060", "Provider": "NVIDIA",
     "DeviceClass": "DISPLAY", "DriverVersion": "31.0.15.3623", "DriverDate": "2024-01-10", "IsSigned": True},
    {"InfName": "oem12.inf", "DeviceName": "NVIDIA HD Audio", "Provider": "NVIDIA",
     "DeviceClass": "MEDIA", "DriverVersion": "1.0", "DriverDate": "2024-01-10", "IsSigned": True},
    {"InfName": "netrtwlane.inf", "DeviceName": "Windows kendi sürücüsü", "DeviceClass": "NET"},
    {"InfName": "OEM7.INF", "DeviceName": "Intel Wi-Fi 6", "Provider": "Intel",
     "DeviceClass": "NET", "DriverVersion": "22.1", "DriverDate": "2023-05-02"},
    {"InfName": "", "DeviceName": "Boş"},
])


class DriverParsingTests(unittest.TestCase):
    def test_third_party_detection(self):
        self.assertTrue(is_third_party_inf("oem12.inf"))
        self.assertTrue(is_third_party_inf("OEM7.INF"))
        self.assertFalse(is_third_party_inf("netrtwlane.inf"))
        self.assertFalse(is_third_party_inf("oem.inf"))
        self.assertFalse(is_third_party_inf(""))

    def test_parse_groups_and_filters(self):
        drivers = S.parse_drivers(SAMPLE)
        names = {d.inf_name.lower(): d for d in drivers}
        self.assertEqual(set(names), {"oem12.inf", "oem7.inf"})
        self.assertEqual(names["oem12.inf"].device_count, 2)
        self.assertEqual(names["oem12.inf"].display_name, "NVIDIA GeForce RTX 3060 (+1)")
        self.assertEqual(names["oem12.inf"].class_name, "Ekran")
        self.assertEqual(names["oem7.inf"].class_name, "Ağ")

    def test_parse_single_object_and_empty(self):
        self.assertEqual(S.parse_drivers(""), [])
        one = S.parse_drivers(json.dumps({"InfName": "oem1.inf", "DeviceName": "X"}))
        self.assertEqual(len(one), 1)

    def test_problem_devices(self):
        raw = json.dumps([
            {"Name": "Ethernet Denetleyicisi", "Class": "Net", "Code": 28},
            {"Name": "Eski Aygıt", "Class": "", "Code": 22},
            {"Name": "Ok", "Class": "x", "Code": 0},
            {"Name": "Tuhaf", "Class": "USB", "Code": 99},
        ])
        items = S.parse_problem_devices(raw)
        self.assertEqual(len(items), 3)
        self.assertTrue(items[0].driver_related)
        self.assertEqual([p.code for p in items if not p.driver_related], [22])
        self.assertEqual(S.parse_problem_devices(""), [])


class ScriptTests(unittest.TestCase):
    def test_backup_script_quotes_paths(self):
        s = S.build_backup_script(["oem1.inf"], Path("C:/Yedek's/Sürücü"), Path("C:/t/list.txt"), Path("C:/t/p.txt"), Path("C:/t/c.flag"))
        self.assertIn("'C:\\Yedek''s\\Sürücü'" if os.name == "nt" else "Yedek''s", s)
        self.assertIn("pnputil.exe /export-driver $inf $dest", s)
        self.assertIn("CANCELLED", s)
        self.assertTrue(s.rstrip().endswith("exit 0"))

    def test_restore_script_with_and_without_restore_point(self):
        a = S.build_restore_script(Path("D:/Drivers"), Path("L"), Path("R"), True)
        b = S.build_restore_script(Path("D:/Drivers"), Path("L"), Path("R"), False)
        self.assertIn("Checkpoint-Computer", a)
        self.assertNotIn("Checkpoint-Computer", b)
        for s in (a, b):
            self.assertIn("pnputil.exe /add-driver $f.FullName /install", s)
            self.assertIn("finally", s)  # sonuç dosyası her durumda yazılır
            self.assertIn("WriteAllText($rcf", s)
            self.assertTrue(s.rstrip().endswith("exit 0"))

    def test_progress_parse(self):
        self.assertEqual(S.parse_progress_line("OK|3|10|oem4.inf"), ("OK", 3, 10, "oem4.inf"))
        self.assertEqual(S.parse_progress_line("FAIL|1|2|oem9.inf"), ("FAIL", 1, 2, "oem9.inf"))
        self.assertIsNone(S.parse_progress_line("END"))
        self.assertIsNone(S.parse_progress_line("OK|x|y|z"))

    def test_restore_codes(self):
        self.assertEqual(S.interpret_restore_code(0)[:2], (True, False))
        self.assertEqual(S.interpret_restore_code(3010)[:2], (True, True))
        self.assertEqual(S.interpret_restore_code(259)[:2], (True, False))
        self.assertFalse(S.interpret_restore_code(1)[0])
        self.assertFalse(S.interpret_restore_code(2)[0])
        self.assertEqual(S.interpret_restore_code(4003)[:2], (True, True))
        self.assertIn("3 sürücü", S.interpret_restore_code(4003)[2])

    def test_restore_code_falls_back_to_log(self):
        log = "Ozet: yuklenen=4 zaten-yuklu=78 hata=0\r\nRC=0\r\n"
        self.assertEqual(S.parse_restore_log_code(log), 0)
        self.assertEqual(S.parse_restore_log_code("RC=1\nxx\nRC=4003\n"), 4003)
        self.assertIsNone(S.parse_restore_log_code("Ozet: hata"))
        self.assertIsNone(S.parse_restore_log_code(""))

    def test_restore_batch_content(self):
        text = S.restore_batch_text()
        self.assertIn('pnputil /add-driver "%~dp0Drivers\\*.inf" /subdirs /install', text)
        self.assertIn("net session", text)
        self.assertIn("\r\n", text)


class FilesystemTests(unittest.TestCase):
    def test_backup_folder_naming_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = S.new_backup_folder(Path(tmp))
            a.mkdir()
            b = S.new_backup_folder(Path(tmp))
            self.assertNotEqual(a, b)
            self.assertTrue(a.name.startswith("Surucu_Yedegi_"))

    def test_manifest_and_bat_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            d = DriverInfo("oem1.inf", "Aygıt", provider="P", class_name="Ağ", version="1", date="2024-01-01")
            S.write_manifest(folder, [d], BackupResult(folder, 1, 1))
            data = json.loads((folder / "yedek_bilgisi.json").read_text(encoding="utf-8"))
            self.assertEqual(data["driver_count"], 1)
            self.assertEqual(data["drivers"][0]["inf"], "oem1.inf")
            self.assertTrue((folder / "Suruculeri_Geri_Yukle.bat").exists())
            self.assertTrue((folder / "OKU.txt").exists())

    def test_inf_count_and_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "a" / "b"
            sub.mkdir(parents=True)
            (sub / "x.inf").write_text("x")
            (Path(tmp) / "y.INF").write_text("y")
            self.assertEqual(count_inf_files(Path(tmp)), 1 + (1 if os.name == "nt" else 0))
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(1536), "1.5 KB")

    def test_free_space_warning_levels(self):
        with tempfile.TemporaryDirectory() as tmp:
            free, warning = S.check_free_space(Path(tmp))
            self.assertGreater(free, 0)
            self.assertTrue(warning is None or "boş alan" in warning)

    def test_unsupported_platform_guards(self):
        if os.name == "nt":
            self.skipTest("Windows'ta çalışıyor")
        self.assertEqual(S.list_drivers(), [])
        self.assertEqual(S.list_problem_devices(), [])
        with self.assertRaises(RuntimeError):
            S.backup([DriverInfo("oem1.inf", "x")], Path("."))
        with self.assertRaises(RuntimeError):
            S.restore(Path("."))


    def test_restore_uses_log_when_result_file_is_missing(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Drivers").mkdir()
            (Path(tmp) / "Drivers" / "a.inf").write_text("x")

            def fake_run(script, *, timeout, workdir, name, poll=None):
                (Path(workdir) / "restore.log").write_text("Ozet: yuklenen=4 zaten-yuklu=78 hata=0\r\nRC=0\r\n", encoding="utf-8")

            with mock.patch.object(S, "is_supported_platform", return_value=True), \
                 mock.patch.object(S, "_run_elevated_powershell", side_effect=fake_run):
                ok, reboot, summary, detail = S.restore(Path(tmp), restore_point=False)
            self.assertTrue(ok)
            self.assertFalse(reboot)
            self.assertIn("RC=0", detail)


if __name__ == "__main__":
    unittest.main()


class EncodingTests(unittest.TestCase):
    def test_powershell_prefix_forces_utf8(self):
        from services import driver_backup_service as m
        self.assertIn("OutputEncoding", m._PS_UTF8)
        self.assertIn("UTF8", m._PS_UTF8)

    def test_turkish_names_survive_parsing(self):
        raw = json.dumps([{"InfName": "oem1.inf", "DeviceName": "Intel® Akıllı Ses Doğrulaması", "Provider": "Intel®"}], ensure_ascii=False)
        self.assertEqual(S.parse_drivers(raw)[0].device_name, "Intel® Akıllı Ses Doğrulaması")

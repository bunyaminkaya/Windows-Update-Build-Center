from services.usb_media_service import UsbDrive, UsbMediaService


def test_fat32_label_is_limited_to_11_chars():
    value = UsbMediaService.sanitize_volume_label(
        "WINDOWS_11_28120.2387_X64_TR-TR", "FAT32"
    )
    assert len(value) <= 11
    assert value == "WINDOWS_11_"


def test_ntfs_label_can_be_longer():
    value = UsbMediaService.sanitize_volume_label(
        "WINDOWS_11_28120.2387_X64_TR-TR", "NTFS"
    )
    assert len(value) <= 32
    assert value.startswith("WINDOWS_11_")


def test_large_usb_fat32_uses_safe_partition_size_and_label():
    drive = UsbDrive(1, "Kingston DataTraveler 2.0", 120 * 1024**3, "E")
    script = UsbMediaService._build_diskpart_script(
        drive, "GPT", "FAT32", "WINDOWS_11_28120.2387_X64_TR-TR"
    )
    assert "create partition primary size=32700" in script
    format_line = next(line for line in script if line.startswith("format fs="))
    assert 'label="WINDOWS_11_"' in format_line
    assert "convert gpt noerr" in script


def test_mbr_marks_partition_active():
    drive = UsbDrive(2, "USB", 16 * 1024**3, "F")
    script = UsbMediaService._build_diskpart_script(
        drive, "MBR", "NTFS", "WINDOWS_USB"
    )
    assert "active" in script


def test_diskpart_script_selects_created_partition_before_format():
    drive = UsbDrive(1, "Test USB", 120 * 1024**3, "E")
    script = UsbMediaService._build_diskpart_script(drive, "GPT", "FAT32", "WINDOWS_11_LONG_LABEL")
    create_idx = next(i for i, line in enumerate(script) if line.startswith("create partition primary"))
    select_idx = script.index("select partition 1")
    format_idx = next(i for i, line in enumerate(script) if line.startswith("format fs=fat32"))
    assign_idx = script.index("assign")
    assert create_idx < select_idx < format_idx < assign_idx


def test_mbr_partition_is_selected_before_active_and_format():
    drive = UsbDrive(2, "Test USB", 16 * 1024**3, "F")
    script = UsbMediaService._build_diskpart_script(drive, "MBR", "NTFS", "WINDOWS_USB")
    assert script.index("select partition 1") < script.index("active")
    assert script.index("active") < next(i for i, line in enumerate(script) if line.startswith("format fs=ntfs"))


def test_gpt_conversion_is_idempotent_in_diskpart_script():
    drive = UsbDrive(1, "Already GPT USB", 64 * 1024**3, "F")
    script = UsbMediaService._build_diskpart_script(drive, "GPT", "FAT32", "WINDOWS_USB")
    assert "convert gpt noerr" in script
    assert script.index("convert gpt noerr") < next(i for i, line in enumerate(script) if line.startswith("create partition primary"))


def test_mbr_conversion_is_idempotent_in_diskpart_script():
    drive = UsbDrive(2, "Already MBR USB", 16 * 1024**3, "G")
    script = UsbMediaService._build_diskpart_script(drive, "MBR", "NTFS", "WINDOWS_USB")
    assert "convert mbr noerr" in script
    assert script.index("convert mbr noerr") < next(i for i, line in enumerate(script) if line.startswith("create partition primary"))


def test_fat32_format_uses_32k_allocation_unit_for_fast_copy():
    # A 32K cluster (Microsoft's recommended FAT32 maximum) drastically
    # cuts FAT table metadata writes when robocopy streams the thousands
    # of small files found on Windows install media, which is the main
    # lever available to close the gap with tools like Rufus.
    drive = UsbDrive(1, "Test USB", 16 * 1024**3, "E")
    script = UsbMediaService._build_diskpart_script(drive, "GPT", "FAT32", "WINDOWS_USB")
    format_line = next(line for line in script if line.startswith("format fs=fat32"))
    assert "unit=32768" in format_line


def test_large_fat32_partition_still_uses_32k_unit_with_capped_size():
    # size=32700 (MB) partitions must be evaluated against that capped
    # size, not the full physical drive size, when picking a cluster.
    drive = UsbDrive(1, "Test USB", 120 * 1024**3, "E")
    script = UsbMediaService._build_diskpart_script(drive, "GPT", "FAT32", "WINDOWS_USB")
    format_line = next(line for line in script if line.startswith("format fs=fat32"))
    assert "unit=32768" in format_line


def test_ntfs_format_keeps_default_allocation_unit():
    # NTFS already handles many small files efficiently via the MFT, so we
    # deliberately leave its cluster size untouched (no unit= clause).
    drive = UsbDrive(1, "Test USB", 16 * 1024**3, "E")
    script = UsbMediaService._build_diskpart_script(drive, "GPT", "NTFS", "WINDOWS_USB")
    format_line = next(line for line in script if line.startswith("format fs=ntfs"))
    assert "unit=" not in format_line


def test_cluster_size_helper_scales_down_on_small_fat32_volumes():
    # Below the FAT32 minimum cluster-count threshold at 32K, the helper
    # must fall back to a smaller legal size instead of producing a
    # unit= value DiskPart would reject.
    too_small_for_32k = UsbMediaService._FAT32_MIN_CLUSTERS * 32768 - 1
    assert UsbMediaService._cluster_size_bytes("FAT32", too_small_for_32k) == 16384

    too_small_for_any = 1024  # far below even the smallest candidate
    assert UsbMediaService._cluster_size_bytes("FAT32", too_small_for_any) is None


def test_cluster_size_helper_matches_format_line_output():
    big_volume = 16 * 1024**3
    assert UsbMediaService._cluster_size_bytes("FAT32", big_volume) == 32768
    assert UsbMediaService._cluster_size_bytes("fat32", big_volume) == 32768
    assert UsbMediaService._cluster_size_bytes("NTFS", big_volume) is None


def test_validate_target_rejects_iso_larger_than_usb(tmp_path):
    from services.usb_media_service import UsbDrive, UsbMediaService
    iso = tmp_path / "big.iso"
    with iso.open("wb") as fh:
        fh.truncate(9 * 1024**3)
    drive = UsbDrive(1, "Test USB", int(8.5 * 1024**3), "E")
    try:
        UsbMediaService.validate_target(drive, iso, "NTFS")
    except RuntimeError as exc:
        assert "kapasitesi" in str(exc).lower()
    else:
        raise AssertionError("Yetersiz USB kapasitesi reddedilmeliydi")


def test_validate_target_accepts_reasonable_iso_size(tmp_path):
    from services.usb_media_service import UsbDrive, UsbMediaService
    iso = tmp_path / "normal.iso"
    with iso.open("wb") as fh:
        fh.truncate(6 * 1024**3)
    drive = UsbDrive(2, "Test USB", 16 * 1024**3, "F")
    UsbMediaService.validate_target(drive, iso, "NTFS")


def test_storage_script_uses_explicit_gpt_objects(tmp_path):
    drive = UsbDrive(1, "Test USB", 120 * 1024**3, "E")
    script = UsbMediaService._build_partition_powershell_script(
        drive, "GPT", "FAT32", "WINDOWS_11_LONG_LABEL", tmp_path / "letter.txt"
    )
    assert "$targetStyle = 'GPT'" in script
    assert "if ($disk.PartitionStyle -eq 'RAW')" in script
    assert "Initialize-Disk -Number $diskNumber -PartitionStyle $targetStyle" in script
    assert "Set-Disk -Number $diskNumber -PartitionStyle $targetStyle" in script
    assert "New-Partition -DiskNumber $diskNumber -Size 32700MB -AssignDriveLetter" in script
    assert "Format-Volume -FileSystem FAT32" in script
    assert "-AllocationUnitSize 32768" in script
    assert "Set-Partition -IsActive" not in script


def test_storage_script_uses_mbr_active_partition(tmp_path):
    drive = UsbDrive(2, "Test USB", 16 * 1024**3, "F")
    script = UsbMediaService._build_partition_powershell_script(
        drive, "MBR", "NTFS", "WINDOWS_USB", tmp_path / "letter.txt"
    )
    assert "$targetStyle = 'MBR'" in script
    assert "if ($disk.PartitionStyle -eq 'RAW')" in script
    assert "Initialize-Disk -Number $diskNumber -PartitionStyle $targetStyle" in script
    assert "Set-Disk -Number $diskNumber -PartitionStyle $targetStyle" in script
    assert "-UseMaximumSize -AssignDriveLetter" in script
    assert "Set-Partition -IsActive $true" in script
    assert "Format-Volume -FileSystem NTFS" in script


def test_storage_script_does_not_depend_on_diskpart_selection(tmp_path):
    drive = UsbDrive(3, "Test USB", 32 * 1024**3, "G")
    script = UsbMediaService._build_partition_powershell_script(
        drive, "GPT", "FAT32", "WINDOWS_USB", tmp_path / "letter.txt"
    )
    lowered = script.lower()
    assert "diskpart" not in lowered
    assert "select partition" not in lowered
    assert "select volume" not in lowered


def test_storage_script_writes_drive_letter_marker(tmp_path):
    marker = tmp_path / "usb.letter"
    drive = UsbDrive(4, "Test USB", 16 * 1024**3, "H")
    script = UsbMediaService._build_partition_powershell_script(
        drive, "GPT", "FAT32", "WINDOWS_USB", marker
    )
    assert "Set-Content -LiteralPath" in script
    assert str(marker).replace("'", "''") in script


def test_swm_parts_copy_directly_and_verify_sizes(tmp_path):
    source_dir = tmp_path / "prepared"
    target_dir = tmp_path / "usb" / "sources"
    source_dir.mkdir()
    target_dir.mkdir(parents=True)
    parts = []
    for name, size in (("install.swm", 1024 * 1024 + 17), ("install2.swm", 512 * 1024 + 9)):
        path = source_dir / name
        path.write_bytes((name.encode("utf-8") * ((size // len(name.encode("utf-8"))) + 1))[:size])
        parts.append(path)

    UsbMediaService._copy_swm_parts(
        parts,
        target_dir,
        progress=lambda _text: None,
        on_progress=lambda _percent, _text: None,
        cancelled=lambda: False,
    )

    for part in parts:
        copied = target_dir / part.name
        assert copied.exists()
        assert copied.stat().st_size == part.stat().st_size
        assert copied.read_bytes() == part.read_bytes()


def test_swm_copy_leaves_no_partial_file_after_success(tmp_path):
    source_dir = tmp_path / "prepared"
    target_dir = tmp_path / "usb" / "sources"
    source_dir.mkdir()
    target_dir.mkdir(parents=True)
    part = source_dir / "install.swm"
    part.write_bytes(b"x" * 131072)

    UsbMediaService._copy_swm_parts(
        [part],
        target_dir,
        progress=lambda _text: None,
        on_progress=lambda _percent, _text: None,
        cancelled=lambda: False,
    )

    assert (target_dir / "install.swm").exists()
    assert not (target_dir / "install.swm.wubc-part").exists()


def test_storage_script_refreshes_disk_state_after_clear(tmp_path):
    drive = UsbDrive(5, "Test USB", 64 * 1024**3, "I")
    script = UsbMediaService._build_partition_powershell_script(
        drive, "GPT", "FAT32", "WINDOWS_USB", tmp_path / "letter.txt"
    )
    assert "Update-Disk -Number $diskNumber" in script
    assert "Get-Disk -Number $diskNumber" in script
    assert "if ($disk.PartitionStyle -eq 'RAW')" in script
    assert "elseif ($disk.PartitionStyle -ne $targetStyle)" in script


def test_storage_script_verifies_target_partition_style_before_partition(tmp_path):
    drive = UsbDrive(6, "Test USB", 32 * 1024**3, "J")
    script = UsbMediaService._build_partition_powershell_script(
        drive, "MBR", "NTFS", "WINDOWS_USB", tmp_path / "letter.txt"
    )
    check = "if ($disk.PartitionStyle -ne $targetStyle)"
    create = "$part = New-Partition"
    assert check in script
    assert script.index(check) < script.index(create)


def test_wim_workspace_requirement_has_safety_margin():
    size = 5 * 1024**3
    required = UsbMediaService._required_wim_workspace_bytes(size)
    assert required >= size + 2 * 1024**3
    assert required >= int(size * 1.35)


def test_workspace_candidates_prefer_iso_folder_and_exclude_usb(monkeypatch, tmp_path):
    iso_dir = tmp_path / "iso_source"
    iso_dir.mkdir()
    target = tmp_path / "usb_target"
    target.mkdir()
    monkeypatch.setattr(UsbMediaService, "_fixed_drive_roots", classmethod(lambda cls: []))
    candidates = UsbMediaService._wim_workspace_candidates(iso_dir, target)
    assert candidates[0] == iso_dir


def test_split_wim_command_uses_scratch_dir(monkeypatch, tmp_path):
    install = tmp_path / "install.wim"
    install.write_bytes(b"x" * 1024)
    workspace = tmp_path / "workspace"
    captured = {}

    def fake_privileged(cls, args, **kwargs):
        captured["args"] = args
        (workspace / "install.swm").write_bytes(b"ok")

    monkeypatch.setattr(UsbMediaService, "_run_privileged", classmethod(fake_privileged))
    monkeypatch.setattr(UsbMediaService, "_wait_until_readable", classmethod(lambda cls, path, timeout=0: True))
    monkeypatch.setattr(UsbMediaService, "_required_wim_workspace_bytes", staticmethod(lambda size: 1))
    parts = UsbMediaService._split_wim_to_workspace(install, workspace, progress=lambda _m: None)
    assert parts
    assert any(str(arg).startswith("/ScratchDir:") for arg in captured["args"])


# ---- Kurulum özelleştirme (autounattend.xml) ve ISO SHA-256 ----
import hashlib
import xml.etree.ElementTree as ET

import pytest

from services.usb_media_service import InstallCustomization, normalize_sha256

_NS = {"u": "urn:schemas-microsoft-com:unattend"}


def _passes(xml: str) -> dict:
    root = ET.fromstring(xml.split("?>", 1)[1])
    return {s.get("pass"): s for s in root.findall("u:settings", _NS)}


def test_empty_customization_has_no_settings():
    c = InstallCustomization()
    assert c.is_empty
    assert _passes(c.build_xml()) == {}


def test_bypass_only_matches_previous_profile():
    xml = InstallCustomization(bypass_hardware=True).build_xml()
    assert set(_passes(xml)) == {"windowsPE"}
    for key in ("BypassTPMCheck", "BypassSecureBootCheck", "BypassRAMCheck"):
        assert key in xml


def test_full_customization_is_well_formed_and_complete():
    xml = InstallCustomization(True, "Ali", True, "PC-01").build_xml()
    passes = _passes(xml)
    assert set(passes) == {"windowsPE", "specialize", "oobeSystem"}
    assert "<ComputerName>PC-01</ComputerName>" in xml
    assert "<HideOnlineAccountScreens>true</HideOnlineAccountScreens>" in xml
    assert "<ProtectYourPC>3</ProtectYourPC>" in xml
    assert "<Name>Ali</Name>" in xml
    assert "HideEULAPage" not in xml  # lisans sayfası kullanıcı adına geçilmez


def test_account_name_is_xml_escaped_and_utf8():
    xml = InstallCustomization(local_account="Çağrı&Co").build_xml()
    assert "&amp;" in xml
    ET.fromstring(xml.split("?>", 1)[1])  # geçerli XML


@pytest.mark.parametrize("name", ["", "a" * 21, "bad/name", "Ad:Soyad", "Administrator", "guest", "..", " x"])
def test_invalid_account_names_rejected(name):
    if name == "":
        return  # boş = özellik kapalı
    with pytest.raises(ValueError):
        InstallCustomization(local_account=name).validate()


@pytest.mark.parametrize("name", ["a" * 16, "PC_01", "Çalışma", "12345", "-pc", "pc-", "my pc"])
def test_invalid_computer_names_rejected(name):
    with pytest.raises(ValueError):
        InstallCustomization(computer_name=name).validate()


def test_valid_computer_names_accepted():
    for name in ("PC-01", "DESKTOP", "a1"):
        InstallCustomization(computer_name=name).validate()


def test_architecture_detection_from_iso_name():
    from pathlib import Path
    d = UsbMediaService.detect_architecture
    assert d(Path("Win11_24H2_Turkish_x64.iso")) == "amd64"
    assert d(Path("Win11_ARM64.iso")) == "arm64"
    assert d(Path("Win10_x86.iso")) == "x86"
    assert d(Path("windows.iso")) == "amd64"


def test_normalize_sha256():
    good = "ab" * 32
    assert normalize_sha256("") == ""
    assert normalize_sha256(" " + good.upper() + " \n") == good.upper()
    assert normalize_sha256("-".join([good[i:i + 8] for i in range(0, 64, 8)])) == good.upper()
    with pytest.raises(ValueError):
        normalize_sha256("123")
    with pytest.raises(ValueError):
        normalize_sha256("g" * 64)


def test_sha256_compute_and_verify(tmp_path):
    f = tmp_path / "x.iso"
    f.write_bytes(b"windows" * 100000)
    want = hashlib.sha256(f.read_bytes()).hexdigest().upper()
    seen = []
    assert UsbMediaService.compute_sha256(f, lambda p, t: seen.append(p)) == want
    assert seen[-1] == 100
    assert UsbMediaService.verify_iso_sha256(f, want.lower()) == want
    with pytest.raises(RuntimeError, match="USB'ye dokunulmadı"):
        UsbMediaService.verify_iso_sha256(f, "0" * 64)


def test_sha256_can_be_cancelled(tmp_path):
    f = tmp_path / "x.iso"
    f.write_bytes(b"a" * 1000)
    with pytest.raises(RuntimeError, match="iptal"):
        UsbMediaService.compute_sha256(f, cancelled=lambda: True)

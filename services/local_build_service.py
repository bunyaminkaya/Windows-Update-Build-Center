from __future__ import annotations

import platform
import sys
from dataclasses import dataclass


@dataclass
class LocalBuild:
    product: str = ""
    display_version: str = ""
    major: str = ""      # ör. 26200
    ubr: int = 0         # ör. 4602
    edition: str = ""

    @property
    def full(self) -> str:
        return f"{self.major}.{self.ubr}" if self.major else ""


def _tuple(build: str) -> tuple[int, int]:
    parts = (build or "").strip().split(".")
    try:
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return 0, 0


class LocalBuildService:
    """Bu bilgisayardaki Windows sürümünü okur (yalnızca okuma, Windows'ta)."""

    @staticmethod
    def current() -> LocalBuild | None:
        if sys.platform != "win32":
            return None
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            )

            def read(name, default=""):
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except OSError:
                    return default

            major = str(read("CurrentBuildNumber") or read("CurrentBuild"))
            product = str(read("ProductName"))
            try:
                if int(major) >= 22000 and "Windows 10" in product:
                    product = product.replace("Windows 10", "Windows 11")  # kayıt defteri bilinen hatası
            except ValueError:
                pass
            return LocalBuild(
                product=product,
                display_version=str(read("DisplayVersion") or read("ReleaseId")),
                major=major,
                ubr=int(read("UBR", 0) or 0),
                edition=str(read("EditionID")),
            )
        except Exception:
            try:
                parts = platform.version().split(".")
                return LocalBuild(product="Windows", major=parts[2] if len(parts) > 2 else "", ubr=0)
            except Exception:
                return None

    @staticmethod
    def compare(records, local: LocalBuild | None, channel_hint: str = "retail") -> dict:
        """Aynı ana build'e (ör. 26200) ait en yeni yayın kaydıyla karşılaştırır."""
        if local is None or not local.major:
            return {"status": "unknown"}
        mine = _tuple(local.full)
        same = [
            r for r in records
            if _tuple(r.build_number)[0] == mine[0]
            and (channel_hint in (r.channel or "").lower() or channel_hint in (r.release_group or "").lower())
        ] or [r for r in records if _tuple(r.build_number)[0] == mine[0]]
        if not same:
            return {"status": "unknown"}
        latest = max(same, key=lambda r: _tuple(r.build_number))
        behind = sum(1 for r in same if _tuple(r.build_number) > mine)
        status = "latest" if _tuple(latest.build_number) <= mine else "behind"
        return {"status": status, "latest": latest, "behind": behind}

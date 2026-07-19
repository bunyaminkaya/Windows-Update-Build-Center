from dataclasses import dataclass


@dataclass(slots=True)
class UupDownloadPackage:
    filename: str
    direct_url: str
    architecture: str
    size: str = "—"
    size_bytes: int = 0
    sha1: str = ""

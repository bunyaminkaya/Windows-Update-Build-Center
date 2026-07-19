from dataclasses import dataclass


@dataclass(slots=True)
class PackageResult:
    update_id: str
    update_title: str
    filename: str
    architecture: str
    file_type: str
    size: str
    direct_url: str
    source: str = "Microsoft Update Catalog"

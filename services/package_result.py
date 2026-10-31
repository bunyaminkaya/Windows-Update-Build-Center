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
    product: str = ""
    classification: str = ""
    version: str = ""
    last_updated: str = ""
    recommended: bool = False
    recommendation_score: int = 0
    recommendation_reason: str = ""
    tracker_description: str = ""
    supersedence: str = ""

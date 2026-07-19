from dataclasses import dataclass, field


@dataclass(slots=True)
class UupSearchResult:
    uuid: str
    title: str
    build: str
    architecture: str
    created: int = 0
    language_code: str = ""
    language_available: bool = False
    edition_code: str = ""
    edition_name: str = ""
    edition_available: bool = False
    file_count: int = 0
    total_size: int = 0
    source_url: str = ""
    notes: list[str] = field(default_factory=list)

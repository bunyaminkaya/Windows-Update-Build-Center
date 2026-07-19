from dataclasses import dataclass


@dataclass(slots=True)
class SearchResult:
    update_id: str
    title: str
    product: str = ""
    classification: str = ""
    last_updated: str = ""
    version: str = ""
    size: str = ""
    source: str = ""
    source_url: str = ""
    channel: str = ""

    @property
    def architecture(self) -> str:
        value = self.title.lower()
        if "arm64" in value:
            return "ARM64"
        if "x64" in value or "64-bit" in value or "x64-based" in value:
            return "x64"
        if "x86" in value or "32-bit" in value or "x86-based" in value:
            return "x86"
        return "—"

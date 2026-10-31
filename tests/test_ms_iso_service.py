import pytest

from services import ms_iso_service as ms

PAGE = """<html><select id="product-edition"><option value="">Select</option>
<option value="3321">Windows 11 (multi-edition ISO)</option></select></html>"""
X64_URL = "https://software.download.prss.microsoft.com/dbazure/Win11_25H2_Turkish_x64.iso?t=abc&e=1"


class FakeResponse:
    def __init__(self, text="", payload=None):
        self.text, self._payload = text, payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, skus=None, links=None, error=None):
        self.headers, self.calls, self.error = {}, [], error
        self.skus = skus if skus is not None else [
            {"Id": "111", "Language": "English", "LocalizedLanguage": "English"},
            {"Id": "222", "Language": "Turkish", "LocalizedLanguage": "Türkçe"},
        ]
        self.links = links or {"ProductDownloadOptions": [{"Uri": X64_URL}]}

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        if "software-download/windows11" in url:
            return FakeResponse(text=PAGE)
        if "vlscppe" in url:
            return FakeResponse(text="ok")
        if self.error:
            return FakeResponse(payload={"Errors": [{"Key": "x", "Value": self.error}]})
        if url.endswith("getskuinformationbyproductedition"):
            return FakeResponse(payload={"Skus": self.skus})
        if url.endswith("GetProductDownloadLinksBySku"):
            return FakeResponse(payload=self.links)
        raise AssertionError(url)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    saved = {}
    monkeypatch.setattr(ms.SettingsService, "load", staticmethod(lambda: {"iso_center": dict(saved)}))
    monkeypatch.setattr(ms.SettingsService, "update_value", staticmethod(lambda sec, key, val: saved.__setitem__(key, val)))
    ms.MicrosoftIsoService._blocked_until = 0.0
    yield
    ms.MicrosoftIsoService._blocked_until = 0.0


def test_finds_turkish_x64_offer_and_reads_version_from_filename():
    session = FakeSession()
    offer = ms.MicrosoftIsoService(session).find("Türkçe", "x64")
    assert (offer.version, offer.architecture, offer.filename) == ("25H2", "x64", "Win11_25H2_Turkish_x64.iso")
    links_call = [c for c in session.calls if c[0].endswith("GetProductDownloadLinksBySku")][0]
    assert links_call[1]["SKU"] == "222" and links_call[2]["Referer"] == ms.PAGE_URLS["x64"]
    sku_call = [c for c in session.calls if c[0].endswith("getskuinformationbyproductedition")][0]
    assert sku_call[1]["ProductEditionId"] == "3321"


def test_missing_language_lists_available_languages():
    session = FakeSession(skus=[{"Id": "1", "Language": "English", "LocalizedLanguage": "English"}])
    with pytest.raises(ms.MicrosoftIsoError) as err:
        ms.MicrosoftIsoService(session).find("Türkçe", "x64")
    assert "English" in str(err.value) and not isinstance(err.value, ms.MicrosoftIsoRejected)


def test_sentinel_rejection_is_typed_and_starts_cooldown():
    session = FakeSession(error="Sentinel marked this request as rejected.")
    with pytest.raises(ms.MicrosoftIsoRejected):
        ms.MicrosoftIsoService(session).find("Türkçe", "x64")
    first = len(session.calls)
    with pytest.raises(ms.MicrosoftIsoRejected) as err:
        ms.MicrosoftIsoService(session).find("Türkçe", "x64")
    assert len(session.calls) == first and "dakika" in str(err.value)  # ikinci denemede Microsoft'a gidilmedi


def test_non_microsoft_link_is_rejected():
    session = FakeSession(links={"ProductDownloadOptions": [{"Uri": "https://evil.example.com/Win11_25H2_Turkish_x64.iso"}]})
    with pytest.raises(ms.MicrosoftIsoError):
        ms.MicrosoftIsoService(session).find("Türkçe", "x64")


def test_unsupported_architecture():
    with pytest.raises(ms.MicrosoftIsoError):
        ms.MicrosoftIsoService(FakeSession()).find("Türkçe", "x86")


def test_rejection_is_remembered_and_expires():
    assert not ms.MicrosoftIsoService.rejected_recently()
    with pytest.raises(ms.MicrosoftIsoRejected):
        ms.MicrosoftIsoService(FakeSession(error="Sentinel marked this request as rejected.")).find("Türkçe", "x64")
    assert ms.MicrosoftIsoService.rejected_recently()
    ms.SettingsService.update_value("iso_center", "ms_rejected_at", 1.0)  # çok eski kayıt
    assert not ms.MicrosoftIsoService.rejected_recently()

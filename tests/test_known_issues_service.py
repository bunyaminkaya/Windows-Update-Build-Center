from services.build_tracker_service import BuildTrackerRecord, BuildTrackerService


class _Response:
    apparent_encoding = "utf-8"
    encoding = "utf-8"

    def __init__(self, html):
        self.text = html

    def raise_for_status(self):
        return None


class _Session:
    def __init__(self, html):
        self.html = html

    def get(self, *_args, **_kwargs):
        return _Response(self.html)


def _record():
    return BuildTrackerRecord(
        build_number="26300.9278", windows_version="26H2",
        microsoft_url="https://support.microsoft.com/help/example",
    )


def test_known_issue_table_is_structured():
    service = BuildTrackerService()
    service.session = _Session("""
        <main><h2>Known issues</h2><table>
        <thead><tr><th>Symptom</th><th>Workaround</th></tr></thead>
        <tbody><tr><td>Explorer may stop responding.</td><td>Restart Explorer while Microsoft is investigating.</td></tr></tbody>
        </table></main>
    """)
    issues = service.fetch_known_issues(_record())
    assert len(issues) == 1
    assert issues[0].description == "Explorer may stop responding."
    assert issues[0].affected_versions == "Windows 11 26H2"
    assert issues[0].status == "Araştırılıyor"
    assert issues[0].workaround.startswith("Restart Explorer")


def test_no_known_issue_notice_is_not_reported_as_issue():
    service = BuildTrackerService()
    service.session = _Session("""
        <main><h2>Bilinen sorunlar</h2>
        <p>Microsoft bu güncelleştirmeyle ilgili bir soruna dair bilgi almamıştır.</p></main>
    """)
    assert service.fetch_known_issues(_record()) == []

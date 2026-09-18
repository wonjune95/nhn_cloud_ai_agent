from aliases import alias_variants, generate


def test_alias_variants_cover_case_and_spacing():
    assert alias_variants("Object Storage") == ["Object Storage", "ObjectStorage", "object storage", "objectstorage"]


def test_alias_variants_single_word_dedupes():
    assert alias_variants("VPC") == ["VPC", "vpc"]


def test_alias_variants_placeholder_is_empty():
    assert alias_variants("_") == []


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql):
        assert "DISTINCT" in sql

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return FakeCursor(self.rows)

    def close(self):
        pass


def test_generate_builds_mapping_and_skips_placeholder():
    conn = FakeConn([("Network", "VPC"), ("Storage", "Object Storage"), ("Bill", "_")])
    assert generate(conn) == {
        "Network/VPC": ["VPC", "vpc"],
        "Storage/Object Storage": ["Object Storage", "ObjectStorage", "object storage", "objectstorage"],
    }


def test_main_does_not_overwrite_dictionary_when_documents_is_empty(tmp_path, monkeypatch, capsys):
    """documents 가 비어 있으면(적재 전·실패) 기존 사전 파일을 건드리지 않는다."""
    import aliases

    out = tmp_path / "services.generated.yaml"
    out.write_text("Network/VPC:\n- VPC\n", encoding="utf-8")

    monkeypatch.setattr(aliases, "get_conn", lambda: FakeConn([]))

    assert aliases.main(["--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == "Network/VPC:\n- VPC\n"
    assert "documents 가 비어 있어 별칭 사전을 갱신하지 않습니다" in capsys.readouterr().out


def test_main_writes_mapping_when_documents_has_rows(tmp_path, monkeypatch):
    import aliases
    import yaml

    out = tmp_path / "services.generated.yaml"
    monkeypatch.setattr(aliases, "get_conn", lambda: FakeConn([("Network", "VPC")]))

    assert aliases.main(["--out", str(out)]) == 0
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == {"Network/VPC": ["VPC", "vpc"]}

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


def test_generate_builds_mapping_and_skips_placeholder():
    conn = FakeConn([("Network", "VPC"), ("Storage", "Object Storage"), ("Bill", "_")])
    assert generate(conn) == {
        "Network/VPC": ["VPC", "vpc"],
        "Storage/Object Storage": ["Object Storage", "ObjectStorage", "object storage", "objectstorage"],
    }

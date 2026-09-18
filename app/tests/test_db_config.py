"""db.py 의 환경변수 해석. 실제 연결은 하지 않는다."""

import db


def test_port_reads_plain_integer():
    assert db._port("5432") == 5432
    assert db._port(" 15432 ") == 15432


def test_port_falls_back_when_service_link_injects_a_url(capsys):
    """쿠버네티스가 Service 'db' 때문에 DB_PORT=tcp://… 를 주입해도 죽지 않는다."""
    assert db._port("tcp://10.100.1.5:5432") == db.DEFAULT_DB_PORT
    assert "DB_PORT" in capsys.readouterr().out


def test_port_falls_back_for_empty_and_missing_values():
    assert db._port(None) == db.DEFAULT_DB_PORT
    assert db._port("") == db.DEFAULT_DB_PORT

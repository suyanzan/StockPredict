import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

import stockpredict.scoreboard as score


@pytest.fixture
def database(monkeypatch):
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL for real PostgreSQL integration tests")
    schema = "test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(f'CREATE SCHEMA "{schema}"')

    def connect():
        return psycopg.connect(url, options=f"-c search_path={schema}", row_factory=dict_row)

    monkeypatch.setattr(score, "connect", connect)
    try:
        with connect() as connection:
            score.initialize(connection)
            score.initialize(connection)
        yield connect
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA "{schema}" CASCADE')

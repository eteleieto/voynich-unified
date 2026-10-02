import duckdb
import pytest

from vud import paths


@pytest.fixture(scope="session")
def con():
    if not paths.DB_PATH.exists():
        pytest.skip("run `vud build` first")
    return duckdb.connect(str(paths.DB_PATH), read_only=True)


def scalar(con, q, params=None):
    return con.sql(q, params=params).fetchone()[0]

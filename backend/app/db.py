from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings

# open=False: we open it explicitly in the FastAPI lifespan (see main.py).
pool = AsyncConnectionPool(
    conninfo=settings.database_url,
    min_size=1,
    max_size=5,
    open=False,
    kwargs={"row_factory": dict_row},  # rows come back as dicts, not tuples
)


async def init_db() -> None:
    """Apply schema.sql. Every statement is IF NOT EXISTS, so this is idempotent.
    (With more time: real migrations via Alembic or dbmate.)"""
    sql = (Path(__file__).parent.parent / "schema.sql").read_text()
    async with pool.connection() as conn:
        await conn.execute(sql)
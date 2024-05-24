# custom_sql_record_manager.py
import contextlib
import decimal
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Sequence, Union, Generator
from utils import _HashedDocument, _deduplicate_in_order, _batch, _get_source_id_assigner

from sqlalchemy import (
    URL,
    Column,
    Engine,
    Float,
    String,
    UniqueConstraint,
    Index,
    and_,
    create_engine,
    delete,
    select,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Query, Session, sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert
from langchain_core.indexing import RecordManager

Base = declarative_base()

class UpsertionRecord(Base):  # type: ignore[valid-type,misc]
    """Table used to keep track of when a key was last updated."""

    __tablename__ = "upsertion_record"

    uuid = Column(
        String,
        index=True,
        default=lambda: str(uuid.uuid4()),
        primary_key=True,
        nullable=False,
    )
    key = Column(String, index=True)
    namespace = Column(String, index=True, nullable=False)
    group_id = Column(String, index=True, nullable=True)
    updated_at = Column(Float, index=True)

    __table_args__ = (
        UniqueConstraint("key", "namespace", name="uix_key_namespace"),
        Index("ix_key_namespace", "key", "namespace"),
    )


class CustomSQLRecordManager(RecordManager):
    """A SQL Alchemy based implementation of the record manager."""

    def __init__(
        self,
        namespace: str,
        *,
        engine: Optional[Union[Engine, AsyncEngine]] = None,
        db_url: Union[None, str, URL] = None,
        engine_kwargs: Optional[Dict[str, Any]] = None,
        async_mode: bool = False,
    ) -> None:
        """Initialize the CustomSQLRecordManager.

        This class serves as a manager persistence layer that uses an SQL
        backend to track upserted records. You should specify either a db_url
        to create an engine or provide an existing engine.

        Args:
            namespace: The namespace associated with this record manager.
            engine: An already existing SQL Alchemy engine.
                Default is None.
            db_url: A database connection string used to create
                an SQL Alchemy engine. Default is None.
            engine_kwargs: Additional keyword arguments
                to be passed when creating the engine. Default is an empty dictionary.
            async_mode: Whether to create an async engine.
                Driver should support async operations.
                It only applies if db_url is provided.
                Default is False.

        Raises:
            ValueError: If both db_url and engine are provided or neither.
            AssertionError: If something unexpected happens during engine configuration.
        """
        super().__init__(namespace=namespace)
        if db_url is None and engine is None:
            raise ValueError("Must specify either db_url or engine")

        if db_url is not None and engine is not None:
            raise ValueError("Must specify either db_url or engine, not both")

        _engine: Union[Engine, AsyncEngine]
        if db_url:
            if async_mode:
                _engine = create_async_engine(db_url, **(engine_kwargs or {}))
            else:
                _engine = create_engine(db_url, **(engine_kwargs or {}))
        elif engine:
            _engine = engine

        else:
            raise AssertionError("Something went wrong with configuration of engine.")

        _session_factory: Union[sessionmaker[Session], async_sessionmaker[AsyncSession]]
        if isinstance(_engine, AsyncEngine):
            _session_factory = async_sessionmaker(bind=_engine)
        else:
            _session_factory = sessionmaker(bind=_engine)

        self.engine = _engine
        self.dialect = _engine.dialect.name
        self.session_factory = _session_factory

    def create_schema(self) -> None:
        """Create the database schema."""
        if isinstance(self.engine, AsyncEngine):
            raise AssertionError("This method is not supported for async engines.")

        Base.metadata.create_all(self.engine)

    async def acreate_schema(self) -> None:
        """Create the database schema."""

        if not isinstance(self.engine, AsyncEngine):
            raise AssertionError("This method is not supported for sync engines.")

        async with self.engine.begin() as session:
            await session.run_sync(Base.metadata.create_all)

    @contextlib.contextmanager
    def _make_session(self) -> Generator[Session, None, None]:
        """Create a session and close it after use."""

        if isinstance(self.session_factory, async_sessionmaker):
            raise AssertionError("This method is not supported for async engines.")

        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    @contextlib.asynccontextmanager
    async def _amake_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Create a session and close it after use."""

        if not isinstance(self.session_factory, async_sessionmaker):
            raise AssertionError("This method is not supported for sync engines.")

        async with self.session_factory() as session:
            yield session

    def get_time(self) -> float:
        """Get the current server time as a timestamp.

        Please note it's critical that time is obtained from the server since
        we want a monotonic clock.
        """
        with self._make_session() as session:
            if self.dialect == "sqlite":
                query = text("SELECT (julianday('now') - 2440587.5) * 86400.0;")
            elif self.dialect == "postgresql":
                query = text("SELECT EXTRACT (EPOCH FROM CURRENT_TIMESTAMP);")
            else:
                raise NotImplementedError(f"Not implemented for dialect {self.dialect}")

            dt = session.execute(query).scalar()
            if isinstance(dt, decimal.Decimal):
                dt = float(dt)
            if not isinstance(dt, float):
                raise AssertionError(f"Unexpected type for datetime: {type(dt)}")
            return dt

    async def aget_time(self) -> float:
        """Get the current server time as a timestamp.

        Please note it's critical that time is obtained from the server since
        we want a monotonic clock.
        """
        async with self._amake_session() as session:
            if self.dialect == "sqlite":
                query = text("SELECT (julianday('now') - 2440587.5) * 86400.0;")
            elif self.dialect == "postgresql":
                query = text("SELECT EXTRACT (EPOCH FROM CURRENT_TIMESTAMP);")
            else:
                raise NotImplementedError(f"Not implemented for dialect {self.dialect}")

            dt = (await session.execute(query)).scalar_one_or_none()

            if isinstance(dt, decimal.Decimal):
                dt = float(dt)
            if not isinstance(dt, float):
                raise AssertionError(f"Unexpected type for datetime: {type(dt)}")
            return dt

    def update(
        self,
        keys: Sequence[str],
        *,
        group_ids: Optional[Sequence[Optional[str]]] = None,
        time_at_least: Optional[float] = None,
    ) -> None:
        """Upsert records into the PostgreSQL database."""
        if group_ids is None:
            group_ids = [None] * len(keys)

        if len(keys) != len(group_ids):
            raise ValueError(
                f"Number of keys ({len(keys)}) does not match number of "
                f"group_ids ({len(group_ids)})"
            )

        update_time = self.get_time()

        if time_at_least and update_time < time_at_least:
            raise AssertionError(f"Time sync issue: {update_time} < {time_at_least}")

        records_to_upsert = [
            {
                "key": key,
                "namespace": self.namespace,
                "updated_at": update_time,
                "group_id": group_id,
            }
            for key, group_id in zip(keys, group_ids)
        ]

        with self._make_session() as session:
            pg_insert_stmt = pg_insert(UpsertionRecord).values(
                records_to_upsert
            )
            stmt = pg_insert_stmt.on_conflict_do_update(
                constraint="uix_key_namespace",
                set_={
                    "updated_at": pg_insert_stmt.excluded.updated_at,
                    "group_id": pg_insert_stmt.excluded.group_id,
                },
            )
            session.execute(stmt)
            session.commit()

    async def aupdate(
        self,
        keys: Sequence[str],
        *,
        group_ids: Optional[Sequence[Optional[str]]] = None,
        time_at_least: Optional[float] = None,
    ) -> None:
        """Upsert records into the PostgreSQL database."""
        if group_ids is None:
            group_ids = [None] * len(keys)

        if len(keys) != len(group_ids):
            raise ValueError(
                f"Number of keys ({len(keys)}) does not match number of "
                f"group_ids ({len(group_ids)})"
            )

        update_time = await self.aget_time()

        if time_at_least and update_time < time_at_least:
            raise AssertionError(f"Time sync issue: {update_time} < {time_at_least}")

        records_to_upsert = [
            {
                "key": key,
                "namespace": self.namespace,
                "updated_at": update_time,
                "group_id": group_id,
            }
            for key, group_id in zip(keys, group_ids)
        ]

        async with self._amake_session() as session:
            pg_insert_stmt = pg_insert(UpsertionRecord).values(
                records_to_upsert
            )
            stmt = pg_insert_stmt.on_conflict_do_update(
                constraint="uix_key_namespace",
                set_={
                    "updated_at": pg_insert_stmt.excluded.updated_at,
                    "group_id": pg_insert_stmt.excluded.group_id,
                },
            )
            await session.execute(stmt)
            await session.commit()

    def exists(self, keys: Sequence[str]) -> List[bool]:
        """Check if the given keys exist in the PostgreSQL database."""
        with self._make_session() as session:
            filtered_query: Query = session.query(UpsertionRecord.key).filter(
                and_(
                    UpsertionRecord.key.in_(keys),
                    UpsertionRecord.namespace == self.namespace,
                )
            )
            records = filtered_query.all()
        found_keys = set(r.key for r in records)
        return [k in found_keys for k in keys]

    async def aexists(self, keys: Sequence[str]) -> List[bool]:
        """Check if the given keys exist in the PostgreSQL database."""
        async with self._amake_session() as session:
            records = (
                (
                    await session.execute(
                        select(UpsertionRecord.key).where(
                            and_(
                                UpsertionRecord.key.in_(keys),
                                UpsertionRecord.namespace == self.namespace,
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
        found_keys = set(records)
        return [k in found_keys for k in keys]

    def list_keys(
        self,
        *,
        before: Optional[float] = None,
        after: Optional[float] = None,
        group_ids: Optional[Sequence[str]] = None,
        limit: Optional[int] = None,
    ) -> List[str]:
        """List records in the PostgreSQL database based on the provided date range."""
        with self._make_session() as session:
            query: Query = session.query(UpsertionRecord).filter(
                UpsertionRecord.namespace == self.namespace
            )

            if after:
                query = query.filter(UpsertionRecord.updated_at > after)
            if before:
                query = query.filter(UpsertionRecord.updated_at < before)
            if group_ids:
                query = query.filter(UpsertionRecord.group_id.in_(group_ids))

            if limit:
                query = query.limit(limit)
            records = query.all()
        return [r.key for r in records]

    async def alist_keys(
        self,
        *,
        before: Optional[float] = None,
        after: Optional[float] = None,
        group_ids: Optional[Sequence[str]] = None,
        limit: Optional[int] = None,
    ) -> List[str]:
        """List records in the PostgreSQL database based on the provided date range."""
        async with self._amake_session() as session:
            query: Query = select(UpsertionRecord.key).filter(
                UpsertionRecord.namespace == self.namespace
            )

            if after:
                query = query.filter(UpsertionRecord.updated_at > after)
            if before:
                query = query.filter(UpsertionRecord.updated_at < before)
            if group_ids:
                query = query.filter(UpsertionRecord.group_id.in_(group_ids))

            if limit:
                query = query.limit(limit)
            records = (await session.execute(query)).scalars().all()
        return list(records)

    def delete_keys(self, keys: Sequence[str]) -> None:
        """Delete records from the PostgreSQL database."""
        with self._make_session() as session:
            filtered_query: Query = session.query(UpsertionRecord).filter(
                and_(
                    UpsertionRecord.key.in_(keys),
                    UpsertionRecord.namespace == self.namespace,
                )
            )

            filtered_query.delete()
            session.commit()

    async def adelete_keys(self, keys: Sequence[str]) -> None:
        """Delete records from the PostgreSQL database."""
        async with self._amake_session() as session:
            await session.execute(
                delete(UpsertionRecord).where(
                    and_(
                        UpsertionRecord.key.in_(keys),
                        UpsertionRecord.namespace == self.namespace,
                    )
                )
            )

            await session.commit()

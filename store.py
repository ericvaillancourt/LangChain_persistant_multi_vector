from sqlalchemy import create_engine, Column, String, LargeBinary, select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
import asyncio
import pickle
from langchain_core.stores import BaseStore

Base = declarative_base()

class ByteStore(Base):
    __tablename__ = 'bytestore'
    collection_name = Column(String, primary_key=True)
    key = Column(String, primary_key=True)
    value = Column(LargeBinary)

class PostgresByteStore(BaseStore):
    def __init__(self, conninfo, collection_name):
        self.conninfo = conninfo
        self.collection_name = collection_name

        # Engines for synchronous and asynchronous operations
        self.engine = create_engine(conninfo)
        self.async_engine = create_async_engine(conninfo)

        # Metadata setup
        Base.metadata.bind = self.engine
        Base.metadata.create_all(self.engine)

        # Session factories for synchronous and asynchronous operations
        self.Session = scoped_session(sessionmaker(bind=self.engine))
        self.async_session_factory = sessionmaker(self.async_engine, class_=AsyncSession, expire_on_commit=False)

    # Synchronous methods
    def get(self, key):
        with self.Session() as session:
            result = session.execute(select(ByteStore).filter_by(collection_name=self.collection_name, key=key)).scalar()
            return pickle.loads(result.value) if result else None

    def set(self, key, value):
        with self.Session() as session:
            serialized_value = pickle.dumps(value)
            entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value)
            session.merge(entry)
            session.commit()

    def mget(self, keys):
        results = {}
        with self.Session() as session:
            # Retrieve all results at once
            query_results = session.execute(select(ByteStore).where(ByteStore.collection_name == self.collection_name, ByteStore.key.in_(keys))).scalars()
            for result in query_results:
                results[result.key] = pickle.loads(result.value)

        # Return a list of values based on the order of keys, using None for missing keys
        return [results.get(key) for key in keys]
    
    def mset(self, items):
        with self.Session() as session:
            for key, value in items:
                serialized_value = pickle.dumps(value)
                entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value)
                session.merge(entry)
            session.commit()

    def mdelete(self, keys):
        with self.Session() as session:
            session.execute(delete(ByteStore).where(ByteStore.collection_name == self.collection_name, ByteStore.key.in_(keys)))
            session.commit()

    def yield_keys(self, prefix=None):
        with self.Session() as session:
            query = select(ByteStore.key).where(ByteStore.collection_name == self.collection_name)
            if prefix:
                query = query.where(ByteStore.key.like(f'{prefix}%'))
            for row in session.execute(query):
                yield row.key

    # Asynchronous methods
    async def aget(self, key):
        async with self.async_session_factory() as session:
            result = await session.execute(select(ByteStore).filter_by(collection_name=self.collection_name, key=key))
            byte_store = result.scalars().first()
            return pickle.loads(byte_store.value) if byte_store else None

    async def aset(self, key, value):
        async with self.async_session_factory() as session:
            serialized_value = pickle.dumps(value)
            entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value)
            session.merge(entry)
            await session.commit()

    async def amget(self, keys):
        results = {}
        async with self.async_session_factory() as session:
            # Asynchronously retrieve all results at once
            query_results = await session.execute(select(ByteStore).where(ByteStore.collection_name == self.collection_name, ByteStore.key.in_(keys)))
            for result in query_results.scalars():
                results[result.key] = pickle.loads(result.value)

        # Return a list of values based on the order of keys, using None for missing keys
        return [results.get(key) for key in keys]
    
    async def amset(self, items):
        async with self.async_session_factory() as session:
            for key, value in items:
                serialized_value = pickle.dumps(value)
                entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value)
                session.merge(entry)
            await session.commit()

    async def amdelete(self, keys):
        async with self.async_session_factory() as session:
            await session.execute(delete(ByteStore).where(ByteStore.collection_name == self.collection_name, ByteStore.key.in_(keys)))
            await session.commit()

    async def ayield_keys(self, prefix=None):
        async with self.async_session_factory() as session:
            query = select(ByteStore.key).where(ByteStore.collection_name == self.collection_name)
            if prefix:
                query = query.where(ByteStore.key.like(f'{prefix}%'))
            async for row in session.stream(query):
                yield row.key

from sqlalchemy import create_engine, Column, String, LargeBinary, select, delete, UniqueConstraint
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
import pickle
import hashlib
from collections import OrderedDict
from langchain_core.stores import BaseStore
from langchain_core.documents.base import Document

Base = declarative_base()

class ByteStore(Base):
    __tablename__ = 'bytestore'
    collection_name = Column(String, primary_key=True)
    key = Column(String, primary_key=True)
    value = Column(LargeBinary)
    value_hash = Column(String)  # New field for storing the hash of the value
    filename = Column(String, primary_key=True)  # Include filename as part of the primary key
    #__table_args__ = (UniqueConstraint('collection_name', 'key', 'filename', name='_collection_key_filename_uc'),)

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

    # Helper function to compute the hash
    def compute_hash(self, content):
        hash_obj = hashlib.sha256(content.encode('utf-8'))
        return hash_obj.hexdigest()

    # Helper function to serialize value with consistent ordering
    def serialize_value(self, value):
        return pickle.dumps(self.recursive_ordered_dict(value))

    # Recursive function to convert dictionaries to OrderedDicts
    def recursive_ordered_dict(self, obj):
        if isinstance(obj, dict):
            return OrderedDict((k, self.recursive_ordered_dict(v)) for k, v in sorted(obj.items()))
        elif isinstance(obj, list):
            return [self.recursive_ordered_dict(v) for v in obj]
        else:
            return obj

    # Extracts the relevant part of the value to be hashed
    def extract_hashable_content(self, value):
        if isinstance(value, Document):
            return value.page_content
        elif isinstance(value, dict):
            return value.get('page_content', '')
        else:
            return str(value)

    # Synchronous methods
    def get(self, key, filename=None):
        with self.Session() as session:
            result = session.execute(select(ByteStore).filter_by(collection_name=self.collection_name, key=key, filename=filename)).scalar()
            return pickle.loads(result.value) if result else None

    def set(self, key, value, filename=None):
        with self.Session() as session:
            serialized_value = self.serialize_value(value)
            hashable_content = self.extract_hashable_content(value)
            entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value, value_hash=self.compute_hash(hashable_content), filename=filename)
            session.merge(entry)
            session.commit()

    def mget(self, keys, filename=None):
        results = {}
        with self.Session() as session:
            query_results = session.execute(select(ByteStore).where(ByteStore.collection_name == self.collection_name, ByteStore.key.in_(keys), ByteStore.filename == filename)).scalars()
            for result in query_results:
                results[result.key] = pickle.loads(result.value)
        return [results.get(key) for key in keys]

    def mset(self, items):
        with self.Session() as session:
            for key, value, filename in items:
                serialized_value = self.serialize_value(value)
                hashable_content = self.extract_hashable_content(value)
                entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value, value_hash=self.compute_hash(hashable_content), filename=filename)
                session.merge(entry)
            session.commit()

    def mdelete(self, keys, filename=None):
        with self.Session() as session:
            session.execute(delete(ByteStore).where(ByteStore.collection_name == self.collection_name, ByteStore.key.in_(keys), ByteStore.filename == filename))
            session.commit()

    def yield_keys(self, prefix=None, filename=None):
        with self.Session() as session:
            query = select(ByteStore.key).where(ByteStore.collection_name == self.collection_name, ByteStore.filename == filename)
            if prefix:
                query = query.where(ByteStore.key.like(f'{prefix}%'))
            for row in session.execute(query):
                yield row.key

    # Asynchronous methods
    async def aget(self, key, filename=None):
        async with self.async_session_factory() as session:
            result = await session.execute(select(ByteStore).filter_by(collection_name=self.collection_name, key=key, filename=filename))
            byte_store = result.scalars().first()
            return pickle.loads(byte_store.value) if byte_store else None

    async def aset(self, key, value, filename=None):
        async with self.async_session_factory() as session:
            serialized_value = self.serialize_value(value)
            hashable_content = self.extract_hashable_content(value)
            entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value, value_hash=self.compute_hash(hashable_content), filename=filename)
            session.merge(entry)
            await session.commit()

    async def amget(self, keys, filename=None):
        results = {}
        async with self.async_session_factory() as session:
            query_results = await session.execute(select(ByteStore).where(ByteStore.collection_name == self.collection_name, ByteStore.key.in_(keys), ByteStore.filename == filename))
            for result in query_results.scalars():
                results[result.key] = pickle.loads(result.value)
        return [results.get(key) for key in keys]

    async def amset(self, items):
        async with self.async_session_factory() as session:
            for key, value, filename in items:
                serialized_value = self.serialize_value(value)
                hashable_content = self.extract_hashable_content(value)
                entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value, value_hash=self.compute_hash(hashable_content), filename=filename)
                session.merge(entry)
            await session.commit()

    async def amdelete(self, keys, filename=None):
        async with self.async_session_factory() as session:
            await session.execute(delete(ByteStore).where(ByteStore.collection_name == self.collection_name, ByteStore.key.in_(keys), ByteStore.filename == filename))
            await session.commit()

    async def ayield_keys(self, prefix=None, filename=None):
        async with self.async_session_factory() as session:
            query = select(ByteStore.key).where(ByteStore.collection_name == self.collection_name, ByteStore.filename == filename)
            if prefix:
                query = query.where(ByteStore.key.like(f'{prefix}%'))
            async for row in session.stream(query):
                yield row.key

    # New synchronous methods with hash checking
    def conditional_set(self, key, value, filename=None):
        serialized_value = self.serialize_value(value)
        hashable_content = self.extract_hashable_content(value)
        new_hash = self.compute_hash(hashable_content)
        with self.Session() as session:
            result = session.execute(select(ByteStore).filter_by(collection_name=self.collection_name, key=key, filename=filename)).scalar()
            if result:
                if result.value_hash == new_hash:
                    return key, 'SKIP'  # No update needed
                operation = 'UPD'
            else:
                operation = 'INS'
            entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value, value_hash=new_hash, filename=filename)
            session.merge(entry)
            session.commit()
            return key, operation

    def conditional_mset(self, items):
        modified_keys = []
        item_keys = set((key, filename) for key, _, filename in items)
        with self.Session() as session:
            existing_records = session.execute(select(ByteStore).filter_by(collection_name=self.collection_name).filter(ByteStore.filename.in_([filename for _, _, filename in items]))).scalars().all()
            existing_keys = {(record.key, record.filename) for record in existing_records}
            existing_record_map = {(record.key, record.filename): record for record in existing_records}

            # Process deletions first
            deleted_keys = existing_keys - item_keys
            for key, filename in deleted_keys:
                session.execute(delete(ByteStore).where(ByteStore.collection_name == self.collection_name, ByteStore.key == key, ByteStore.filename == filename))
                modified_keys.append((key, 'DEL'))

            # Process inserts and updates
            for key, value, filename in items:
                serialized_value = self.serialize_value(value)
                hashable_content = self.extract_hashable_content(value)
                new_hash = self.compute_hash(hashable_content)
                if (key, filename) in existing_record_map:
                    existing_hash = existing_record_map[(key, filename)].value_hash
                    if existing_hash == new_hash:
                        modified_keys.append((key, 'SKIP'))
                    else:
                        entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value, value_hash=new_hash, filename=filename)
                        session.merge(entry)
                        modified_keys.append((key, 'UPD'))
                else:
                    entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value, value_hash=new_hash, filename=filename)
                    session.add(entry)
                    modified_keys.append((key, 'INS'))

            session.commit()
        return modified_keys

    # New asynchronous methods with hash checking
    async def aconditional_set(self, key, value, filename=None):
        serialized_value = self.serialize_value(value)
        hashable_content = self.extract_hashable_content(value)
        new_hash = self.compute_hash(hashable_content)
        async with self.async_session_factory() as session:
            result = await session.execute(select(ByteStore).filter_by(collection_name=self.collection_name, key=key, filename=filename))
            result = result.scalars().first()
            if result:
                if result.value_hash == new_hash:
                    return key, 'SKIP'  # No update needed
                operation = 'UPD'
            else:
                operation = 'INS'
            entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value, value_hash=new_hash, filename=filename)
            session.merge(entry)
            await session.commit()
            return key, operation

    async def aconditional_mset(self, items):
        modified_keys = []
        item_keys = set((key, filename) for key, _, filename in items)
        async with self.async_session_factory() as session:
            existing_records = (await session.execute(select(ByteStore).filter_by(collection_name=self.collection_name).filter(ByteStore.filename.in_([filename for _, _, filename in items])))).scalars().all()
            existing_keys = {(record.key, record.filename) for record in existing_records}
            existing_record_map = {(record.key, record.filename): record for record in existing_records}

            # Process deletions first
            deleted_keys = existing_keys - item_keys
            for key, filename in deleted_keys:
                await session.execute(delete(ByteStore).where(ByteStore.collection_name == self.collection_name, ByteStore.key == key, ByteStore.filename == filename))
                modified_keys.append((key, 'DEL'))

            # Process inserts and updates
            for key, value, filename in items:
                serialized_value = self.serialize_value(value)
                hashable_content = self.extract_hashable_content(value)
                new_hash = self.compute_hash(hashable_content)
                if (key, filename) in existing_record_map:
                    existing_hash = existing_record_map[(key, filename)].value_hash
                    if existing_hash == new_hash:
                        modified_keys.append((key, 'SKIP'))
                    else:
                        entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value, value_hash=new_hash, filename=filename)
                        session.merge(entry)
                        modified_keys.append((key, 'UPD'))
                else:
                    entry = ByteStore(collection_name=self.collection_name, key=key, value=serialized_value, value_hash=new_hash, filename=filename)
                    session.add(entry)
                    modified_keys.append((key, 'INS'))

            await session.commit()
        return modified_keys

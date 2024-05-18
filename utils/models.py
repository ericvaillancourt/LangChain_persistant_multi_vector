from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, Float, Index

Base = declarative_base()

class UpsertionRecord(Base):
    """Table to store upsertion records."""

    __tablename__ = "upsertions"

    key = Column(String, primary_key=True)
    namespace = Column(String, primary_key=True)
    updated_at = Column(Float, nullable=False)
    group_id = Column(String, nullable=True)

    __table_args__ = (
        Index("idx_upsertions_namespace_updated_at", "namespace", "updated_at"),
    )

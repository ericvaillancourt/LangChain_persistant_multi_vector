import hashlib
import json
import uuid
import logging
from typing import Any, Dict, Optional, Union, Iterable, Iterator, Sequence, Set, Callable, List, TypeVar, cast
from itertools import islice
from langchain_core.documents import Document
from langchain_core.pydantic_v1 import root_validator

T = TypeVar("T")

NAMESPACE_UUID = uuid.UUID(int=1984)

# Configure logging
logging.basicConfig(level=logging.DEBUG, filename='hashed_document_debug.log')

def _hash_string_to_uuid(input_string: str) -> uuid.UUID:
    """Hashes a string and returns the corresponding UUID."""
    hash_value = hashlib.sha1(input_string.encode("utf-8")).hexdigest()
    return uuid.uuid5(NAMESPACE_UUID, hash_value)

def _hash_nested_dict_to_uuid(data: Dict[Any, Any]) -> uuid.UUID:
    """Hashes a nested dictionary and returns the corresponding UUID."""
    serialized_data = json.dumps(data, sort_keys=True)
    hash_value = hashlib.sha1(serialized_data.encode("utf-8")).hexdigest()
    return uuid.uuid5(NAMESPACE_UUID, hash_value)

def generate_reproducible_id_by_position(position: int, metadata: Dict[str, Any]) -> str:
    """Generates a reproducible unique ID based on the position in the list and metadata."""
    metadata_copy = {k: v for k, v in metadata.items() if k != "doc_id"}
    combined_data = f"{position}-{json.dumps(metadata_copy, sort_keys=True)}"
    return str(_hash_string_to_uuid(combined_data))

def generate_reproducible_id_by_content(content: str, metadata: Dict[str, Any]) -> str:
    """Generates a reproducible unique ID based on the position in the list and metadata."""
    metadata_copy = {k: v for k, v in metadata.items() if k == "source"}
    combined_data = f"{content}-{json.dumps(metadata_copy, sort_keys=True)}"
    return str(_hash_string_to_uuid(combined_data))

class _HashedDocument(Document):
    """A hashed document with a unique ID."""

    uid: str
    hash_: str
    content_hash: str
    source_hash: str

    @classmethod
    def is_lc_serializable(cls) -> bool:
        return False

    @root_validator(pre=True)
    def calculate_hashes(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Root validator to calculate content and metadata hash."""
        content = values.get("page_content", "")
        metadata = values.get("metadata", {})

        # Only include the source field in the metadata hash
        source = metadata.get("source", "")

        content_hash = str(_hash_string_to_uuid(content))
        source_hash = str(_hash_string_to_uuid(source))

        values["content_hash"] = content_hash
        values["source_hash"] = source_hash
        values["hash_"] = str(_hash_string_to_uuid(content_hash + source_hash))

        _uid = values.get("uid", None)

        if _uid is None:
            values["uid"] = values["hash_"]

        # Logging to verify determinism
        logging.debug(f"Document Content: {content}")
        logging.debug(f"Document Metadata: {metadata}")
        logging.debug(f"Content Hash: {content_hash}")
        logging.debug(f"Source Hash: {source_hash}")
        logging.debug(f"Combined Hash (hash_): {values['hash_']}")
        logging.debug(f"UID: {values['uid']}")

        return values

    def to_document(self) -> Document:
        """Return a Document object."""
        return Document(
            page_content=self.page_content,
            metadata=self.metadata,
        )

    @classmethod
    def from_document(
        cls, document: Document, *, uid: Optional[str] = None
    ) -> '_HashedDocument':
        """Create a HashedDocument from a Document."""
        return cls(
            uid=uid,
            page_content=document.page_content,
            metadata=document.metadata,
        )

def _batch(size: int, iterable: Iterable[T]) -> Iterator[List[T]]:
    """Utility batching function."""
    it = iter(iterable)
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            return
        yield chunk

def _deduplicate_in_order(
    hashed_documents: Iterable[_HashedDocument],
) -> Iterator[_HashedDocument]:
    """Deduplicate a list of hashed documents while preserving order."""
    seen: Set[str] = set()
    for hashed_doc in hashed_documents:
        if hashed_doc.hash_ not in seen:
            seen.add(hashed_doc.hash_)
            yield hashed_doc

def _get_source_id_assigner(
    source_id_key: Union[str, Callable[[Document], str], None],
) -> Callable[[Document], Union[str, None]]:
    """Get the source id from the document."""
    if source_id_key is None:
        return lambda doc: None
    elif isinstance(source_id_key, str):
        return lambda doc: doc.metadata[source_id_key]
    elif callable(source_id_key):
        return source_id_key
    else:
        raise ValueError(
            f"source_id_key should be either None, a string or a callable. "
            f"Got {source_id_key} of type {type(source_id_key)}."
        )

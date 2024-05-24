# index_with_ids.py
import logging
from typing import Union, Iterable, Sequence, Callable, Optional, Dict, Literal, Set, cast
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore
from langchain_core.indexing.base import RecordManager
from utils import _HashedDocument, _deduplicate_in_order, _batch, _get_source_id_assigner

def index_with_ids(
    docs_source: Union[Iterable[Document]],
    record_manager: RecordManager,
    vector_store: VectorStore,
    *,
    batch_size: int = 100,
    cleanup: Literal["incremental", "full", None] = None,
    source_id_key: Union[str, Callable[[Document], str], None] = None,
    cleanup_batch_size: int = 1_000,
    force_update: bool = False,
) -> Dict:
    """Index documents with unique IDs, and log detailed debug information."""
    
    if cleanup not in {"incremental", "full", None}:
        raise ValueError(f"cleanup should be one of 'incremental', 'full' or None. Got {cleanup}.")
    
    if cleanup == "incremental" and source_id_key is None:
        raise ValueError("Source id key is required when cleanup mode is incremental.")

    methods = ["delete", "add_documents"]
    for method in methods:
        if not hasattr(vector_store, method):
            raise ValueError(f"Vectorstore {vector_store} does not have required method {method}")
    if type(vector_store).delete == VectorStore.delete:
        raise ValueError("Vectorstore has not implemented the delete method")

    doc_iterator = iter(docs_source)

    source_id_assigner = _get_source_id_assigner(source_id_key)

    index_start_dt = record_manager.get_time()
    num_added = 0
    num_skipped = 0
    num_updated = 0
    num_deleted = 0
    results = []
    all_hashed_docs = []  # Initialize to collect all hashed documents
    ids_operations = []  # Initialize to collect ids and their operations

    for doc_batch in _batch(batch_size, doc_iterator):
        if not doc_batch:
            continue
        
        hashed_docs = list(
            _deduplicate_in_order(
                [_HashedDocument.from_document(doc) for doc in doc_batch]
            )
        )

        all_hashed_docs.extend(hashed_docs)  # Collect all hashed documents

        source_ids: Sequence[Optional[str]] = [
            source_id_assigner(doc.to_document()) for doc in hashed_docs
        ]

        if cleanup == "incremental":
            for source_id, hashed_doc in zip(source_ids, hashed_docs):
                if source_id is None:
                    raise ValueError(
                        "Source ids are required when cleanup mode is incremental. "
                        f"Document that starts with content: {hashed_doc.page_content[:100]} was not assigned"
                    )
            source_ids = cast(Sequence[str], source_ids)

        exists_batch = record_manager.exists([doc.uid for doc in hashed_docs])

        uids = []
        docs_to_index = []
        uids_to_refresh = []
        seen_docs: Set[str] = set()
        for hashed_doc, doc_exists in zip(hashed_docs, exists_batch):
            if doc_exists:
                if force_update:
                    seen_docs.add(hashed_doc.uid)
                else:
                    uids_to_refresh.append(hashed_doc.uid)
                    continue
            uids.append(hashed_doc.uid)
            docs_to_index.append(hashed_doc.to_document())

        if uids_to_refresh:
            record_manager.update(uids_to_refresh, time_at_least=index_start_dt)
            num_skipped += len(uids_to_refresh)
            for uid in uids_to_refresh:
                ids_operations.append({"key": uid, "operation": "SKIP"})

        if docs_to_index:
            vector_store.add_documents(docs_to_index, ids=uids, batch_size=batch_size)
            num_added += len(docs_to_index) - len(seen_docs)
            num_updated += len(seen_docs)
            for uid in uids:
                operation = "INS" if uid not in seen_docs else "UPD"
                ids_operations.append({"key": uid, "operation": operation})

        record_manager.update(
            [doc.uid for doc in hashed_docs],
            group_ids=source_ids,
            time_at_least=index_start_dt,
        )

    # Ensure all documents are checked for incremental cleanup before continuing
    if cleanup == "incremental":
        for source_id in source_ids:
            if source_id is None:
                raise AssertionError("Source ids cannot be None here.")
        _source_ids = cast(Sequence[str], source_ids)
        uids_to_delete = record_manager.list_keys(
            group_ids=_source_ids, before=index_start_dt
        )
        if uids_to_delete:
            vector_store.delete(uids_to_delete)
            record_manager.delete_keys(uids_to_delete)
            num_deleted += len(uids_to_delete)
            for uid in uids_to_delete:
                ids_operations.append({"key": uid, "operation": "DEL"})

    if cleanup == "full":
        while uids_to_delete := record_manager.list_keys(
            before=index_start_dt, limit=cleanup_batch_size
        ):
            vector_store.delete(uids_to_delete)
            record_manager.delete_keys(uids_to_delete)
            num_deleted += len(uids_to_delete)
            for uid in uids_to_delete:
                ids_operations.append({"key": uid, "operation": "DEL"})

    results.append({"num_added": num_added, "num_updated": num_updated, "num_skipped": num_skipped, "num_deleted": num_deleted})

    return {
        "status": "success",
        "ids": ids_operations,  # Include ids and their operations
        "results": results,
    }

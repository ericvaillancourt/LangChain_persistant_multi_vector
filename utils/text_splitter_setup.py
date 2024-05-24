from sqlalchemy import create_engine, Column, String, LargeBinary, select, Table, MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from langchain.schema.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

def setup_text_splitter_and_process_documents(CONNECTION_STRING, parent_docs_operations, retriever):
    separators = ["\n\n", "\n", ".", "?", "!"]

    # Initialize the RecursiveCharacterTextSplitter with fixed parameters
    child_text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=400,
        chunk_overlap=20,
        separators=separators
    )

    # List to store all sub-documents
    all_sub_docs = []

    # Database connection setup
    engine = create_engine(CONNECTION_STRING)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Define table structure
    metadata = MetaData()
    langchain_pg_embedding = Table(
        'langchain_pg_embedding', metadata,
        Column('id', String, primary_key=True),
        Column('collection_id', String),
        Column('embedding', LargeBinary),
        Column('document', String),
        Column('cmetadata', JSONB)
    )

    # Sort the parent documents operations to ensure deterministic processing order
    parent_docs_operations = sorted(parent_docs_operations, key=lambda x: x[0])

    # Iterate through the operations
    for doc_id, operation in parent_docs_operations:
        if operation == 'SKIP':
            # Fetch records from langchain_pg_embedding table for SKIP documents
            query = select(
                langchain_pg_embedding.c.id,
                langchain_pg_embedding.c.collection_id,
                langchain_pg_embedding.c.embedding,
                langchain_pg_embedding.c.document,
                langchain_pg_embedding.c.cmetadata
            ).where(
                (langchain_pg_embedding.c.cmetadata['doc_id'].astext == doc_id) &
                (langchain_pg_embedding.c.cmetadata['type'].astext == 'smaller chunk')
            ).order_by(langchain_pg_embedding.c.id)  # Ensure fixed order
            
            result = session.execute(query).fetchall()
            
            # Recreate sub-documents from fetched records
            for row in result:
                metadata = row.cmetadata
                sub_doc_content = row.document
                sub_doc = Document(page_content=sub_doc_content, metadata=metadata)
                all_sub_docs.append(sub_doc)
        else:
            # Retrieve the document from the docstore for non-SKIP documents
            doc = retriever.docstore.get(doc_id)
            if doc:
                source = doc.metadata.get("source")  # Retrieve the source from the document's metadata
                sub_docs = child_text_splitter.split_documents([doc])
                # Ensure fixed order for sub-documents
                sub_docs = sorted(sub_docs, key=lambda x: x.page_content)
                for sub_doc in sub_docs:
                    sub_doc.metadata["doc_id"] = doc_id  # Assign the same doc_id to each sub-document
                    sub_doc.metadata["source"] = f"{source}(smaller chunk)"  # Add the suffix to the source
                    sub_doc.metadata["type"] = "smaller chunk"
                all_sub_docs.extend(sub_docs)

    # Close the session after use
    session.close()

    return all_sub_docs

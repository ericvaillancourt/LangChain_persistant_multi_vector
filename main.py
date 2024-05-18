from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from utils.index_with_ids import index_with_ids
from utils.custom_sql_record_manager import CustomSQLRecordManager
from database import COLLECTION_NAME, CONNECTION_STRING

# Create example documents and record manager
documents = [
    Document(page_content="Document 11 content", metadata={"source": "source_11"}),
    Document(page_content="Document 31 content", metadata={"source": "source_31"}),
]

namespace = f"{COLLECTION_NAME}"
record_manager = CustomSQLRecordManager(namespace, db_url=CONNECTION_STRING)

embeddings = OpenAIEmbeddings()
vectorstore = PGVector(
    embeddings=embeddings,
    collection_name=COLLECTION_NAME,
    connection=CONNECTION_STRING,
    use_jsonb=True,
)

indexing_result = index_with_ids(documents, record_manager, vectorstore, cleanup="incremental", source_id_key="source")
print("Initial Indexing result:", indexing_result)

indexing_result = index_with_ids(documents, record_manager, vectorstore, cleanup="incremental", source_id_key="source")
print("Second Indexing result:", indexing_result)

documents = [
    # Document(page_content="Document 44 content", metadata={"source": "source_44"}),
    
]

indexing_result = index_with_ids(documents, record_manager, vectorstore, cleanup="incremental", source_id_key="source")
print("After Deletion Indexing result:", indexing_result)

from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain.indexes import SQLRecordManager, index

embeddings = OpenAIEmbeddings()

documents = []

for i in range(1, 201):
    page_content = f"data {i}"
    metadata = {"source": f"test.txt"}
    document = Document(page_content=page_content, metadata=metadata)
    documents.append(document)

collection_name = "test_index"

embedding = OpenAIEmbeddings()

vectorstore = Chroma(
    persist_directory="emb",
    embedding_function=embeddings
)
namespace = f"choma/{collection_name}"
record_manager = SQLRecordManager(
    namespace, db_url="sqlite:///record_manager_cache.sql"
)

record_manager.create_schema()

idx = index(
    documents,
    record_manager,
    vectorstore,
    cleanup="incremental",
    source_id_key="source",
)
# should be : {'num_added': 200, 'num_updated': 0, 'num_skipped': 0, 'num_deleted': 0}
# and that's what we get.
print(idx)
idx = index(
    documents,
    record_manager,
    vectorstore,
    cleanup="incremental",
    source_id_key="source",
)
# should be : {'num_added': 0, 'num_updated': 0, 'num_skipped': 200, 'num_deleted': 0}
# but we get : {'num_added': 100, 'num_updated': 0, 'num_skipped': 100, 'num_deleted': 100}
print(idx)
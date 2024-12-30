from sqlalchemy import create_engine, MetaData, Table, select, update, String, TypeDecorator
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import BINARY, JSON
import json
import os
from dotenv import load_dotenv

# Define a custom type for 'vector'
class VectorType(TypeDecorator):
    impl = BINARY

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value

# Load environment variables
load_dotenv()
host = os.getenv("PG_VECTOR_HOST")
user = os.getenv("PG_VECTOR_USER")
password = os.getenv("PG_VECTOR_PASSWORD")
COLLECTION_NAME = os.getenv("PGDATABASE")
CONNECTION_STRING = f"postgresql+psycopg://{user}:{password}@{host}:5432/{COLLECTION_NAME}"

# Create the engine and session
engine = create_engine(CONNECTION_STRING)
Session = sessionmaker(bind=engine)

# Define tables
metadata = MetaData()

langchain_pg_embedding = Table(
    'langchain_pg_embedding', metadata,
    autoload_with=engine
)

documents = Table(
    'documents', metadata,
    autoload_with=engine
)

# Initialize pagination parameters
limit = 1000
offset = 0
counter = 0

# Paginate results
while True:
    with Session() as session:
        # Fetch rows with pagination
        result_proxy = session.execute(
            select(langchain_pg_embedding).offset(offset).limit(limit)
        ).mappings()

        rows = result_proxy.all()

        if not rows:
            break  # Exit the loop if no more rows

        for row in rows:
            cmetadata = row.get('cmetadata')

            if isinstance(cmetadata, dict):  # Check if cmetadata is already a dictionary
                cmetadata_dict = cmetadata
            else:
                try:
                    cmetadata_dict = json.loads(cmetadata)  # Convert to dict if it's a string
                except (TypeError, json.JSONDecodeError):
                    print(f"Skipping row with invalid JSON: {row['id']}")
                    continue

            # Check if 'url' is already present
            existing_url = cmetadata_dict.get('url', None)

            # Extract file name from 'source'
            source = cmetadata_dict.get('source', '')
            if source:
                # Extract the file name between the path and the last '('
                start_index = source.rfind('/') + 1  # Find the last '/'
                end_index = source.rfind('(')  # Find the last '('
                file_name = source[start_index:end_index].strip()

                # Search for the file name in the documents table
                document_result = session.execute(
                    select(documents.c.url).where(documents.c.filename == file_name)
                ).fetchone()

                if document_result:
                    url = document_result[0]  # Access the URL by index

                    # Check if the document is a PDF
                    if file_name.lower().endswith('.pdf'):
                        page_number = cmetadata_dict.get('page', 0)
                        url += f"#page={page_number}"

                    # Update or add the URL to cmetadata
                    if existing_url != url:
                        cmetadata_dict['url'] = url

                        try:
                            # Update the row in the langchain_pg_embedding table
                            update_stmt = (
                                update(langchain_pg_embedding)
                                .where(langchain_pg_embedding.c.id == row['id'])
                                .values(cmetadata=cmetadata_dict)  # Use JSONB directly
                            )

                            session.execute(update_stmt)
                            counter += 1

                        except Exception as e:
                            print(f"Error updating row {row['id']}: {e}")
                            continue

        # Commit changes after each batch
        session.commit()
        print(f"Committed {counter} rows...")

        # Update the offset for the next batch
        offset += limit

print(f"Update complete for {counter} rows!")

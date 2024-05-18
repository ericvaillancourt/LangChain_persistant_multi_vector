from utils.custom_sql_record_manager import CustomSQLRecordManager
from database import CONNECTION_STRING

namespace = "your_namespace_here"  # Replace with your actual namespace
record_manager = CustomSQLRecordManager(namespace, db_url=CONNECTION_STRING)

# Create the schema
record_manager.create_schema()

print("Database schema created successfully.")

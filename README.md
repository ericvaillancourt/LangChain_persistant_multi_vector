# Document Retrieval System: From Chunking to Question Generation

This repository contains the code and resources for the article [Document Retrieval System: From Chunking to Question Generation](https://medium.com/@eric_vaillancourt/enough-with-prototyping-time-for-persistent-multi-vector-storage-with-postgresql-in-langchain-8e678738e80d). The article explores techniques for breaking down larger documents into smaller chunks, generating concise summaries, and creating hypothetical questions for each chunk. These techniques are invaluable for information retrieval, text analysis, and enhancing comprehension.

## Contents

1. **Chunking and Summarizing**: Code for breaking down documents into smaller chunks and generating summaries.
2. **Question Generation**: Code for creating hypothetical questions for each document chunk.
3. **Document Retrieval System**: Code for setting up a retrieval system using various storage methods.

I have written a second article to explain the Multi-vector-RAG update vectors.ipynb notebook. 
[Reducing Costs and Enabling Granular Updates with Multi-Vector Retriever in LangChain](https://medium.com/@eric_vaillancourt/reducing-costs-and-enabling-granular-updates-with-multi-vector-retriever-in-langchain-ed35e09c727a).

This follow-up article delves into advanced techniques for updating vectors in a multi-vector retrieval system, addressing challenges such as efficient document updates and maintaining consistent document IDs. 

This notebook demonstrates how to:

1. Integrate LangChain's SQLRecordManager and custom utilities.
2. Generate reproducible document IDs.
Efficiently update document embeddings and the vector store.
3. Implement advanced retrieval methods for improved information management.


## Installation

To get started with the code in this repository, follow these steps:

1. Clone the repository: `git clone https://github.com/ericvaillancourt/LangChain_persistant_multi_vector.git`
2. Navigate to the project directory: `cd project`
3. Install the required packages: `pip install -r requirements.txt`



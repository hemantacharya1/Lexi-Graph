import chromadb
from celery.result import EagerResult, AsyncResult
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI

from config import settings
from schemas.query import QueryResponse, SourceDocument
from tasks import embed_query_task

def process_query(case_id: str, query: str) -> QueryResponse:
    """
    Processes a user's query by performing a RAG chain.
    1. Embeds the query using a Celery task.
    2. Retrieves relevant document chunks from ChromaDB.
    3. Constructs a prompt with the context.
    4. Invokes the Gemini LLM to generate an answer.
    5. Returns the answer along with the source documents.
    """
    print(f"Starting query process for case_id: {case_id}")

    # --- 1. Embed the query using the Celery worker ---
    try:
        # We call the task and wait for the result synchronously.
        # This is an RPC (Remote Procedure Call) pattern.
        task_result: AsyncResult = embed_query_task.delay(query_text=query)
        # We add a timeout to prevent the API from hanging indefinitely.
        query_embedding = task_result.get(timeout=30) 
        print("Successfully received query embedding from worker.")
    except Exception as e:
        print(f"Error getting embedding from worker: {e}")
        # In a real app, you might want a more specific error message.
        return QueryResponse(answer="Could not process query: Failed to generate text embedding.", sources=[])

    # --- 2. Retrieve relevant document chunks from ChromaDB ---
    try:
        chroma_client = chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)
        collection_name = f"case_{case_id.replace('-', '')}"
        collection = chroma_client.get_collection(name=collection_name)

        # Query the collection
        retrieved_results = collection.query(
            query_embeddings=[query_embedding],
            n_results=5, # Retrieve the top 5 most relevant chunks
            # IMPORTANT: Add a where filter to ensure we only search within the correct case.
            # This is a critical security and data isolation feature.
            where={"case_id": case_id}
        )
        print(f"Retrieved {len(retrieved_results['ids'][0])} chunks from ChromaDB.")
    except Exception as e:
        # This can happen if the collection doesn't exist yet (no docs processed).
        print(f"Error querying ChromaDB: {e}")
        return QueryResponse(answer="Could not find any relevant documents. Please ensure documents have been uploaded and processed for this case.", sources=[])

    if not retrieved_results['ids'][0]:
        return QueryResponse(answer="I couldn't find any relevant information in the uploaded documents to answer your question.", sources=[])

    # --- 3. Construct the prompt and RAG chain ---
    
    # This helper function formats the retrieved chunks into a single string.
    def format_docs(metadatas: list[dict]) -> str:
        return "\n\n".join(
            f"Source File: {meta.get('file_name', 'N/A')}, Page: {meta.get('page_number', 'N/A')}\nContent: {meta.get('absolute_text', '')}"
            for meta in metadatas
        )

    context = format_docs(retrieved_results['metadatas'][0])

    # This is our prompt template. It instructs the LLM on how to behave.
    template = """
    You are a helpful legal assistant. Answer the user's question based ONLY on the context provided below.
    If the context does not contain the answer, state that you cannot find the answer in the provided documents.
    Do not make up information. Be concise and precise. And don't answer questions unrelated to the provided context.

    CONTEXT:
    {context}

    QUESTION:
    {question}

    ANSWER:
    """
    prompt = ChatPromptTemplate.from_template(template)

    # Instantiate the Gemini LLM model
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=settings.GOOGLE_API_KEY)
    
    # Create the LangChain Expression Language (LCEL) chain
    # This is a modern, clean way to chain components together.
    rag_chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    # --- 4. Invoke the LLM to generate an answer ---
    print("Invoking LLM to generate the final answer...")
    final_answer = rag_chain.invoke({"context": context, "question": query})

    # --- 5. Format and return the final response ---
    source_documents = [
        SourceDocument(
            document_id=meta.get('document_id'),
            file_name=meta.get('file_name'),
            page_number=str(meta.get('page_number', 'N/A')), # Ensure page_number is a string
            absolute_text=meta.get('absolute_text')
        ) for meta in retrieved_results['metadatas'][0]
    ]

    print("Successfully generated answer and sources.")
    return QueryResponse(answer=final_answer, sources=source_documents)
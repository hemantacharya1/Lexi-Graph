import re
import redis
import pickle
from celery.result import AsyncResult
from rank_bm25 import BM25Okapi

import chromadb
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI

from config import settings
from schemas.query import QueryResponse, SourceDocument
from tasks import embed_query_task, rerank_documents_task # Import our new task


SHORT_QUERY_WORD_COUNT = 5  # Queries shorter than this will be expanded.
SLAM_DUNK_THRESHOLD = 0.4  # A very high confidence match.
MISS_THRESHOLD = 0.9       # A very low confidence match.


# --- HELPER FUNCTIONS ---

def _get_bm25_index_for_case(case_id: str, collection: chromadb.Collection) -> BM25Okapi:
    """
    Builds or retrieves a cached BM25 keyword search index for a given case.
    This avoids re-building the index for every query, saving significant time.
    """
    # Initialize a connection to our Redis cache.
    redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)
    cache_key = f"bm25_index__{case_id}"

    # 1. First, try to get the index from the cache.
    cached_index = redis_client.get(cache_key)
    if cached_index:
        print("[BM25 Cache] Index found in cache. Loading.")
        # Deserialize the cached object back into a usable BM25 index.
        return pickle.loads(cached_index)

    # 2. If it's not in the cache, we build it from scratch.
    print("[BM25 Cache] Index not in cache. Building from scratch.")
    try:
        # Fetch all documents for this specific case from ChromaDB.
        all_docs = collection.get(where={"case_id": case_id}, include=["documents"])
        
        # The corpus is the collection of all text chunks we want to search.
        corpus = all_docs['documents']
        if not corpus:
            print("[BM25 Cache] No documents in case to build index. Returning empty index.")
            return None

        # BM25 works by tokenizing the text (splitting it into words).
        tokenized_corpus = [doc.split(" ") for doc in corpus]
        bm25 = BM25Okapi(tokenized_corpus)

        # 3. Save the newly built index into Redis with a 1-hour expiration time.
        # The 'pickle' library is used to serialize the Python object into bytes for storage.
        redis_client.set(cache_key, pickle.dumps(bm25), ex=3600)
        print("[BM25 Cache] Successfully built and cached new index.")
        return bm25
    except Exception as e:
        print(f"[BM25 Cache] !!! Error building index: {e}")
        return None


def _reciprocal_rank_fusion(results_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    """
    Merges multiple ranked lists of document IDs into a single list using Reciprocal Rank Fusion.
    This provides a more robust final ranking than any single search method.
    """
    # This dictionary will store the combined RRF scores for each document.
    ranked_scores = {}
    for doc_list in results_lists:
        # Iterate through each document in the ranked list.
        for rank, doc_id in enumerate(doc_list):
            # Add the document's score to the combined score dictionary.
            # The score is calculated as 1 / (k + rank).
            if doc_id not in ranked_scores:
                ranked_scores[doc_id] = 0
            ranked_scores[doc_id] += 1 / (k + rank + 1)

    # Sort the documents by their final RRF score in descending order.
    return {doc_id: score for doc_id, score in sorted(ranked_scores.items(), key=lambda item: item[1], reverse=True)}

def _perform_expansion(query: str) -> str:
    """
    Performs the actual LLM call for query expansion.
    """
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=settings.GOOGLE_API_KEY)
        expansion_template = """
        You are a helpful AI assistant. A user is asking a question about a legal document. 
        Rephrase their question into a more descriptive, semantically rich query that is likely to find relevant information in a vector database.
        Focus on extracting key terms and concepts. Only output the rephrased query.

        Original Query: '{original_query}'

        Rephrased Query:
        """
        expansion_prompt = ChatPromptTemplate.from_template(expansion_template)
        expansion_chain = expansion_prompt | llm | StrOutputParser()
        expanded_query = expansion_chain.invoke({"original_query": query})
        return expanded_query
    except Exception as e:
        print(f"Error during query expansion: {e}. Falling back to original query.")
        return query


# --- MAIN SERVICE FUNCTION ---

def process_query(case_id: str, query: str) -> QueryResponse:
    """
    Processes a user's query using a latency-aware "Fast Path / Deep Dive" RAG pipeline.
    """
    print(f"\n--- Starting Query Process for Case: {case_id} ---")
    print(f"Original Query: '{query}'")

    # --- Step 1: The "Fast Path" - Initial Vector Search ---
    print("\n[Step 1] Executing Fast Path: Initial Vector Search...")
    try:
        # We only need the embedding for the vector search.
        if len(query.split()) < SHORT_QUERY_WORD_COUNT:
            query = _perform_expansion(query)

        embedding_result = embed_query_task.delay(query_text=query).get(timeout=30)
        
        chroma_client = chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)
        collection_name = f"case_{case_id.replace('-', '')}"
        collection = chroma_client.get_collection(name=collection_name)

        # Retrieve the top 10 closest chunks based on semantic meaning.
        vector_results = collection.query(
            query_embeddings=[embedding_result],
            n_results=10,
            where={"case_id": case_id}
        )
    except Exception as e:
        print(f"!!! Error during initial vector search: {e}")
        return QueryResponse(answer="An error occurred while searching the document database.", sources=[])

    # --- Step 2: The "Confidence Gates" - Analyze Fast Path Results ---
    print("\n[Step 2] Analyzing Confidence of Fast Path Results...")
    if not vector_results or not vector_results['ids'][0]:
        print("-> Decision: Clear Miss (No results found). Exiting.")
        return QueryResponse(answer="I couldn't find any information in the documents for your question.", sources=[])

    # Get the distance score of the best-matching document. Lower is better.
    top_document_distance = vector_results['distances'][0][0]
    print(f"Top document distance score: {top_document_distance},{vector_results['distances'][0]}")

    # Define our confidence thresholds. These are tunable.
    if top_document_distance <= SLAM_DUNK_THRESHOLD:
        print(f"-> Decision: Slam Dunk (Score < {SLAM_DUNK_THRESHOLD}). Taking fast path exit.")
        # The result is so good, we trust it and exit early.
        final_chunks = collection.get(ids=vector_results['ids'][0][:3], include=["metadatas"])['metadatas']
    
    elif top_document_distance > MISS_THRESHOLD:
        print(f"-> Decision: Clear Miss (Score > {MISS_THRESHOLD}). Exiting.")
        # The best result is still too irrelevant.
        return QueryResponse(answer="I could not find any information that was sufficiently relevant to your query.", sources=[])

    else:
        # --- Step 3: The "Deep Dive Path" - For Ambiguous Results ---
        print(f"-> Decision: Ambiguous Zone. Engaging Deep Dive Path...")
        
        # A. Keyword Search
        print("[Deep Dive] Performing keyword search...")
        bm25 = _get_bm25_index_for_case(case_id, collection)
        if bm25:
            tokenized_query = query.split(" ")
            # Use the BM25 index to get the top 10 keyword-matching documents.
            keyword_doc_ids = bm25.get_top_n(tokenized_query, collection.get(where={"case_id": case_id})['documents'], n=10)
        else:
            keyword_doc_ids = []

        # B. Fuse Results
        print("[Deep Dive] Fusing vector and keyword results...")
        vector_doc_ids = vector_results['ids'][0]
        fused_results = _reciprocal_rank_fusion([vector_doc_ids, keyword_doc_ids])
        top_fused_ids = list(fused_results.keys())[:25] # Get top 25 candidates for re-ranking

        if not top_fused_ids:
            print("!!! No candidates found after fusion. Exiting.")
            return QueryResponse(answer="Could not find any relevant documents after a detailed search.", sources=[])

        candidate_chunks = collection.get(ids=top_fused_ids, include=["metadatas"])['metadatas']
        
        # C. Re-Rank with Cross-Encoder
        print("[Deep Dive] Re-ranking top candidates with Cross-Encoder...")
        # This is a call to our new, fast, and accurate Celery task.
        final_chunks = rerank_documents_task.delay(query=query, chunks=candidate_chunks).get(timeout=30)


    # --- Step 4: Final Answer Generation ---
    print(f"\n[Step 4] Generating final answer with {len(final_chunks)} high-quality chunks.")
    if not final_chunks:
        # This can happen if the re-ranking task fails or returns an empty list.
        return QueryResponse(answer="Found potential documents, but none were relevant enough to form an answer.", sources=[])

    # Construct the final context for the LLM.
    context = "\n\n---\n\n".join([chunk['absolute_text'] for chunk in final_chunks])
    
    # Define the final prompt for the LLM.
    template = """
    You are a helpful legal assistant. Answer the user's question based ONLY on the context provided below.
    If the context does not contain the answer, state that you cannot find the answer in the provided documents.
    Do not make up information. Be concise and precise.

    CONTEXT:
    {context}

    QUESTION:
    {question}

    ANSWER:
    """
    prompt = ChatPromptTemplate.from_template(template)
    
    final_answer_llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=settings.GOOGLE_API_KEY)
    
    rag_chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | prompt
        | final_answer_llm
        | StrOutputParser()
    )
    
    # Generate the final answer.
    final_answer = rag_chain.invoke({"context": context, "question": query})

    # Format the source documents for the final response.
    source_documents = [
        SourceDocument(
            document_id=chunk.get('document_id'),
            file_name=chunk.get('file_name'),
            page_number=str(chunk.get('page_number', 'N/A')),
            absolute_text=chunk.get('absolute_text')
        ) for chunk in final_chunks
    ]
    
    print("\n--- Query Process Completed Successfully ---")
    return QueryResponse(answer=final_answer, sources=source_documents)
# In file: src/service/query_service.py

import re
import redis
import pickle
import httpx
from rank_bm25 import BM25Okapi
import time # Ensure 'time' is imported

import chromadb
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI

from config import settings
from schemas.query import QueryResponse, SourceDocument


SHORT_QUERY_WORD_COUNT = 5
SLAM_DUNK_THRESHOLD = 0.6
MISS_THRESHOLD = 1.0


# --- HELPER FUNCTIONS (No changes needed here) ---

def _get_bm25_index_and_corpus(case_id: str, collection: chromadb.Collection) -> tuple[BM25Okapi, list, list]:
    """
    Builds or retrieves a cached BM25 index AND ITS CORPUS for a given case.
    This is the key performance optimization.
    """
    redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)
    cache_key = f"bm25_data__{case_id}"

    cached_data = redis_client.get(cache_key)
    if cached_data:
        print("[BM25 Cache] Index and corpus found in cache. Loading.")
        return pickle.loads(cached_data)

    print("[BM25 Cache] Index not in cache. Building from scratch.")
    try:
        all_docs = collection.get(where={"case_id": case_id}, include=["documents", "metadatas"])
        corpus = all_docs['documents']
        doc_ids = all_docs['ids']
        if not corpus:
            return None, None, None

        tokenized_corpus = [doc.split(" ") for doc in corpus]
        bm25 = BM25Okapi(tokenized_corpus)

        data_to_cache = (bm25, corpus, doc_ids)
        redis_client.set(cache_key, pickle.dumps(data_to_cache), ex=3600)
        
        print("[BM25 Cache] Successfully built and cached new index and corpus.")
        return bm25, corpus, doc_ids
    except Exception as e:
        print(f"[BM25 Cache] !!! Error building index: {e}")
        return None, None, None


def _reciprocal_rank_fusion(results_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    """
    Merges multiple ranked lists of document IDs into a single list using Reciprocal Rank Fusion.
    """
    ranked_scores = {}
    for doc_list in results_lists:
        for rank, doc_id in enumerate(doc_list):
            if doc_id not in ranked_scores:
                ranked_scores[doc_id] = 0
            ranked_scores[doc_id] += 1 / (k + rank + 1)
    return {doc_id: score for doc_id, score in sorted(ranked_scores.items(), key=lambda item: item[1], reverse=True)}

def _perform_expansion(query: str) -> str:
    """
    Performs the actual LLM call for query expansion.
    """
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=settings.GOOGLE_API_KEY)
        expansion_template = """
        You are a helpful AI assistant... (rest of your prompt)
        """
        expansion_prompt = ChatPromptTemplate.from_template(expansion_template)
        expansion_chain = expansion_prompt | llm | StrOutputParser()
        expanded_query = expansion_chain.invoke({"original_query": query})
        return expanded_query
    except Exception as e:
        print(f"Error during query expansion: {e}. Falling back to original query.")
        return query


# --- MAIN SERVICE FUNCTION (with timing logs) ---

def process_query(case_id: str, query: str) -> QueryResponse:
    """
    Processes a user's query using a latency-aware "Fast Path / Deep Dive" RAG pipeline.
    """
    # --- Start of Timing Logic ---
    start_time = time.time()
    timings = {}
    # ---

    print(f"\n--- Starting Query Process for Case: {case_id} ---")
    print(f"Original Query: '{query}'")

    try:
        # --- Timing Step: Query Expansion (Conditional) ---
        expansion_start = time.time()
        final_query = query
        if len(query.split()) < SHORT_QUERY_WORD_COUNT:
            final_query = _perform_expansion(query)
        timings['Query Expansion'] = time.time() - expansion_start
        # ---
        
        # --- Timing Step: Embedding ---
        embedding_start = time.time()
        # Make a direct HTTP POST request to the worker's internal API.
        # 'worker' is the service name from docker-compose.yml.
        # Port 8001 is what we defined in worker_startup.sh.
        worker_api_url = "http://worker:8001"
        with httpx.Client() as client:
            response = client.post(
                f"{worker_api_url}/embed_query",
                json={"query_text": query},
                timeout=30.0
            )
        response.raise_for_status() # This will raise an error for 4xx or 5xx responses
        embedding_result = response.json()

        timings['Embedding (Celery Task)'] = time.time() - embedding_start
        # ---
        
        # --- Timing Step: Vector Search ---
        vector_search_start = time.time()
        chroma_client = chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)
        collection_name = f"case_{case_id.replace('-', '')}"
        collection = chroma_client.get_collection(name=collection_name)
        vector_results = collection.query(
            query_embeddings=[embedding_result],
            n_results=10,
            where={"case_id": case_id}
        )
        timings['Vector Search'] = time.time() - vector_search_start
        # ---

    except Exception as e:
        print(f"!!! Error during initial retrieval steps: {e}")
        return QueryResponse(answer="An error occurred while searching the document database.", sources=[])

    if not vector_results or not vector_results['ids'][0]:
        print("-> Decision: Clear Miss (No results found). Exiting.")
        return QueryResponse(answer="I couldn't find any information in the documents for your question.", sources=[])

    top_document_distance = vector_results['distances'][0][0]
    print(f"Top document distance score: {top_document_distance}")

    path_taken = "Fast Path" # Default path
    if top_document_distance <= SLAM_DUNK_THRESHOLD:
        print(f"-> Decision: Slam Dunk (Score < {SLAM_DUNK_THRESHOLD}). Taking fast path exit.")
        final_chunks = collection.get(ids=vector_results['ids'][0][:3], include=["metadatas"])['metadatas']
    
    elif top_document_distance > MISS_THRESHOLD:
        print(f"-> Decision: Clear Miss (Score > {MISS_THRESHOLD}). Exiting.")
        return QueryResponse(answer="I could not find any information that was sufficiently relevant to your query.", sources=[])

    else:
        path_taken = "Deep Dive Path" # Update path if we enter the deep dive
        print(f"-> Decision: Ambiguous Zone. Engaging Deep Dive Path...")
        
        # --- Timing Step: BM25 Indexing/Retrieval ---
        bm25_start = time.time()
        bm25, corpus, doc_ids = _get_bm25_index_and_corpus(case_id, collection)
        if bm25:
            tokenized_query = final_query.split(" ")
            bm25_scores = bm25.get_scores(tokenized_query)
            scored_doc_ids = sorted(zip(doc_ids, bm25_scores), key=lambda item: item[1], reverse=True)
            keyword_doc_ids = [doc_id for doc_id, score in scored_doc_ids if score > 0][:10]
        else:
            keyword_doc_ids = []
        timings['BM25 Search (Cached)'] = time.time() - bm25_start
        # ---

        # --- Timing Step: Fusion (negligible, but good to have) ---
        fusion_start = time.time()
        vector_doc_ids = vector_results['ids'][0]
        fused_results = _reciprocal_rank_fusion([vector_doc_ids, keyword_doc_ids])
        top_fused_ids = list(fused_results.keys())[:25]
        timings['Result Fusion'] = time.time() - fusion_start
        # ---

        if not top_fused_ids:
            return QueryResponse(answer="Could not find any relevant documents after a detailed search.", sources=[])

        candidate_chunks = collection.get(ids=top_fused_ids, include=["metadatas"])['metadatas']
        
        # --- Timing Step: Re-Ranking ---
        rerank_start = time.time()
        with httpx.Client() as client:
            # We send the query and the slimmed-down candidate chunks to the re-ranker.
            response = client.post(
                f"{worker_api_url}/rerank_documents",
                json={"query": query, "chunks": candidate_chunks},
                timeout=30.0
            )
            response.raise_for_status()
            # The response is the final list of top 5 re-ranked chunks.
            final_chunks = response.json()
        timings['Re-Ranking (Celery Task)'] = time.time() - rerank_start
        # ---

    if not final_chunks:
        return QueryResponse(answer="Found potential documents, but none were relevant enough to form an answer.", sources=[])

    # --- Timing Step: Final Answer Generation ---
    generation_start = time.time()
    context = "\n\n---\n\n".join([chunk['absolute_text'] for chunk in final_chunks])
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

    # Correctly define the chain's structure (the "recipe")
    rag_chain = (
        {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
        | prompt
        | final_answer_llm
        | StrOutputParser()
    )

    # Correctly invoke the chain with the data (the "ingredients")
    final_answer = rag_chain.invoke({"context": context, "question": query})
    timings['Final Answer Generation (LLM)'] = time.time() - generation_start
    # ---

    # Correctly validate the Pydantic model
    source_documents = [
        SourceDocument.model_validate(chunk) for chunk in final_chunks
    ]
    
    # --- Final Timing Summary ---
    total_time = time.time() - start_time
    timings['Total Query Time'] = total_time

    print("\n--- PERFORMANCE SUMMARY ---")
    print(f"Path Taken: {path_taken}")
    for step, duration in timings.items():
        print(f"- {step}: {duration:.2f} seconds")
    print("---------------------------\n")
    # ---
    
    return QueryResponse(answer=final_answer, sources=source_documents)
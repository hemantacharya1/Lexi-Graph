from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict

from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
from config import settings

embedding_model = None
rerank_model = None

app = FastAPI(
    title="Lexi-Graph ML Inference API",
    description="Internal API for serving ML models for the Lexi-Graph application.",
    version="0.1.0",
)

@app.on_event("startup")
def startup_event():
    """
    This function is triggered when the FastAPI application starts.
    It pre-loads the AI models into the global variables, so they are "warm"
    and ready for the first request. This solves the "cold start" latency problem.
    """
    global embedding_model, rerank_model
    
    print("--- Worker API starting up: Warming up AI models... ---")
    
    # Load the embedding model (for vector search)
    embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
    
    # Load the Cross-Encoder model (for re-ranking)
    rerank_model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    
    print("--- AI models are warm and ready to serve requests. ---")


class EmbedRequest(BaseModel):
    query_text: str

class RerankChunk(BaseModel):
    id: str
    absolute_text: str

class RerankRequest(BaseModel):
    query: str
    chunks: List[RerankChunk]

class RerankResponse(RerankChunk):
    relevance_score: float

@app.post("/embed_query", response_model=List[float])
def embed_query(request: EmbedRequest):
    """
    Takes a text query and returns its vector embedding.
    """
    global embedding_model
    if embedding_model is None:
        return {"error": "Embedding model not loaded"}, 503

    embedding = embedding_model.encode(request.query_text).tolist()
    return embedding

@app.post("/rerank_documents", response_model=List[RerankResponse])
def rerank_documents(request: RerankRequest):
    """
    Takes a query and a list of candidate chunks and returns the top 5
    most relevant chunks, re-ranked by the Cross-Encoder model.
    """
    global rerank_model
    if rerank_model is None:
        return {"error": "Re-rank model not loaded"}, 503

    model_input_pairs = [[request.query, chunk.absolute_text] for chunk in request.chunks]

    scores = rerank_model.predict(model_input_pairs)
    
    # 1. Create a new list to hold the results.
    scored_chunks = []
    
    # 2. Combine the original chunk data with its new score into a new dictionary.
    for chunk, score in zip(request.chunks, scores):
        scored_chunks.append({
            "id": chunk.id,
            "absolute_text": chunk.absolute_text,
            "relevance_score": float(score) # Cast to float to ensure JSON serializability
        })
        
    reranked_chunks = sorted(scored_chunks, key=lambda x: x['relevance_score'], reverse=True)
    
    return reranked_chunks[:5]


@app.get("/health")
def health_check():
    """A simple health check endpoint to confirm the API is running."""
    return {"status": "ok", "models_loaded": embedding_model is not None and rerank_model is not None}
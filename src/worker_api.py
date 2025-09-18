# Create new file: src/worker_api.py

from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict

from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
from config import settings

# --- 1. Define Global Variables for Models ---
# We will load our models into these variables during startup.
# This is a crucial performance optimization: it ensures we don't reload the models
# from disk on every single API request.
embedding_model = None
rerank_model = None

# --- 2. Create the FastAPI Application ---
app = FastAPI(
    title="Lexi-Graph ML Inference API",
    description="Internal API for serving ML models for the Lexi-Graph application.",
    version="0.1.0",
)

# --- 3. Define the "Warm-Up" Function ---
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

# --- 4. Define Request and Response Models (Pydantic) ---
# This ensures our API has clear, validated data contracts.

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

# --- 5. Define the API Endpoints ---

@app.post("/embed_query", response_model=List[float])
def embed_query(request: EmbedRequest):
    """
    Takes a text query and returns its vector embedding.
    """
    global embedding_model
    if embedding_model is None:
        return {"error": "Embedding model not loaded"}, 503

    # The .tolist() is essential to convert the NumPy array into a
    # standard Python list that is JSON serializable.
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

    # The Cross-Encoder expects a list of [query, passage] pairs.
    model_input_pairs = [[request.query, chunk.absolute_text] for chunk in request.chunks]
    
    # Predict the relevance scores for each pair.
    scores = rerank_model.predict(model_input_pairs)
    
    # Combine the original chunks with their new scores.
    for chunk, score in zip(request.chunks, scores):
        chunk.relevance_score = float(score) # Cast to float to ensure JSON serializability
        
    # Sort the chunks by their new relevance score in descending order.
    reranked_chunks = sorted(request.chunks, key=lambda x: x.relevance_score, reverse=True)
    
    # Return the top 5.
    return reranked_chunks[:5]

@app.get("/health")
def health_check():
    """A simple health check endpoint to confirm the API is running."""
    return {"status": "ok", "models_loaded": embedding_model is not None and rerank_model is not None}
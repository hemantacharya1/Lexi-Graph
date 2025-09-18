import traceback
import hashlib
from datetime import datetime
from celery import chord
from celery_app import celery_worker
from database import SessionLocal
from config import settings
# Use the correct model names we defined
import models.document as document_model

def _get_db():
    """Creates a new database session for each task execution."""
    return SessionLocal()

@celery_worker.task(name="tasks.prepare_and_process_document")
def prepare_and_process_document(document_id: str):
    """
    Parent task: Orchestrates the entire document processing pipeline.
    This version implements a production-grade HYBRID chunking strategy.
    """
    from unstructured.partition.auto import partition
    from unstructured.cleaners.core import clean
    from langchain.text_splitter import RecursiveCharacterTextSplitter

    print(f"\n[Parent Task] Starting preparation for document_id: {document_id}")
    db = _get_db()
    try:
        document = db.query(document_model.LegalDocument).filter(document_model.LegalDocument.id == document_id).first()
        if not document:
            print(f"[Parent Task] ERROR: Document {document_id} not found.")
            return

        # (The deletion logic we added previously should remain here)
        # ...

        document.status = "PROCESSING"
        document.status_message = "Step 1/3: Parsing document content and metadata."
        db.commit()

        print(f"[Parent Task] Parsing file: {document.file_path}")
        elements = partition(filename=document.file_path)

        # --- START: Hybrid Chunking Logic ---

        target_chunk_size_chars = 1000
        # This splitter will ONLY be used for elements that are too large on their own.
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=target_chunk_size_chars,
            chunk_overlap=150 # Overlap is useful here to connect the split pieces of a large paragraph.
        )
        
        chunks_with_metadata = []
        current_chunk_text = ""
        current_chunk_page_numbers = set()

        for el in elements:
            element_text = clean(el.text, extra_whitespace=True)
            page_number = el.metadata.page_number or "N/A"

            # Rule 2: Handle elements that are larger than our target size on their own.
            if len(element_text) > target_chunk_size_chars:
                # First, if we have a chunk we were building, save it.
                if current_chunk_text:
                    chunks_with_metadata.append({
                        "text": current_chunk_text,
                        "page_number": sorted(list(current_chunk_page_numbers))[0],
                        "file_name": document.file_name
                    })
                    current_chunk_text = ""
                    current_chunk_page_numbers = set()

                # Now, split the oversized element using our fallback Recursive Splitter.
                sub_chunks = text_splitter.split_text(element_text)
                for sub_chunk in sub_chunks:
                    chunks_with_metadata.append({
                        "text": sub_chunk,
                        "page_number": page_number, # All sub-chunks come from the same page
                        "file_name": document.file_name
                    })
                continue # Move to the next element

            # Rule 1: Handle normal-sized elements with the grouping strategy.
            if len(current_chunk_text) + len(element_text) > target_chunk_size_chars:
                # If adding the new element would exceed the size, finalize the current chunk.
                chunks_with_metadata.append({
                    "text": current_chunk_text,
                    "page_number": sorted(list(current_chunk_page_numbers))[0],
                    "file_name": document.file_name
                })
                # And start a new chunk with the current element.
                current_chunk_text = element_text
                current_chunk_page_numbers = {page_number}
            else:
                # Otherwise, append the element's text to the current chunk.
                current_chunk_text += f"\n\n{element_text}"
                current_chunk_page_numbers.add(page_number)

        # After the loop, add the last chunk being built.
        if current_chunk_text:
            chunks_with_metadata.append({
                "text": current_chunk_text,
                "page_number": sorted(list(current_chunk_page_numbers))[0],
                "file_name": document.file_name
            })
            
        # --- END: Hybrid Chunking Logic ---

        print(f"[Parent Task] Hybrid chunking complete. Total chunks: {len(chunks_with_metadata)}")
        
        # ... (The rest of the function for batching and dispatching the chord remains exactly the same) ...
        if not chunks_with_metadata:
            document.status = "FAILED"
            document.status_message = "No content found to process."
            db.commit()
            print(f"[Parent Task] ERROR: No content extracted from document {document_id}.")
            return
        
        batch_size = 128
        chunk_batches = [chunks_with_metadata[i:i + batch_size] for i in range(0, len(chunks_with_metadata), batch_size)]
        print(f"[Parent Task] Batching complete. Total batches: {len(chunk_batches)}")

        document.status_message = f"Step 2/3: Embedding {len(chunks_with_metadata)} chunks across {len(chunk_batches)} batches."
        db.commit()

        child_tasks_group = [
            embed_and_store_batch.s(batch, str(document.id), str(document.case_id))
            for batch in chunk_batches
        ]
        
        callback_task = mark_document_as_completed.s(document_id=str(document.id))

        print(f"[Parent Task] Dispatching chord with {len(child_tasks_group)} child tasks.")
        chord(child_tasks_group)(callback_task)

    except Exception as e:
        print(f"[Parent Task] !!! An error occurred: {e}")
        traceback.print_exc()
        db.rollback()
        document = db.query(document_model.LegalDocument).filter(document_model.LegalDocument.id == document_id).first()
        if document:
            document.status = "FAILED"
            document.status_message = f"Error during preparation: {str(e)}"
            db.commit()
    finally:
        db.close()

@celery_worker.task(name="tasks.embed_and_store_batch")
def embed_and_store_batch(batch_of_chunk_objects: list[dict], document_id: str, case_id: str):
    """
    Child task: Embeds a batch of chunks and stores them in the vector database.
    This is where the heavy AI and database work happens.
    """
    import chromadb
    from sentence_transformers import SentenceTransformer

    print(f"  [Child Task] Processing batch of {len(batch_of_chunk_objects)} chunks for doc: {document_id[:8]}...")
    try:
        embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        chroma_client = chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)

        collection_name = f"case_{case_id.replace('-', '')}"
        collection = chroma_client.get_or_create_collection(name=collection_name)

        texts_to_embed = []
        metadatas = []
        ids = []

        for i, chunk_obj in enumerate(batch_of_chunk_objects):
            text_content = chunk_obj['text']
            page_number = str(chunk_obj['page_number'])
            
            texts_to_embed.append(text_content)

            chunk_metadata = {
                "document_id": document_id,
                "case_id": case_id,
                "file_name": chunk_obj['file_name'],
                "page_number": page_number,
                "absolute_text": text_content
            }
            metadatas.append(chunk_metadata)

            raw_id = f"{page_number}-{i}-{text_content}"
            unique_hash = hashlib.md5(raw_id.encode()).hexdigest()
            chunk_id = f"{document_id}_{unique_hash}"
            ids.append(chunk_id)

        embeddings = embedding_model.encode(texts_to_embed).tolist()
            
        collection.add(
            embeddings=embeddings,
            documents=texts_to_embed,
            metadatas=metadatas,
            ids=ids
        )
        print(f"  [Child Task] Successfully stored {len(batch_of_chunk_objects)} embeddings for doc: {document_id[:8]}")
        
    except Exception as e:
        print(f"  [Child Task] !!! FAILED to process batch for doc: {document_id[:8]}. Error: {e}")
        traceback.print_exc()
        raise

@celery_worker.task(name="tasks.mark_document_as_completed")
def mark_document_as_completed(*args, document_id: str, **kwargs):
    """
    Callback task: This only runs if all child tasks in the chord succeeded.
    Its only job is to set the final 'COMPLETED' status in the database.
    """
    print(f"[Callback Task] All embedding tasks completed for document_id: {document_id}")
    db = _get_db()
    try:
        document = db.query(document_model.LegalDocument).filter(document_model.LegalDocument.id == document_id).first()
        if document:
            document.status = "COMPLETED"
            document.status_message = "Successfully indexed for searching."
            document.processed_at = datetime.now(datetime.utcnow().astimezone().tzinfo)
            db.commit()
            print(f"[Callback Task] Final status 'COMPLETED' set for document: {document.file_name}")
    except Exception as e:
        print(f"[Callback Task] !!! FAILED to update final status for doc {document_id}. Error: {e}")
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


@celery_worker.task(name="tasks.embed_query_task")
def embed_query_task(query_text: str) -> list[float]:
    """
    A simple, fast task that takes a text query and returns its embedding.
    This is called synchronously by the API to leverage the worker's AI models.
    """
    from sentence_transformers import SentenceTransformer
    
    print(f"[Query Embed Task] Received query: '{query_text}'")
    try:
        # This model is pre-loaded/cached in the worker, so instantiation is fast.
        embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        embedding = embedding_model.encode(query_text).tolist()
        print("[Query Embed Task] Successfully generated embedding.")
        return embedding
    except Exception as e:
        print(f"[Query Embed Task] !!! FAILED to generate embedding for query. Error: {e}")
        traceback.print_exc()
        # Re-raise the exception so the API knows the task failed.
        raise

@celery_worker.task(name="tasks.rerank_documents_task")
def rerank_documents_task(query: str, chunks: list[dict]) -> list[dict]:
    """
    Takes a query and a list of candidate document chunks and re-ranks them for relevance.
    This uses a specialized Cross-Encoder model, which is much more accurate for this task
    than a standard embedding model.
    """
    from sentence_transformers.cross_encoder import CrossEncoder

    print(f"[Re-rank Task] Received {len(chunks)} chunks to re-rank for query: '{query}'")
    if not chunks:
        return []

    try:
        # Load the pre-downloaded Cross-Encoder model.
        # This model is optimized for semantic relevance ranking.
        cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

        # The Cross-Encoder needs pairs of (query, chunk_text) to compare.
        model_input_pairs = [[query, chunk['absolute_text']] for chunk in chunks]

        # Get the relevance scores. This is the core computation.
        scores = cross_encoder.predict(model_input_pairs)

        # Combine the original chunks with their new relevance scores.
        for chunk, score in zip(chunks, scores):
            # The corrected line
            chunk['relevance_score'] = float(score)

        # Sort the chunks in descending order based on the new score.
        # The most relevant chunks will now be at the top of the list.
        reranked_chunks = sorted(chunks, key=lambda x: x['relevance_score'], reverse=True)

        print("[Re-rank Task] Successfully re-ranked documents.")
        # Return only the top 5 most relevant chunks for the final context.
        return reranked_chunks[:5]

    except Exception as e:
        print(f"[Re-rank Task] !!! FAILED to re-rank documents. Error: {e}")
        traceback.print_exc()
        # Fallback: If re-ranking fails for any reason, return the original top 5 chunks.
        # This makes the system resilient to errors in the re-ranking step.
        return chunks[:5]
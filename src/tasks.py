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
    It is designed to be fast and delegate the heavy work to child tasks.
    """
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    from unstructured.partition.auto import partition
    from unstructured.cleaners.core import clean

    print(f"\n[Parent Task] Starting preparation for document_id: {document_id}")
    db = _get_db()
    try:
        document = db.query(document_model.LegalDocument).filter(document_model.LegalDocument.id == document_id).first()
        if not document:
            print(f"[Parent Task] ERROR: Document {document_id} not found.")
            return
        
        document.status = "PROCESSING"
        document.status_message = "Step 1/3: Parsing document content and metadata."
        db.commit()

        # Unstructured handles different file types (PDF, DOCX, etc.) automatically.
        print(f"[Parent Task] Parsing file: {document.file_path}")
        elements = partition(filename=document.file_path)

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
        
        chunks_with_metadata = []
        # We loop through each element unstructured found (e.g., a paragraph, a title).
        for element in elements:
            text = clean(element.text, extra_whitespace=True)
            page_number = element.metadata.page_number or "N/A"
            element_chunks = text_splitter.split_text(text)

            for chunk_text in element_chunks:
                chunk_object = {
                    "text": chunk_text,
                    "page_number": page_number,
                    "file_name": document.file_name
                }
                chunks_with_metadata.append(chunk_object)
        
        print(f"[Parent Task] Chunking complete. Total chunks with metadata: {len(chunks_with_metadata)}")
        if not chunks_with_metadata:
            document.status = "FAILED"
            document.status_message = "No content found to process."
            db.commit()
            print(f"[Parent Task] ERROR: No content extracted from document {document_id}.")
            return
        
        batch_size = 128  # This is a good default, not too large or small.
        chunk_batches = [chunks_with_metadata[i:i + batch_size] for i in range(0, len(chunks_with_metadata), batch_size)]
        print(f"[Parent Task] Batching complete. Total batches: {len(chunk_batches)}")

        document.status_message = f"Step 2/3: Embedding {len(chunks_with_metadata)} chunks across {len(chunk_batches)} batches."
        db.commit()

        child_tasks_group = [
            embed_and_store_batch.s(batch, str(document.id), str(document.case_id))
            for batch in chunk_batches
        ]
        
        # The 'callback' is the single task that will run only after ALL child tasks succeed.
        callback_task = mark_document_as_completed.s(document_id=str(document.id))

        print(f"[Parent Task] Dispatching chord with {len(child_tasks_group)} child tasks.")
        chord(child_tasks_group)(callback_task)

    except Exception as e:
        print(f"[Parent Task] !!! An error occurred: {e}")
        traceback.print_exc()
        db.rollback() # Undo any partial status changes.
        # Try to fetch the document again to update its status to FAILED.
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
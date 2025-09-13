import os
from datetime import datetime
from celery import chord
from celery_app import celery_worker
from database import SessionLocal
from config import settings
import models.document as document_model

# Import the heavy libraries inside the tasks to ensure the API server
# doesn't load them on startup.
def _get_db():
    return SessionLocal()

@celery_worker.task(name="tasks.prepare_and_process_document")
def prepare_and_process_document(document_id: str):
    """
    Parent task: Loads, parses, and chunks the document, then fans out
    child tasks for embedding and storage.
    """
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    from unstructured.partition.auto import partition
    print("system 1 started")
    db = _get_db()
    try:
        # 1. Update status to PROCESSING
        db.query(document_model.LegalDocument).filter(document_model.LegalDocument.id == document_id).update(
            {"status": "PROCESSING", "status_message": "Parsing and chunking document."}
        )
        db.commit()

        document = db.query(document_model.LegalDocument).filter(document_model.LegalDocument.id == document_id).first()
        if not document:
            raise FileNotFoundError("Document not found in database.")

        # 2. Parse document using unstructured
        elements = partition(filename=document.file_path)
        full_text = "\n\n".join([el.text for el in elements])
        print(full_text)
        # 3. Chunk the text
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150,
            length_function=len,
        )
        chunks = text_splitter.split_text(full_text)
        print(f"Total chunks created: {len(chunks)}")
        print(chunks)
        # 4. Create batches of chunks
        batch_size = 128
        chunk_batches = [chunks[i:i + batch_size] for i in range(0, len(chunks), batch_size)]
        print(f"Total batches created: {len(chunk_batches)}")
        # 5. Prepare the chord
        # Create a group of child tasks to run in parallel
        child_tasks_group = [
            embed_and_store_batch.s(
                batch,
                str(document.id),
                str(document.case_id)
            ) for batch in chunk_batches
        ]
        
        # Define the final callback task that runs after all child tasks are complete
        callback_task = mark_document_as_completed.s(document_id=str(document.id))

        # Execute the chord
        chord(child_tasks_group)(callback_task)

        print("system 1 finished")

    except Exception as e:
        db.query(document_model.LegalDocument).filter(document_model.LegalDocument.id == document_id).update(
            {"status": "FAILED", "status_message": f"Error during preparation: {str(e)}"}
        )
        db.commit()
    finally:
        db.close()


@celery_worker.task(name="tasks.embed_and_store_batch")
def embed_and_store_batch(batch_of_chunks: list[str], document_id: str, case_id: str):
    """
    Child task: Embeds a batch of chunks and stores them in ChromaDB.
    """
    import chromadb
    from sentence_transformers import SentenceTransformer
    print("system 2 started")
    try:
        # 1. Initialize models and clients
        embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        chroma_client = chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)
        collection = chroma_client.get_or_create_collection(name=f"case_{case_id.replace('-', '')}")

        # 2. Embed the batch of chunks
        embeddings = embedding_model.encode(batch_of_chunks).tolist()

        # 3. Prepare data for ChromaDB
        # Each chunk needs a unique ID
        ids = [f"{document_id}_{i}" for i, _ in enumerate(batch_of_chunks)]
        metadata = [{
            "document_id": document_id,
            "case_id": case_id,
        } for _ in batch_of_chunks]
        
        # 4. Store in ChromaDB
        collection.add(
            embeddings=embeddings,
            documents=batch_of_chunks,
            metadatas=metadata,
            ids=ids
        )
        print("system 2 finished")
    except Exception as e:
        # In a real app, you'd want more robust error handling, maybe a retry mechanism.
        print(f"Failed to process batch for document {document_id}. Error: {e}")
        # This error won't be automatically propagated to the user right now,
        # but the document status will remain "PROCESSING".
        raise


@celery_worker.task(name="tasks.mark_document_as_completed")
def mark_document_as_completed(document_id: str):
    """
    Callback task: Updates the document status to COMPLETED.
    """
    db = _get_db()
    try:
        db.query(document_model.LegalDocument).filter(document_model.LegalDocument.id == document_id).update(
            {"status": "COMPLETED", "status_message": "Successfully indexed.", "processed_at": datetime.now(datetime.UTC)}
        )
        db.commit()
    finally:
        db.close()
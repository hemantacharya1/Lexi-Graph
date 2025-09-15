import traceback
from datetime import datetime
from celery_app import celery_worker
from database import SessionLocal
import models.document as document_model


def _get_db():
    """Creates a new database session for the task."""
    return SessionLocal()


@celery_worker.task(name="tasks.process_document")
def process_document(document_id: str):
    # Unstructured for multi-format parsing
    from unstructured.partition.auto import partition
    """
    A task that extracts text/content from multiple document types
    (PDFs, images, HTML, JSON, etc.) using `unstructured`.
    """
    print(f"\n[Worker] Received task to process document_id: {document_id}")
    db = _get_db()

    try:
        print(f"[Worker] Starting processing for document ID: {document_id}")

        # Step 1: Get the document record
        document = (
            db.query(document_model.LegalDocument)
            .filter(document_model.LegalDocument.id == document_id)
            .first()
        )
        if not document:
            print(f"[Worker] ERROR: Document with ID {document_id} not found.")
            return

        # Step 2: Update status to PROCESSING
        print(f"[Worker] Updating status to PROCESSING for file: {document.file_name}")
        document.status = "PROCESSING"
        document.status_message = "Extracting text/content from document."
        db.commit()

        # Step 3: Use unstructured to parse the file
        print(f"[Worker] Parsing file with unstructured: {document.file_path}")
        elements = partition(filename=document.file_path)

        # Join text elements
        full_text = "\n".join([str(el) for el in elements])

        print("\n--- EXTRACTED TEXT (first 2000 chars) ---")
        print(full_text[:2000] + "...")
        print("--- END OF TEXT ---")

        # Step 4: Update status to COMPLETED
        print(f"[Worker] Content extraction successful. Updating status to COMPLETED.")
        document.status = "COMPLETED"
        document.status_message = f"Successfully extracted content from {document.file_name}"
        document.processed_at = datetime.now(datetime.utcnow().astimezone().tzinfo)
        db.commit()

        print(f"[Worker] Task for document {document_id} finished successfully.")

    except Exception as e:
        print(f"[Worker] !!! An error occurred in process_document: {e}")
        traceback.print_exc()
        db.rollback()

        # Update status to FAILED
        document = (
            db.query(document_model.LegalDocument)
            .filter(document_model.LegalDocument.id == document_id)
            .first()
        )
        if document:
            document.status = "FAILED"
            document.status_message = f"Error during processing: {str(e)}"
            db.commit()
    finally:
        db.close()

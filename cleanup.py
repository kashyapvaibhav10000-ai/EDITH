from datetime import datetime
from config import get_chroma_client


def _get_memory_collection():
    return get_chroma_client().get_or_create_collection("edith_memory")

def cleanup():
    all_items = _get_memory_collection().get()
    ids = all_items["ids"]
    documents = all_items["documents"]
    
    noise_keywords = ["hello", "hi", "bye", "okay", "ok", "thanks", "thank you"]
    to_delete = []
    
    for id_, doc in zip(ids, documents):
        if any(kw in doc.lower() for kw in noise_keywords) and len(doc) < 100:
            to_delete.append(id_)
    
    if to_delete:
        _get_memory_collection().delete(ids=to_delete)
        print(f"[{datetime.now()}] Cleaned {len(to_delete)} noise memories.")
    else:
        print(f"[{datetime.now()}] Nothing to clean.")

if __name__ == "__main__":
    cleanup()

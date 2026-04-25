import os
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from config import NOTES_DIR, MODELS, get_logger
from errors import Result

log = get_logger("rag")

Settings.embed_model = OllamaEmbedding(model_name="nomic-embed-text")
Settings.llm = Ollama(model=MODELS["chat"], request_timeout=60.0)
Settings.chunk_size = 512
Settings.chunk_overlap = 50

SUPPORTED = [".txt", ".md", ".pdf", ".py", ".js", ".json", ".csv"]

def build_index() -> Result:
    try:
        if not os.path.exists(NOTES_DIR):
            os.makedirs(NOTES_DIR)
            return Result.failure("Notes directory was empty — created it.", error_type="not_found")
        files = [f for f in os.listdir(NOTES_DIR) if any(f.endswith(ext) for ext in SUPPORTED)]
        if not files:
            return Result.failure(f"No supported files found in {NOTES_DIR}", error_type="not_found")
        log.info(f"Indexing {len(files)} files: {files}")
        reader = SimpleDirectoryReader(NOTES_DIR, required_exts=SUPPORTED, recursive=False)
        documents = reader.load_data()
        index = VectorStoreIndex.from_documents(documents)
        log.info(f"RAG index built with {len(files)} files")
        return Result.success(index)
    except Exception as e:
        return Result.from_exception(e)

def query_rag(question, index) -> Result:
    try:
        query_engine = index.as_query_engine()
        response = query_engine.query(question)
        return Result.success(str(response))
    except Exception as e:
        return Result.from_exception(e)

if __name__ == "__main__":
    index = build_index()
    if index:
        while True:
            q = input("Ask a question (or quit): ").strip()
            if q.lower() == "quit":
                break
            answer = query_rag(q, index)
            print(f"Answer: {answer}")

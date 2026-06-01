import os
from typing import Any, Sequence, List

from config import NOTES_DIR, get_logger
from errors import Result
from smart_router import smart_call

log = get_logger("rag")

try:
    from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    from llama_index.core.llms import LLM, CompletionResponse, LLMMetadata
    from llama_index.core.llms.callbacks import llm_completion_callback
    from llama_index.core.llms import ChatMessage
    LLAMA_AVAILABLE = True
except ImportError:
    LLAMA_AVAILABLE = False

if LLAMA_AVAILABLE:
    class SmartCallLLM(LLM):
        @property
        def metadata(self) -> LLMMetadata:
            """LLM metadata."""
            return LLMMetadata(
                model_name="smart_call_llm",
                context_window=4096,
                num_output=2048,
            )

        def complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
            response_text = smart_call(prompt, intent="reasoning")
            return CompletionResponse(text=response_text)

        @llm_completion_callback()
        def stream_complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
            response_text = smart_call(prompt, intent="reasoning")
            yield CompletionResponse(text=response_text)

        @llm_completion_callback()
        def chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> CompletionResponse:
            prompt = "\n".join([f"{m.role}: {m.content}" for m in messages])
            return self.complete(prompt, **kwargs)

        @llm_completion_callback()
        def stream_chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> CompletionResponse:
            prompt = "\n".join([f"{m.role}: {m.content}" for m in messages])
            return self.stream_complete(prompt, **kwargs)

        @llm_completion_callback()
        async def acomplete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
            return self.complete(prompt, **kwargs)

        @llm_completion_callback()
        async def astream_complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
            response = await self.acomplete(prompt, **kwargs)
            yield response

        @llm_completion_callback()
        async def achat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> CompletionResponse:
            return self.chat(messages, **kwargs)

        @llm_completion_callback()
        async def astream_chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> CompletionResponse:
            response = await self.achat(messages, **kwargs)
            yield response

    Settings.embed_model = HuggingFaceEmbedding(model_name="all-MiniLM-L6-v2")
    Settings.llm = SmartCallLLM()
    Settings.chunk_size = 512
    Settings.chunk_overlap = 50

SUPPORTED = [".txt", ".md", ".pdf", ".py", ".js", ".json", ".csv"]

def build_index() -> Result:
    if not LLAMA_AVAILABLE:
        return Result.failure("RAG unavailable: llama_index not installed", error_type="unavailable")
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

def index_directory(path: str) -> Result:
    """Index all supported files in given directory into a LlamaIndex VectorStoreIndex."""
    if not LLAMA_AVAILABLE:
        return Result.failure("RAG unavailable: llama_index not installed", error_type="unavailable")
    from pathlib import Path
    target = Path(path)
    if not target.exists():
        return Result.failure(f"Path does not exist: {path}", error_type="not_found")
    files = [f for f in target.rglob("*") if f.suffix.lower() in SUPPORTED]
    if not files:
        return Result.failure(f"No supported files found in {path}", error_type="not_found")
    try:
        reader = SimpleDirectoryReader(str(target), required_exts=SUPPORTED, recursive=True)
        documents = reader.load_data()
        index = VectorStoreIndex.from_documents(documents)
        log.info(f"index_directory: indexed {len(files)} files from {path}")
        return Result.success({"index": index, "count": len(files), "path": path})
    except Exception as e:
        return Result.from_exception(e)

# # raise NotImplementedError("RAG is disabled because Ollama has been removed. A cloud-based embedding model and LLM are needed.")
    
def query_rag(question, index) -> Result:
    if not LLAMA_AVAILABLE:
        return Result.failure("RAG unavailable: llama_index not installed", error_type="unavailable")
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

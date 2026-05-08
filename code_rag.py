import os
import ast
from pathlib import Path
from config import CODE_DIRS, SUPPORTED_CODE_EXTENSIONS, SKIPPED_DIRS, MODELS, get_chroma_client, get_logger

def _llm(*args, **kwargs):
    from config import safe_ollama_call
    r = safe_ollama_call(*args, **kwargs)
    return r.value if r.ok else r.error

def _llm_gen(*args, **kwargs):
    from config import safe_ollama_generate
    r = safe_ollama_generate(*args, **kwargs)
    return r.value if r.ok else r.error

log = get_logger("code_rag")


def _get_codebase_collection():
    return get_chroma_client().get_or_create_collection("edith_codebase")

def extract_python_chunks(filepath):
    chunks = []
    try:
        with open(filepath) as _fh:
            source = _fh.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = node.lineno - 1
                end = node.end_lineno
                lines = source.split("\n")[start:end]
                chunk_text = "\n".join(lines)
                chunks.append({
                    "text": chunk_text,
                    "type": type(node).__name__,
                    "name": node.name,
                    "file": filepath,
                    "lines": f"{node.lineno}-{node.end_lineno}"
                })
    except Exception:
        try:
            with open(filepath) as _fh:
                lines = _fh.readlines()
            for i in range(0, len(lines), 50):
                chunk = "".join(lines[i:i+50])
                chunks.append({
                    "text": chunk, "type": "chunk", "name": f"lines_{i}",
                    "file": filepath, "lines": f"{i}-{i+50}"
                })
        except Exception:
            pass
    return chunks

def extract_js_chunks(filepath):
    chunks = []
    try:
        with open(filepath) as _fh:
            lines = _fh.readlines()
        for i in range(0, len(lines), 50):
            chunk = "".join(lines[i:i+50])
            if chunk.strip():
                chunks.append({
                    "text": chunk, "type": "chunk", "name": f"lines_{i}",
                    "file": filepath, "lines": f"{i}-{i+50}"
                })
    except Exception:
        pass
    return chunks

def index_codebase():
    print("[EDITH RAG-C] Starting codebase indexing...")
    total = 0
    for code_dir in CODE_DIRS:
        if not os.path.exists(code_dir):
            print(f"  Skipping {code_dir} — not found")
            continue
        print(f"\n  Scanning: {code_dir}")
        for root, dirs, files in os.walk(code_dir):
            dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
            for fname in files:
                ext = Path(fname).suffix
                if ext not in SUPPORTED_CODE_EXTENSIONS:
                    continue
                filepath = os.path.join(root, fname)
                if ext == ".py":
                    chunks = extract_python_chunks(filepath)
                else:
                    chunks = extract_js_chunks(filepath)
                for chunk in chunks:
                    if len(chunk["text"].strip()) < 30:
                        continue
                    doc_id = f"{filepath}::{chunk['name']}::{chunk['lines']}"
                    _get_codebase_collection().upsert(
                        documents=[chunk["text"]],
                        metadatas=[{"file": chunk["file"], "type": chunk["type"], "name": chunk["name"], "lines": chunk["lines"]}],
                        ids=[doc_id],
                    )
                    total += 1
    print(f"\n[EDITH RAG-C] Indexed {total} code chunks!")
    log.info(f"Indexed {total} code chunks")
    return total

def query_code(question, n=4):
    results = _get_codebase_collection().query(query_texts=[question], n_results=n)
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    context = ""
    for doc, meta in zip(docs, metas):
        context += f"\n# File: {meta['file']} | {meta['type']}: {meta['name']} | Lines: {meta['lines']}\n"
        context += doc + "\n---\n"
    return context

def ask_code(question):
    print(f"\n[EDITH] Searching codebase for: {question}")
    context = query_code(question)
    prompt = f"""You are EDITH, a coding assistant. Answer the question using ONLY the code context below.
Be specific — mention file names and function names.

Code Context:
{context}

Question: {question}

Answer:"""
    return _llm_gen(MODELS["chat"], prompt)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--index":
        index_codebase()
    else:
        print("[EDITH Code RAG] Ready!")
        print("Commands: --index to index codebase, then ask questions")
        while True:
            q = input("\nAsk about your code >> ").strip()
            if q.lower() in ("exit", "quit"):
                break
            if q:
                answer = ask_code(q)
                print(f"\n[EDITH]\n{answer}")

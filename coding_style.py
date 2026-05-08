import os
import ast
import json
from config import REPOS, SKIPPED_DIRS, MODELS, CODING_PERSONALITY_JSON, CODING_PERSONALITY_TXT, get_logger

def _llm(*args, **kwargs):
    from config import safe_ollama_call
    r = safe_ollama_call(*args, **kwargs)
    return r.value if r.ok else r.error

def _llm_gen(*args, **kwargs):
    from config import safe_ollama_generate
    r = safe_ollama_generate(*args, **kwargs)
    return r.value if r.ok else r.error

log = get_logger("coding_style")

def analyze_python_style(filepath):
    stats = {"functions": 0, "classes": 0, "comments": 0, "avg_function_len": 0, "uses_async": False, "uses_type_hints": False}
    try:
        with open(filepath) as _fh:
            source = _fh.read()
        lines = source.split("\n")
        stats["comments"] = sum(1 for l in lines if l.strip().startswith("#"))
        tree = ast.parse(source)
        func_lengths = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stats["functions"] += 1
                if isinstance(node, ast.AsyncFunctionDef):
                    stats["uses_async"] = True
                if node.returns or any(arg.annotation for arg in node.args.args):
                    stats["uses_type_hints"] = True
                func_lengths.append(node.end_lineno - node.lineno)
            elif isinstance(node, ast.ClassDef):
                stats["classes"] += 1
        if func_lengths:
            stats["avg_function_len"] = round(sum(func_lengths) / len(func_lengths))
    except Exception:
        pass
    return stats

def extract_style():
    print("[EDITH] Analyzing your coding style...")
    total = {"functions": 0, "classes": 0, "comments": 0, "lens": [], "async_files": 0, "typed_files": 0, "py_files": 0, "ts_files": 0}

    for repo in REPOS:
        if not os.path.exists(repo):
            continue
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
            for f in files:
                if f.endswith(".py"):
                    total["py_files"] += 1
                    stats = analyze_python_style(os.path.join(root, f))
                    total["functions"] += stats["functions"]
                    total["classes"] += stats["classes"]
                    total["comments"] += stats["comments"]
                    if stats["avg_function_len"]:
                        total["lens"].append(stats["avg_function_len"])
                    if stats["uses_async"]:
                        total["async_files"] += 1
                    if stats["uses_type_hints"]:
                        total["typed_files"] += 1
                elif f.endswith((".ts", ".tsx", ".js", ".jsx")):
                    total["ts_files"] += 1

    avg_len = round(sum(total["lens"]) / len(total["lens"])) if total["lens"] else 15
    comment_ratio = round(total["comments"] / max(total["functions"], 1), 1)

    style = {
        "language_preference": "Python + TypeScript (Next.js)",
        "function_style": "concise" if avg_len < 20 else "detailed",
        "avg_function_length": avg_len,
        "uses_async": total["async_files"] > total["py_files"] * 0.3,
        "uses_type_hints": total["typed_files"] > total["py_files"] * 0.3,
        "comment_density": "minimal" if comment_ratio < 1 else "moderate",
        "prefers_classes": total["classes"] > total["functions"] * 0.3,
        "py_files_written": total["py_files"],
        "ts_files_written": total["ts_files"],
        "frameworks": ["Next.js 14", "FastAPI", "Prisma", "TailwindCSS"],
        "patterns": ["REST APIs", "React components", "Database ORM", "JWT auth"],
    }

    personality = f"""You are EDITH's coding assistant, trained to code like Vaibhav Kashyap.

VAIBHAV'S CODING STYLE (extracted from {total['py_files']} Python + {total['ts_files']} TypeScript files):

- Prefers {style['function_style']} functions (avg {avg_len} lines each)
- Uses {'async/await patterns' if style['uses_async'] else 'synchronous code mostly'}
- {'Uses type hints' if style['uses_type_hints'] else 'Minimal type hints'}
- Comment style: {style['comment_density']} comments
- Primary stack: {', '.join(style['frameworks'])}
- Common patterns: {', '.join(style['patterns'])}
- Builds: pharmacy SaaS (AyurStock Pro) + personal AI systems

RULES WHEN CODING FOR VAIBHAV:
1. Write {style['function_style']} functions, not sprawling ones
2. Use {'async/await' if style['uses_async'] else 'simple functions'} where appropriate
3. Follow Next.js 14 App Router conventions for frontend
4. Use Prisma + PostgreSQL patterns for database code
5. Keep variable names descriptive but not overly verbose
6. Prefer functional approaches over heavy class hierarchies
7. Always include error handling
8. For Python: follow the EDITH module pattern (simple scripts, subprocess for isolation)"""

    with open(CODING_PERSONALITY_JSON, "w") as f:
        json.dump(style, f, indent=2)
    with open(CODING_PERSONALITY_TXT, "w") as f:
        f.write(personality)

    print("\n[EDITH] Style Analysis Complete!")
    print(f"  Python files analyzed : {total['py_files']}")
    print(f"  TypeScript files      : {total['ts_files']}")
    print(f"  Avg function length   : {avg_len} lines")
    print(f"  Async usage           : {'Yes' if style['uses_async'] else 'No'}")
    print(f"  Type hints            : {'Yes' if style['uses_type_hints'] else 'No'}")
    print(f"  Comment style         : {style['comment_density']}")
    print(f"\n[EDITH] Personality saved to coding_personality.txt")
    return personality

def ask_code_like_vaibhav(question):
    with open(CODING_PERSONALITY_TXT) as _fh:
        personality = _fh.read()
    prompt = personality + f"\n\nTask: {question}\n\nWrite the code:"
    return _llm_gen(MODELS["chat"], prompt)

if __name__ == "__main__":
    if not os.path.exists(CODING_PERSONALITY_TXT):
        extract_style()
    print("\n[EDITH Coding Assistant] Powered by your style")
    print("Ask me to write any code — I'll code like you!\n")
    while True:
        q = input("What should I build? >> ").strip()
        if q.lower() in ("exit", "quit"):
            break
        if q:
            print("\n[EDITH] Coding...\n")
            code = ask_code_like_vaibhav(q)
            print(code)
            print()

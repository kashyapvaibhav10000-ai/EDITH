import docker
from tools import confirm as hitl_confirm

client = None

def run_code_in_sandbox(code, language="python"):
    if not hitl_confirm(f"RUN {language} code in Docker sandbox:\n{code}"):
        return "❌ Cancelled."
    
    if language == "python":
        image = "python:3.11-slim"
        cmd = ["python", "-c", code]
    elif language == "bash":
        image = "alpine:latest"
        cmd = ["sh", "-c", code]
    else:
        return "Unsupported language."

    try:
        global client
        if client is None:
            try:
                client = docker.from_env()
            except Exception as e:
                return f"❌ Docker unavailable. Start Docker or fix socket permissions. Error: {e}"

        result = client.containers.run(
            image,
            cmd,
            remove=True,
            mem_limit="256m",
            network_disabled=True,
        )
        return f"✅ Output:\n{result.decode()}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# Test it
if __name__ == "__main__":
    print(run_code_in_sandbox("print('Hello from EDITH sandbox!')"))

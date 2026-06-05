import asyncio

try:
    import docker
    from tools import confirm as hitl_confirm
    client = None
    _DOCKER_AVAILABLE = True
except ImportError:
    docker = None
    client = None
    _DOCKER_AVAILABLE = False
    def hitl_confirm(prompt):
        return False

def run_code_in_sandbox(code, language="python"):
    # Early exit if docker not available
    if not _DOCKER_AVAILABLE:
        return "[Sandbox unavailable — docker module not installed on this node]"
    
    try:
        loop = asyncio.get_running_loop()
        if loop is not None:
            raise NotImplementedError(
                "run_code_in_sandbox blocks on input() — cannot call from async context. "
                "Use asyncio.to_thread(run_code_in_sandbox, code, language) instead."
            )
    except RuntimeError:
        pass  # No running loop — safe to call input()

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

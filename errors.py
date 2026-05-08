from dataclasses import dataclass
from typing import Any

@dataclass
class Result:
    ok: bool
    value: Any = ""
    error: str = ""
    error_type: str = ""  # "timeout", "connection", "permission", "unknown"
    
    @classmethod
    def success(cls, value: Any = "") -> "Result":
        return cls(ok=True, value=value)
        
    @classmethod
    def failure(cls, error: str, error_type: str = "unknown") -> "Result":
        return cls(ok=False, error=error, error_type=error_type)
        
    @classmethod
    def from_exception(cls, e: Exception) -> "Result":
        err_str = str(e).lower()
        err_type = "timeout" if "timeout" in err_str else "connection" if "connect" in err_str else "unknown"
        return cls(ok=False, error=str(e), error_type=err_type)

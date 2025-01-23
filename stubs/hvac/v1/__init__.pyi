"""Type stubs for hvac.v1."""
from typing import Any, Dict, Optional

class Client:
    """Type stub for hvac.v1.Client."""
    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
        cert: Optional[tuple[str, str]] = None,
        verify: bool = True,
        timeout: int = 30,
        proxies: Optional[Dict[str, str]] = None,
        allow_redirects: bool = True,
        namespace: Optional[str] = None,
        **kwargs: Any
    ) -> None: ...

    def list(self, path: str, mount_point: Optional[str] = None) -> Dict[str, Any]: ...
    def read(self, path: str, mount_point: Optional[str] = None) -> Dict[str, Any]: ...

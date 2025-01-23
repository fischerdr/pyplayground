"""Type stubs for vault_utils module."""
from typing import Optional
import hvac

def create_vault_client(
    vault_addr: Optional[str] = None,
    vault_token: Optional[str] = None,
    namespace: Optional[str] = None
) -> hvac.Client: ...

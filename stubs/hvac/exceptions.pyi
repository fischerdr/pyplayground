"""Type stubs for hvac.exceptions."""

class VaultError(Exception):
    """Base class for Vault errors."""
    pass

class InvalidRequest(VaultError):
    """Exception raised when Vault request is invalid."""
    pass

"""Type stubs for pick package."""
from typing import Any, List, Optional, Tuple, Union

def pick(
    options: List[Any],
    title: Optional[str] = None,
    indicator: str = '*',
    default_index: int = 0,
    multiselect: bool = False,
    min_selection_count: int = 0,
    options_map_func: Optional[Any] = None
) -> Union[Tuple[Any, int], List[Tuple[Any, int]]]: ...

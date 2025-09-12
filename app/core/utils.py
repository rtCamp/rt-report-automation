import datetime
import time
from typing import Any, TypeGuard, TypeVar

T = TypeVar("T")

def to_unix(dt):
    """
    Convert a datetime.date or datetime.datetime object to a Unix timestamp (int).
    If already an int, returns as is.
    """
    if isinstance(dt, datetime.date):
        return int(time.mktime(dt.timetuple()))
    return int(dt)

def validate(data: Any, type_: type[T] | tuple[type, ...]) -> TypeGuard[T]:
    """
    Validate that `data` is of the given type (or tuple of types).
    - Raises TypeError if not.
    - Narrows type for static checkers (Pylance/MyPy).
    """
    if not isinstance(data, type_):
        if isinstance(type_, tuple):
            type_names = " or ".join(t.__name__ for t in type_)
            raise TypeError(f"Expected {type_names}, got {type(data).__name__}")
        raise TypeError(f"Expected {type_.__name__}, got {type(data).__name__}")
    return True

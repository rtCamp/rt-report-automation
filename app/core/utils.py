"""Utility functions for the application."""

import datetime
import logging
import time
from typing import Any, NoReturn, TypeGuard, TypeVar

from fastapi import HTTPException

T = TypeVar("T")


def to_unix(dt):
	"""Convert a datetime.date or datetime.datetime object to a Unix timestamp (int).

	If already an int, returns as is.
	"""
	if isinstance(dt, datetime.date):
		return int(time.mktime(dt.timetuple()))
	return int(dt)


def validate(data: Any, type_: type[T] | tuple[type, ...]) -> TypeGuard[T]:
	"""Validate that `data` is of the given type (or tuple of types).

	- Raises TypeError if not.
	- Narrows type for static checkers (Pylance/MyPy).
	"""
	if not isinstance(data, type_):
		if isinstance(type_, tuple):
			type_names = " or ".join(t.__name__ for t in type_)
			raise TypeError(f"Expected {type_names}, got {type(data).__name__}")
		raise TypeError(f"Expected {type_.__name__}, got {type(data).__name__}")
	return True


def log_and_raise(
	logger: logging.Logger,
	message: str,
	exception_type: type[Exception] = ValueError,
	cause: Exception | None = None,
	http_status_code: int | None = None,
) -> NoReturn:
	"""Log an error message and raise an exception.

	This utility provides a consistent pattern for error handling across the
	application. It ensures that errors are properly logged before raising
	exceptions, and properly chains exceptions when a cause is provided.

	Args:
		logger: Logger instance to use for logging.
		message: Error message to log and raise.
		exception_type: Type of exception to raise (default: ValueError).
			Ignored if http_status_code is provided.
		cause: Original exception to chain from (optional). When provided, the error
			message will include details from the cause.
		http_status_code: HTTP status code for FastAPI controllers (optional).
			When provided, raises HTTPException instead of exception_type.

	Raises:
		HTTPException: If http_status_code is provided.
		The specified exception_type: If http_status_code is not provided.

	Examples:
		>>> log_and_raise(logger, "Invalid input")
		# Logs: "Invalid input" and raises ValueError("Invalid input")

		>>> log_and_raise(logger, "Operation failed", Exception, original_error)
		# Logs: "Operation failed: <error details>" and raises Exception

		>>> log_and_raise(logger, "Not found", http_status_code=404, cause=e)
		# Logs: "Not found: <error details>" and raises HTTPException(404) from e

	"""
	# Determine which exception to raise
	if http_status_code:
		exception = HTTPException(status_code=http_status_code, detail=message)
	else:
		exception = exception_type(message)

	# Raise with or without chaining
	if cause:
		logger.error("%s: %s", message, cause)
		raise exception from cause
	logger.error("%s", message)
	raise exception

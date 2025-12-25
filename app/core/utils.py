"""Utility functions for the application."""

import datetime
import logging
import time
from typing import Any, NoReturn, TypeGuard, TypeVar

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
) -> NoReturn:
	"""Log an error message and raise an exception.

	This utility provides a consistent pattern for error handling across the
	application. It ensures that errors are properly logged before raising
	exceptions, and properly chains exceptions when a cause is provided.

	Args:
		logger: Logger instance to use for logging.
		message: Error message to log and raise.
		exception_type: Type of exception to raise (default: ValueError).
		cause: Original exception to chain from (optional). When provided, the error
			message will include details from the cause.

	Raises:
		The specified exception_type with the given message.

	Examples:
		>>> log_and_raise(logger, "Invalid input")
		# Logs: "Invalid input" and raises ValueError("Invalid input")

		>>> log_and_raise(logger, "Operation failed", Exception, original_error)
		# Logs: "Operation failed: <error details>" and raises Exception

	"""
	if cause:
		logger.error("%s: %s", message, cause)
		raise exception_type(message) from cause
	logger.error("%s", message)
	raise exception_type(message)

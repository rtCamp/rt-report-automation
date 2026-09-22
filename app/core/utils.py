"""Utility functions for the application."""

import datetime
import logging
from typing import Any, NoReturn, TypeGuard, TypeVar

from fastapi import HTTPException

T = TypeVar("T")


def to_unix(dt):
	"""Convert date/datetime/int values to a Unix timestamp (seconds).

	Conversion rules:
	- int: returned as-is
	- date: interpreted as 00:00:00 UTC on that date
	- datetime: timezone-aware values keep their tz; naive values are treated as UTC
	"""
	if isinstance(dt, int):
		return dt

	if isinstance(dt, datetime.datetime):
		if dt.tzinfo is None:
			dt = dt.replace(tzinfo=datetime.UTC)
		return int(dt.timestamp())

	if isinstance(dt, datetime.date):
		dt_utc = datetime.datetime.combine(
			dt,
			datetime.time.min,
			tzinfo=datetime.UTC,
		)
		return int(dt_utc.timestamp())

	raise TypeError(f"Unsupported type for to_unix: {type(dt).__name__}")


def to_unix_inclusive_date_range(
	start_date: datetime.date,
	end_date: datetime.date,
) -> tuple[int, int]:
	"""Convert date range to Unix timestamps with inclusive end-date semantics.

	Returns:
		tuple[int, int]:
			- start_ts at 00:00:00 UTC on start_date (inclusive)
			- end_ts at 00:00:00 UTC on end_date + 1 day (exclusive)

	"""
	if start_date > end_date:
		raise ValueError("start_date must be less than or equal to end_date")

	start_ts = to_unix(start_date)
	end_ts = to_unix(end_date + datetime.timedelta(days=1))
	return start_ts, end_ts


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
		try:
			exception = exception_type(message)
		except TypeError:
			# Some exception classes (e.g. slack_sdk.errors.SlackApiError,
			# which requires a `response` argument) can't be constructed
			# from a bare message string -- this matters here because
			# callers commonly pass `exception_type=exc.__class__` to
			# preserve the original exception's type. Falling back to a
			# plain Exception avoids crashing on that construction (which
			# would mask the real error with a confusing TypeError); the
			# original exception's real type and details are still
			# preserved via `raise ... from cause` below.
			exception = Exception(message)

	# Raise with or without chaining
	if cause:
		logger.error("%s: %s", message, cause)
		raise exception from cause
	logger.error("%s", message)
	raise exception

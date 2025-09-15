"""Custom exception classes for the application."""

from fastapi import HTTPException, status


class AuthenticationError(HTTPException):
	"""Custom exception for authentication errors."""

	def __init__(self, message: str = "Could not validate credentials"):
		"""Initialize the AuthenticationError with a message."""
		super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)


class InternalServerError(HTTPException):
	"""Custom exception for Internal Server errors."""

	def __init__(
		self,
		error: Exception | str,
		message: str = "An unexpected error occurred.",
		hint: str | None = None,
	):
		"""Initialize the InternalServerError with details."""
		super().__init__(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail={
				"error": "Internal Server Error",
				"message": f"{message}: {str(error)}",
				"hint": hint,
			},
		)

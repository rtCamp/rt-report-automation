from fastapi import HTTPException, status


class InternalServerError(HTTPException):
	"""Custom exception for Internal Server errors."""

	def __init__(
		self,
		error: Exception | str,
		message: str = "An unexpected error occurred.",
		hint: str | None = None,
	):
		super().__init__(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail={
				"error": "Internal Server Error",
				"message": f"{message}: {str(error)}",
				"hint": hint,
			},
		)

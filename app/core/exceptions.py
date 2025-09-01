from fastapi import HTTPException, status


class AuthenticationError(HTTPException):
	def __init__(self, message: str = "Could not validate credentials"):
		super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)

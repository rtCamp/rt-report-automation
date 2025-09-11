from datetime import datetime


def format_to_yymmdd(iso_date: str) -> str:
	"""Formats an ISO 8601 date string to 'YYYY-MM-DD'.
	Args:
		iso_date (str): The date string in ISO 8601 format.
	Returns:
		str: The formatted date string in 'YYYY-MM-DD' format.
	"""
	date = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))

	yy = date.year
	mm = f"{date.month:02d}"
	dd = f"{date.day:02d}"

	return f"{yy}-{mm}-{dd}"

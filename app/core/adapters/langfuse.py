from dotenv import load_dotenv
from langfuse import get_client

load_dotenv()

# Initialize Langfuse client
langfuse = get_client()

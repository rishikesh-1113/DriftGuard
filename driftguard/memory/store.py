"""
Memory store for DriftGuard.
On /approve: embeds the finding + manifest context and stores in Qdrant.
This is what makes the agent learn team conventions over time.
"""

import os
import uuid
import google.genai as genai
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
from dotenv import load_dotenv

load_dotenv()

COLLECTION_NAME = "driftguard_reviews"
EMBEDDING_MODEL = "gemini-embedding-001"
VECTOR_SIZE = 3072  # gemini-embedding-001 output size


def get_qdrant_client() -> QdrantClient:
    url = os.getenv("QDRANT_URL")
    api_key = os.getenv("QDRANT_API_KEY")
    if not url or not api_key:
        raise ValueError("QDRANT_URL and QDRANT_API_KEY must be set in .env")
    return QdrantClient(url=url, api_key=api_key)


def get_embedding(text: str) -> list:
    """Generate embedding using gemini-embedding-001 (free with Gemini API key)."""
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    result = client.models.embed_content(model=EMBEDDING_MODEL, contents=text)
    return result.embeddings[0].values


def ensure_collection_exists(client: QdrantClient):
    """Create the Qdrant collection if it doesn't exist yet."""
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def build_embedding_text(rule: str, message: str, file_path: str, approved_fix: str) -> str:
    """
    Build the text we embed — combines issue type + context + approved fix.
    This is what gets searched later when a similar issue appears.
    Sanitizes inputs to prevent injection of control characters.
    """
    def _sanitize(s: str) -> str:
        return str(s).replace("|", "").replace("\n", " ").replace("\r", "").strip()

    return (
        f"rule: {_sanitize(rule)} | issue: {_sanitize(message)} "
        f"| file: {_sanitize(file_path)} | approved_fix: {_sanitize(approved_fix)}"
    )


def store_approved_finding(
    rule: str,
    severity: str,
    message: str,
    reasoning: str,
    approved_fix: str,
    file_path: str,
    pr_number: int,
    repo_name: str,
) -> str:
    """
    Embed and store an approved finding in Qdrant.
    Called when a human comments /approve on a PR.
    Returns the stored point ID.
    """
    client = get_qdrant_client()
    ensure_collection_exists(client)

    text = build_embedding_text(rule, message, file_path, approved_fix)
    embedding = get_embedding(text)

    point_id = str(uuid.uuid4())

    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "rule": rule,
                    "severity": severity,
                    "message": message,
                    "reasoning": reasoning,
                    "approved_fix": approved_fix,
                    "file_path": file_path,
                    "pr_number": pr_number,
                    "repo_name": repo_name,
                },
            )
        ],
    )

    return point_id

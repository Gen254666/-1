# -*- coding: utf-8 -*-
"""Warm the embedding model cache inside the mcp-server container."""
import os

from steel_core.knowledge.service import get_client, search_knowledge

client = get_client(os.environ.get("CHROMA_PATH", "/app/chroma_data"))
citations = search_knowledge(
    client,
    query="含税价怎么计算",
    collections=["kb_public"],
    top_k=5,
    user_id="00000000-0000-0000-0000-000000000000",
)
print("citations:", len(citations))
for c in citations:
    print(c.index, c.title, c.score, c.snippet[:80].replace("\n", " "))

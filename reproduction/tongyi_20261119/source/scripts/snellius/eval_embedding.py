"""Shared, explicit retriever encoding settings for corpus and query vectors."""
import torch

QUERY_INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"
DEFAULT_RETRIEVAL = {
    "pooling": "last_token", "padding_side": "left", "max_length": 512,
    "query_prefix": "Instruct: " + QUERY_INSTRUCTION + "\nQuery:",
    "passage_prefix": "", "normalize": True,
}
E5_RETRIEVAL = {
    **DEFAULT_RETRIEVAL, "pooling": "mean", "padding_side": "right",
    "query_prefix": "Instruct: " + QUERY_INSTRUCTION + "\nQuery: ",
}


def retrieval_settings(assets):
    return {**DEFAULT_RETRIEVAL, **assets.get("retrieval", {})}


def pool_embeddings(hidden, attention_mask, pooling):
    if pooling == "mean":
        hidden = hidden.float().masked_fill(~attention_mask[..., None].bool(), 0.0)
        return hidden.sum(dim=1) / attention_mask.sum(dim=1, keepdim=True).clamp_min(1)
    if pooling == "last_token":
        # Both left and right padding are supported, including mixed lengths.
        positions = torch.arange(attention_mask.shape[1], device=attention_mask.device)
        last = (positions[None, :] * attention_mask).max(dim=1).values
        return hidden[torch.arange(hidden.shape[0], device=hidden.device), last].float()
    raise ValueError("Unsupported pooling: " + pooling)

"""Single-token answer labels and the pinned model's actual context capacity."""

import json
import string
from functools import lru_cache
from itertools import chain
from pathlib import Path


@lru_cache(maxsize=32)
def label_ids(tokenizer, count: int) -> dict[str, int]:
    if count < 1:
        raise ValueError("At least one candidate is required")
    # Preserve the original labels for small catalogs. Larger catalogs use other
    # ordinary vocabulary tokens, always checked for exact one-token round trips.
    vocabulary = (sorted(tokenizer.get_vocab(), key=lambda label: (len(label), label))
                  if count > len(string.ascii_uppercase) else [])
    labels, used = {}, set()
    for label in chain(string.ascii_uppercase, vocabulary):
        if not label.isascii() or not label.isalnum() or label in labels:
            continue
        encoded = tokenizer.encode(label, add_special_tokens=False)
        if len(encoded) != 1 or encoded[0] in used or tokenizer.decode(encoded) != label:
            continue
        labels[label] = encoded[0]
        used.add(encoded[0])
        if len(labels) == count:
            return labels
    raise ValueError("Catalog exceeds the tokenizer's distinct single-token labels")


def context_limit(weights_path: str) -> int:
    config = json.loads((Path(weights_path) / "config.json").read_text())
    limit = config.get("text_config", config).get("max_position_embeddings")
    if type(limit) is not int or limit < 1:
        raise ValueError("Pinned model has no valid max_position_embeddings")
    return limit

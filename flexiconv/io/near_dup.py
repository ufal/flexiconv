"""
Near-duplicate detection via MinHash and LSH.

Uses word-level shingles, MinHash signatures, and banded LSH to find
candidate pairs with high Jaccard similarity without all-pairs comparison.
"""
from __future__ import annotations

import hashlib
import re
import struct
from typing import List, Optional, Set, Tuple

# Defaults: 100 minhash components, 20 bands of 5 rows → candidate threshold ~0.55
# Verify with exact signature similarity (default threshold 0.8)
NUM_HASHES = 100
NUM_BANDS = 20
ROWS_PER_BAND = 5
SHINGLE_SIZE = 5  # word n-grams
_PRIME = (1 << 61) - 1  # Mersenne prime for minhash mod


def _make_permutation(seed: int, i: int) -> Tuple[int, int]:
    """Return (a, b) for permutation h(x) = (a*x + b) % _PRIME, a != 0."""
    h = hashlib.sha256(f"{seed}-{i}".encode()).digest()
    a = struct.unpack("<Q", h[:8])[0] % (_PRIME - 1) + 1
    b = struct.unpack("<Q", h[8:16])[0] % _PRIME
    return (a, b)


# Cache permutations for NUM_HASHES
_PERMS: Optional[List[Tuple[int, int]]] = None


def _permutations(seed: int = 42) -> List[Tuple[int, int]]:
    global _PERMS
    if _PERMS is None:
        _PERMS = [_make_permutation(seed, i) for i in range(NUM_HASHES)]
    return _PERMS


def shingle_text(text: str, n: int = SHINGLE_SIZE) -> Set[int]:
    """Return set of integer hashes of word n-grams. Words are tokenized by whitespace."""
    words = re.split(r"\s+", text.strip())
    if len(words) < n:
        if not words or not words[0]:
            return set()
        return {_hash_string(" ".join(words))}
    out: Set[int] = set()
    for i in range(len(words) - n + 1):
        shingle = " ".join(words[i : i + n])
        out.add(_hash_string(shingle))
    return out


def _hash_string(s: str) -> int:
    """Stable 64-bit hash of string (for shingles)."""
    h = hashlib.sha256(s.encode("utf-8")).digest()
    return struct.unpack("<Q", h[:8])[0] % _PRIME


def minhash_signature(shingles: Set[int], num_hashes: int = NUM_HASHES, seed: int = 42) -> List[int]:
    """Compute MinHash signature (list of num_hashes ints) from shingle set."""
    perms = _permutations(seed)[:num_hashes]
    sig: List[int] = []
    for a, b in perms:
        min_val = _PRIME
        for s in shingles:
            val = (a * s + b) % _PRIME
            if val < min_val:
                min_val = val
        sig.append(min_val if shingles else 0)
    return sig


def lsh_bands(signature: List[int], num_bands: int = NUM_BANDS, rows_per_band: int = ROWS_PER_BAND) -> List[Tuple[int, str]]:
    """Return list of (band_id, bucket_key) for LSH indexing. bucket_key is hex hash of band's values."""
    bands: List[Tuple[int, str]] = []
    for b in range(num_bands):
        start = b * rows_per_band
        end = min(start + rows_per_band, len(signature))
        if start >= end:
            break
        chunk = tuple(signature[start:end])
        key = hashlib.sha256(struct.pack(f"<{len(chunk)}Q", *chunk)).hexdigest()[:16]
        bands.append((b, key))
    return bands


def signature_similarity(sig_a: List[int], sig_b: List[int]) -> float:
    """Estimated Jaccard similarity from two MinHash signatures (fraction of matching components)."""
    if not sig_a or not sig_b or len(sig_a) != len(sig_b):
        return 0.0
    matches = sum(1 for i, j in zip(sig_a, sig_b) if i == j)
    return matches / len(sig_a)


def signature_from_blob(blob: bytes) -> List[int]:
    """Deserialize signature from blob (packed uint64s, little-endian)."""
    n = len(blob) // 8
    return list(struct.unpack(f"<{n}Q", blob))


def signature_to_blob(signature: List[int]) -> bytes:
    """Serialize signature to blob (packed uint64s, little-endian)."""
    return struct.pack(f"<{len(signature)}Q", *signature)

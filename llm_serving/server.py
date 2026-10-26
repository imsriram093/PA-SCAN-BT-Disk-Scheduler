"""
server.py  -  The (simulated) GPU hardware: its limits and its prefix cache.

The disk project had one hardware fact: moving the arm costs time.
The GPU has three limits plus one cache:
    - a batch can hold at most `max_seqs` requests,
    - all running requests must fit in the KV-cache memory,
    - only `max_prefill_tokens` prompt tokens can be processed per step,
    - a shared prefix that is still cached does not have to be re-computed.
"""

from collections import OrderedDict
from dataclasses import dataclass

from llm_serving import config


@dataclass
class ServerSpec:
    max_seqs: int = config.MAX_BATCH_SEQS
    kv_cache_tokens: int = config.KV_CACHE_TOKENS
    max_prefill_tokens: int = config.MAX_PREFILL_TOKENS
    prefix_cache_tokens: int = config.PREFIX_CACHE_TOKENS
    step_base_ms: float = config.STEP_BASE_MS
    decode_ms_per_seq: float = config.DECODE_MS_PER_SEQ
    prefill_ms_per_token: float = config.PREFILL_MS_PER_TOKEN

    def step_time(self, decoding, prefill_tokens):
        """Duration of one step with `decoding` running requests and `prefill_tokens` prompt tokens."""
        return (self.step_base_ms + self.decode_ms_per_seq * decoding
                + self.prefill_ms_per_token * prefill_tokens)


class PrefixCache:
    """Least-Recently-Used cache of shared prefixes, measured in tokens."""

    def __init__(self, capacity_tokens):
        self.capacity = capacity_tokens
        self.entries = OrderedDict()     # prefix_id -> tokens, oldest first
        self.used = 0

    def contains(self, prefix_id):
        """Look without touching (used to estimate a request's cost before admitting it)."""
        return prefix_id in self.entries

    def lookup(self, prefix_id, tokens):
        """Use the prefix: return True on a hit. On a miss the prefix is computed and cached."""
        if prefix_id in self.entries:
            self.entries.move_to_end(prefix_id)
            return True
        if tokens <= self.capacity:
            while self.used + tokens > self.capacity:
                _, old = self.entries.popitem(last=False)     # evict the least recently used
                self.used -= old
            self.entries[prefix_id] = tokens
            self.used += tokens
        return False

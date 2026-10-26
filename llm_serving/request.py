"""
request.py  -  What ONE LLM inference request looks like.

"Tenant 3 (rag-search, STANDARD) sent a prompt that starts with shared
document #17 (2000 tokens), adds 640 tokens of its own, and wants 180
output tokens. It arrived at t = 1250 ms."
"""

from dataclasses import dataclass, field


@dataclass
class Request:
    # ---- filled in by the workload generator (the INPUT) ----
    request_id: int          # unique number of this request
    tenant_id: int           # which tenant (customer / app) sent it
    priority: int            # 0 = INTERACTIVE, 1 = STANDARD, 2 = BATCH  (see config.py)
    arrival_time: float      # when the request reached the server queue (ms)
    prefix_id: int           # which shared prefix (system prompt / document) the prompt starts with
    prefix_tokens: int       # length of that shared prefix
    prompt_tokens: int       # tokens of the prompt that are unique to this request
    output_tokens: int       # tokens the model will generate

    # ---- filled in by the simulator (the OUTPUT) ----
    admit_time: float = field(default=None)        # first time it entered the batch
    first_token_time: float = field(default=None)  # when its first output token was produced
    finish_time: float = field(default=None)       # when its last output token was produced
    generated: int = field(default=0)              # output tokens produced so far
    preemptions: int = field(default=0)            # times it was pushed out of the batch
    cache_hit: bool = field(default=False)         # was its prefix in the cache on (last) admission?

    @property
    def prompt_len(self):
        """Full prompt length (shared prefix + own part)."""
        return self.prefix_tokens + self.prompt_tokens

    @property
    def kv_tokens(self):
        """KV-cache memory reserved while it runs (whole prompt + every output token)."""
        return self.prefix_tokens + self.prompt_tokens + self.output_tokens

    @property
    def ttft(self):
        """Time To First Token: arrival -> first output token. The LLM version of 'waiting time'."""
        return self.first_token_time - self.arrival_time

    @property
    def latency(self):
        """End-to-end latency: arrival -> last output token."""
        return self.finish_time - self.arrival_time

    @property
    def tpot(self):
        """Time Per Output Token after the first one (how fast the answer streams)."""
        if self.output_tokens <= 1:
            return 0.0
        return (self.finish_time - self.first_token_time) / (self.output_tokens - 1)

    def fresh_copy(self):
        """Return an un-served copy, so every algorithm gets IDENTICAL input."""
        return Request(self.request_id, self.tenant_id, self.priority, self.arrival_time,
                       self.prefix_id, self.prefix_tokens, self.prompt_tokens, self.output_tokens)

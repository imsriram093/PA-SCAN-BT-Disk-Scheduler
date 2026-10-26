"""
request.py  -  What ONE disk I/O request looks like.

Think of it as a "ticket" a process hands to the operating system:
"Process 3 wants to read cylinder 87, it is LOW priority, and it asked at t = 12.5 ms".
"""

from dataclasses import dataclass, field


@dataclass
class Request:
    # ---- filled in by the workload generator (the INPUT) ----
    request_id: int          # unique number of this request
    process_id: int          # which process asked for it
    track: int               # cylinder number the head must travel to
    arrival_time: float      # when the request reached the disk queue (ms)
    priority: int            # 0 = HIGH, 1 = MEDIUM, 2 = LOW  (see config.py)

    # ---- filled in by the simulator (the OUTPUT) ----
    start_time: float = field(default=None)    # when the head reached it and began reading
    finish_time: float = field(default=None)   # when the read/write finished
    seek_distance: int = field(default=0)      # cylinders the head moved to reach it

    @property
    def waiting_time(self):
        """Time spent waiting in the queue + travelling to it (arrival -> start)."""
        return self.start_time - self.arrival_time

    @property
    def turnaround_time(self):
        """Total time in the system (arrival -> finish)."""
        return self.finish_time - self.arrival_time

    def fresh_copy(self):
        """Return an un-served copy, so every algorithm gets IDENTICAL input."""
        return Request(self.request_id, self.process_id, self.track,
                       self.arrival_time, self.priority)

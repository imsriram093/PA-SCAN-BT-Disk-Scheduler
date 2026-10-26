"""
baseline.py  -  COMPONENT 1: the classic disk-scheduling algorithms.

The faculty asks for ONE baseline; our main baseline is SCAN (the "elevator").
FCFS, SSTF, C-SCAN and LOOK are included as extra reference points, because
your report looks stronger when it shows where the new algorithm sits among
ALL the textbook algorithms.

Every algorithm is a small class with the same two methods:
    reset(head, direction, disk_size)   -> forget everything before a new run
    select(pending, head, now)          -> return (chosen_request, via_cylinders)

`via_cylinders` is a list of cylinders the head must touch BEFORE reaching the
chosen request. It is empty for most algorithms; SCAN uses it to travel to the
disk edge before turning around, and C-SCAN to jump back to cylinder 0.
"""

UP, DOWN = +1, -1


class Scheduler:
    """Common parent class - holds the head direction and disk size."""
    name = "base"

    def reset(self, head, direction, disk_size):
        self.direction = direction
        self.disk_size = disk_size

    def select(self, pending, head, now):
        raise NotImplementedError

    # Small helpers shared by the SCAN family
    def _ahead(self, requests, head):
        """Requests that lie in the current direction of travel (including under the head)."""
        if self.direction == UP:
            return [r for r in requests if r.track >= head]
        return [r for r in requests if r.track <= head]

    @staticmethod
    def _nearest(requests, head):
        """Closest request to the head; ties broken by who arrived first."""
        return min(requests, key=lambda r: (abs(r.track - head), r.arrival_time, r.request_id))


# ---------------------------------------------------------------------------
class FCFS(Scheduler):
    """First-Come-First-Served: serve requests strictly in arrival order."""
    name = "FCFS"

    def select(self, pending, head, now):
        return min(pending, key=lambda r: (r.arrival_time, r.request_id)), []


# ---------------------------------------------------------------------------
class SSTF(Scheduler):
    """Shortest-Seek-Time-First: always go to the closest request (can starve far ones)."""
    name = "SSTF"

    def select(self, pending, head, now):
        return self._nearest(pending, head), []


# ---------------------------------------------------------------------------
class SCAN(Scheduler):
    """
    SCAN / Elevator  (THE BASELINE).
    The arm sweeps in one direction serving every request it meets.
    When nothing is left ahead it continues to the END of the disk,
    then reverses and sweeps back - exactly like a lift in a building.
    Every request is treated the same: no priorities, no fairness limits.
    """
    name = "SCAN"

    def select(self, pending, head, now):
        ahead = self._ahead(pending, head)
        if ahead:
            return self._nearest(ahead, head), []

        # Nothing ahead: go all the way to the disk edge, then reverse.
        edge = self.disk_size - 1 if self.direction == UP else 0
        self.direction = -self.direction
        # After reversing at the edge, every pending request is "ahead".
        return self._nearest(pending, edge), ([edge] if edge != head else [])


# ---------------------------------------------------------------------------
class CSCAN(Scheduler):
    """
    Circular SCAN: serve only while moving UP. At the top edge, jump back to
    cylinder 0 and start again. Gives more uniform waiting times than SCAN.
    (The jump back is counted as head movement.)
    """
    name = "C-SCAN"

    def reset(self, head, direction, disk_size):
        super().reset(head, UP, disk_size)   # C-SCAN always serves in the UP direction

    def select(self, pending, head, now):
        ahead = [r for r in pending if r.track >= head]
        if ahead:
            return self._nearest(ahead, head), []
        top = self.disk_size - 1
        via = ([top] if head != top else []) + [0]
        return self._nearest(pending, 0), via


# ---------------------------------------------------------------------------
class LOOK(Scheduler):
    """LOOK: like SCAN but turns around at the LAST request instead of the disk edge."""
    name = "LOOK"

    def select(self, pending, head, now):
        ahead = self._ahead(pending, head)
        if not ahead:
            self.direction = -self.direction
            ahead = self._ahead(pending, head)
        return self._nearest(ahead, head), []

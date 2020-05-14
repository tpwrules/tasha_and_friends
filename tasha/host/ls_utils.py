import time
import collections

from . import latch_streamer as ls

# print status in a pretty and contextual way
class StatusPrinter:
    # period: how often, in seconds, to wait before printing another status
    def __init__(self, period=0.5):
        self.period = period

        # we only keep the last five old statuses
        self.old_statuses = collections.deque(maxlen=5)
        self.last_time = 0
        self.latches_sent = 0

    def status_cb(self, msg):
        if isinstance(msg, ls.DeviceErrorMessage):
            # if the device raised an error, we print the statuses leading up to
            # it so some context is visible
            print() # avoid overwriting any status line
            for old_status in self.old_statuses:
                print(old_status)
            print(msg)
        elif not isinstance(msg, ls.StatusMessage):
            # regular old messages just get printed.
            print(msg)
        else:
            # we accumulate status message statistics to avoid printing so many
            # all the time
            now = time.monotonic()
            self.old_statuses.append(msg)
            self.latches_sent += msg.sent
            if now-self.last_time < self.period:
                return # it's not time yet

            percent_full = int(100*msg.buffer_use/msg.buffer_size)
            m = ("   Pos: {: >5d}"
                "   Buf:{: >3d}%"
                "   Sent:{: >5d} ({:3.1f}x)  ".format(
                msg.device_pos, percent_full, self.latches_sent,
                self.latches_sent/60.09/(now-self.last_time)))
            print(m, end="\r")

            self.latches_sent = 0
            self.last_time = now

# get latches and stream them. if read_latches returns None, it assumes we're
# out of latches and does the finishing sequence
def stream_loop(latch_streamer, read_latches):
    finished = False

    while latch_streamer.communicate():
        # try and get some latches. 10k is about half a second at max rates
        if not finished:
            if latch_streamer.latch_queue_len < 10000:
                latches = read_latches(10000)
                latch_streamer.add_latches(latches)
                if latches is None: # just told the latch streamer to stop
                    finished = True

        # if we're not getting latches fast enough, spin until we do
        while not finished and latch_streamer.latch_queue_len < 1000:
            latches = read_latches(10000)
            latch_streamer.add_latches(latches)
            if latches is None: # just told the latch streamer to stop
                finished = True

        time.sleep(0.01)

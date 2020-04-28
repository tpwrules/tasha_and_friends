# play back a TAS

import sys
import time

import numpy as np

from .latch_streamer import LatchStreamer

latch_file = open(sys.argv[2], "rb")
def read_latches(num_latches):
    # for legacy reasons, the latch file holds data for 8 controllers, but
    # people only use at max 4. it's also big endian, unlike everything else.
    data = latch_file.read(num_latches*16)
    if len(data) == 0:
        return np.zeros((num_latches, 5), dtype=np.uint16)
    data = np.frombuffer(data, dtype='>u2').reshape(-1, 8)
    # take out the controllers that matter and leave empty (i.e. garbage) the
    # currently unused APU frequency word
    out = np.empty((data.shape[0], 5), dtype=np.uint16)
    out[:, :4] = data[:, (0, 1, 4, 5)]
    # then return it as a flattened array
    return out

latch_streamer = LatchStreamer()
latch_streamer.add_latches(read_latches(100))
latch_streamer.connect(sys.argv[1], status_cb=print)

while True:
    while latch_streamer.latch_queue_len < 10000:
        latch_streamer.add_latches(read_latches(10000))

    latch_streamer.communicate()

    time.sleep(0.01)

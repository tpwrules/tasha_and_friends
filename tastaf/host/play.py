# play back a TAS

import sys
import struct
import itertools

import numpy as np

latch_file = open(sys.argv[2], "rb")
def read_latches(num_latches):
    # for legacy reasons, the latch file holds data for 8 controllers, but
    # people only use at max 4. it's also big endian, unlike everything else.
    data = latch_file.read(num_latches*16)
    data = np.frombuffer(data, dtype='>u2').reshape(-1, 8)
    # take out the controllers that matter and leave empty (i.e. garbage) the
    # currently unused APU frequency word
    out = np.empty((data.shape[0], 5), dtype=np.uint16)
    out[:, :4] = data[:, (0, 1, 4, 5)]
    # then return it as a flattened array
    return out.reshape(-1)

# first, we need to load the firmware to do it
from ..firmware.latch_streamer import make_firmware
from ..firmware.bootload import do_bootload

# include some latches in the firmware so that it can start running before we
# reestablish communication with it
priming_latches = read_latches(2000)
print("Priming with {} latches.".format(len(priming_latches)//5))

print("Downloading playback firmware...")
do_bootload(sys.argv[1], make_firmware(priming_latches))

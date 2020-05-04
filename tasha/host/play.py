import argparse
import time

import numpy as np

from .latch_streamer import LatchStreamer

parser = argparse.ArgumentParser(description='Play back a TAS using TASHA.')
parser.add_argument('port', type=str,
    help='Name of the serial port TASHA is attached to.')
parser.add_argument('file', type=argparse.FileType('rb'),
    help='Path to the r16m file to play back.')

parser.add_argument('-b', '--blank', type=int, default=0,
    help='Prepend blank latches to or (if negative) remove latches from the '
    'start of the TAS.')

args = parser.parse_args()

latch_file = args.file
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

if args.blank > 0:
    latch_streamer.add_latches(np.zeros((args.blank, 5), dtype=np.uint16))
elif args.blank < 0:
    to_read = -args.blank
    while to_read > 0:
        l = read_latches(to_read)
        to_read -= len(l)
    l = None

latch_streamer.add_latches(read_latches(100))
latch_streamer.connect(args.port, status_cb=print)

while True:
    while latch_streamer.latch_queue_len < 10000:
        latch_streamer.add_latches(read_latches(10000))

    latch_streamer.communicate()

    time.sleep(0.01)

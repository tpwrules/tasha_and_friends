import argparse
import time

import numpy as np

from .latch_streamer import LatchStreamer
from .ls_utils import StatusPrinter, stream_loop
from ..gateware.apu_calc import calculate_advanced

parser = argparse.ArgumentParser(description='Play back a TAS using TASHA.')
parser.add_argument('port', type=str,
    help='Name of the serial port TASHA is attached to.')
parser.add_argument('file', type=argparse.FileType('rb'),
    help='Path to the r16m file to play back.')

parser.add_argument('-b', '--blank', type=int, default=0,
    help='Prepend blank latches to or (if negative) remove latches from the '
    'start of the TAS.')
parser.add_argument('--apu_freq', type=float, default=None,
    help='Configure the initial APU frequency in MHz (before the TAS takes '
    'control, if configured). If not set, defaults to 24.607104MHz.')

args = parser.parse_args()

latch_file = args.file
def read_latches(num_latches):
    # for legacy reasons, the latch file holds data for 8 controllers, but
    # people only use at max 4. it's also big endian, unlike everything else.
    data = latch_file.read(num_latches*16)
    if len(data) == 0:
        return None # the file is over
    data = np.frombuffer(data, dtype='>u2').reshape(-1, 8)
    # take out the controllers that matter and leave empty (i.e. garbage) the
    # currently unused APU frequency word
    out = np.empty((data.shape[0], 5), dtype=np.uint16)
    out[:, :4] = data[:, (0, 1, 4, 5)]
    # then return it as a flattened array
    return out

latch_streamer = LatchStreamer()

apu_freq_basic = None
apu_freq_advanced = None
if args.apu_freq is not None:
    apu_freq_basic, apu_freq_advanced, actual = \
        calculate_advanced(args.apu_freq)

    if abs(args.apu_freq-actual) > 10e-6:
        print("WARNING: desired APU frequency is {:.6f} but actual will be "
            "{:.6f} (more than 10Hz different)".format(args.apu_freq, actual))

if args.blank > 0:
    latch_streamer.add_latches(np.zeros((args.blank, 5), dtype=np.uint16))
elif args.blank < 0:
    to_read = -args.blank
    while to_read > 0:
        l = read_latches(to_read)
        to_read -= len(l)
    l = None

# enough priming latches to tide us over even at max latch speed
num_priming_latches = 2500
print("Loading priming latches...")
while latch_streamer.latch_queue_len < num_priming_latches:
    latches = read_latches(num_priming_latches-latch_streamer.latch_queue_len)
    if latches is None: # no more latches already?
        # oh well. send the ones we have. when the stream loop asks for more it
        # will get None again and start shutting everything down
        num_priming_latches = latch_streamer.latch_queue_len
        break
    latch_streamer.add_latches(latches)

printer = StatusPrinter()
latch_streamer.connect(args.port, status_cb=printer.status_cb,
    num_priming_latches=num_priming_latches,
    apu_freq_basic=apu_freq_basic,
    apu_freq_advanced=apu_freq_advanced,
)

stream_loop(latch_streamer, read_latches)

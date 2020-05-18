import argparse
import time

import numpy as np

from .latch_streamer import LatchStreamer
from .ls_utils import StatusPrinter, stream_loop
from ..gateware.apu_calc import calculate_advanced

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description='Play back a TAS using TASHA.\n\n'
    'The intital settings of the APU clock generator can be configured using\n'
    'the \'--apu_\'-prefixed options. If the TAS is configured to control the\n'
    'clock generator, then the initial settings are in effect only until the\n'
    'first latch. Please consult \'apu_clockgen.py\' for a more thorough\n'
    'description of the clock generator settings and operation.')
parser.add_argument('port', type=str,
    help='Name of the serial port TASHA is attached to.')
parser.add_argument('file', type=argparse.FileType('rb'),
    help='Path to the r16m file to play back.')

parser.add_argument('-b', '--blank', type=int, default=0,
    help='Prepend blank latches to or (if negative) remove latches from the '
    'start of the TAS.')
parser.add_argument('-c', '--controllers', type=str, default='1,2,5,6',
    help='Comma-separated list of controllers to use from the TAS. The first '
    'entry is assigned to p1d0 (player 1 data line 0), the second p1d1, the '
    'third p2d0, and the fourth p2d1. By default, all four lines are used and '
    'are assigned controllers 1,2,5,6.')

parser.add_argument('-f', '--apu_freq', type=float, default=24.607104,
    help='Set initial frequency in MHz. If not set, defaults to 24.607104MHz.')
parser.add_argument('--apu_jitter', type=int, default=0, choices=range(8),
    metavar="N", help='Set initial jitter amount. This delays pulse skipping '
    'by a random number of clock cycles between 0 and 2**N-1. By default '
    'N = 0, and so jitter is disabled. High jitter amounts at low frequencies '
    'may unexpectedly raise the output frequency.')
parser.add_argument('--apu_alt_jitter', action="store_true",
    help='Enable alternate jitter mode, where the LFSR is advanced every pulse '
    'skip. By default, the LFSR is advanced every clock cycle.')
parser.add_argument('--apu_alt_polarity', action="store_true",
    help='Enable alternate skip polarity, where high pulses are skipped '
    '(010 -> 000). By default, low pulses are skipped (101 -> 111).')

args = parser.parse_args()

all_controllers = ["p1d0", "p1d1", "p2d0", "p2d1"]
# number of each controller in the file, corresponding to the names above
file_nums = []
for controller in args.controllers.split(","):
    try:
        file_num = int(controller)
    except ValueError:
        file_num = None
    if file_num is None or (file_num < 1 or file_num > 8):
        print("Invalid controller number '{}'. Must be 1-8.".format(controller))
        exit(1)
    file_nums.append(file_num)

if len(file_nums) < 1 or len(file_nums) > 4:
    print("Invalid number of controllers '{}'. Must be 1-4.".format(
        len(file_nums)))
    exit(1)

# subtract 1 to get the column offset
file_nums = tuple(n-1 for n in file_nums)
# remove the controllers we're not using
all_controllers = all_controllers[:len(file_nums)]

latch_file = args.file
def read_latches(num_latches):
    # for legacy reasons, the latch file holds data for 8 controllers, but
    # people only use at max 4. it's also big endian, unlike everything else.
    data = latch_file.read(num_latches*16)
    if len(data) == 0:
        return None # the file is over
    data = np.frombuffer(data, dtype='>u2').reshape(-1, 8)
    # take out the controllers we're using and convert to regular endian uint16
    return data[:, file_nums].astype(np.uint16)

latch_streamer = LatchStreamer(controllers=all_controllers)

apu_freq_basic, apu_freq_advanced, actual = calculate_advanced(
    args.apu_freq, args.apu_jitter, args.apu_alt_jitter, args.apu_alt_polarity)

if abs(args.apu_freq-actual) > 10e-6:
    print("WARNING: desired APU frequency is {:.6f} but actual will be "
        "{:.6f} (more than 10Hz different)".format(args.apu_freq, actual))

if args.blank > 0:
    latch_streamer.add_latches(
        np.zeros((args.blank, len(file_nums)), dtype=np.uint16))
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

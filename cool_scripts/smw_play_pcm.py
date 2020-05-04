# play back PCM audio through total's SMW ACE and TASHA. the ACE must already be
# running. for the record, the ACE TAS filename is "smw_stereo_pcm_v6.r16m" and
# it must be prepended with 3 blank latches to work correctly with TASHA.

# FFMPEG command line illustrated below, where F is the input file.
# ffmpeg -i F -hide_banner -v quiet -f s16le -ac 2 -ar 32000 -acodec pcm_s16le -

# pipe it like: <ffmpeg command> | python3 smw_play_pcm.py <TASHA serial port>

import sys
import time

import numpy as np

from tasha.host.latch_streamer import LatchStreamer

def bitswap(b):
    b = (b&0xF0) >> 4 | (b&0x0F) << 4
    b = (b&0xCC) >> 2 | (b&0x33) << 2
    b = (b&0xAA) >> 1 | (b&0x55) << 1
    return b

# turn 8 bytes (4 samples) of little-endian signed 16-bit PCM audio into four 16
# bit sets of buttons
def twiddle(packed_pcm):
    val = (packed_pcm[1] << 8) + (packed_pcm[0])
    #val = val ^ 0xA804

    d1 =  (((val>>6))&1)
    d1 += (((val>>4)&1)<<1)
    d1 += (((val>>2)&1)<<2)
    d1 += (((val)&1)<<3)

    d2 = ((val>>7)&1)
    d2 += (((val>>5)&1)<<1)
    d2 += (((val>>3)&1)<<2)
    d2 += (((val>>1)&1)<<3)

    d3 = (((val>>14))&1)
    d3 += ((((val>>12))&1)<<1)
    d3 += (((val>>10)&1)<<2)
    d3 += ((((val>>8))&1)<<3)

    d4 = (((val>>15))&1)
    d4 += ((((val>>13))&1)<<1)
    d4 += ((((val>>11))&1)<<2)
    d4 += (((val>>9)&1)<<3)

    val = (packed_pcm[3] << 8) + (packed_pcm[2])
    #val = val ^ 0xA804

    d5 =  (((val>>6))&1)
    d5 += (((val>>4)&1)<<1)
    d5 += (((val>>2)&1)<<2)
    d5 += (((val)&1)<<3)

    d6 = ((val>>7)&1)
    d6 += (((val>>5)&1)<<1)
    d6 += (((val>>3)&1)<<2)
    d6 += (((val>>1)&1)<<3)

    d7 = (((val>>14))&1)
    d7 += ((((val>>12))&1)<<1)
    d7 += (((val>>10)&1)<<2)
    d7 += ((((val>>8))&1)<<3)

    d8 = (((val>>15))&1)
    d8 += ((((val>>13))&1)<<1)
    d8 += ((((val>>11))&1)<<2)
    d8 += (((val>>9)&1)<<3)

    val = (packed_pcm[5] << 8) + (packed_pcm[4])
    #val = val ^ 0xA804

    d11 =  (((val>>6))&1)
    d11 += (((val>>4)&1)<<1)
    d11 += (((val>>2)&1)<<2)
    d11 += (((val)&1)<<3)

    d21 = ((val>>7)&1)
    d21 += (((val>>5)&1)<<1)
    d21 += (((val>>3)&1)<<2)
    d21 += (((val>>1)&1)<<3)

    d31 = (((val>>14))&1)
    d31 += ((((val>>12))&1)<<1)
    d31 += (((val>>10)&1)<<2)
    d31 += ((((val>>8))&1)<<3)

    d41 = (((val>>15))&1)
    d41 += ((((val>>13))&1)<<1)
    d41 += ((((val>>11))&1)<<2)
    d41 += (((val>>9)&1)<<3)

    val = (packed_pcm[7] << 8) + (packed_pcm[6])
    #val = val ^ 0xA804

    d51 =  (((val>>6))&1)
    d51 += (((val>>4)&1)<<1)
    d51 += (((val>>2)&1)<<2)
    d51 += (((val)&1)<<3)

    d61 = ((val>>7)&1)
    d61 += (((val>>5)&1)<<1)
    d61 += (((val>>3)&1)<<2)
    d61 += (((val>>1)&1)<<3)

    d71 = (((val>>14))&1)
    d71 += ((((val>>12))&1)<<1)
    d71 += (((val>>10)&1)<<2)
    d71 += ((((val>>8))&1)<<3)

    d81 = (((val>>15))&1)
    d81 += ((((val>>13))&1)<<1)
    d81 += ((((val>>11))&1)<<2)
    d81 += (((val>>9)&1)<<3)

    b0 = bitswap(d1) + (bitswap(d5)>>4)
    b1 = bitswap(d11) + (bitswap(d51)>>4)
    b2 = bitswap(d2) + (bitswap(d6)>>4)
    b3 = bitswap(d21) + (bitswap(d61)>>4)
    b4 = bitswap(d3) + (bitswap(d7)>>4)
    b5 = bitswap(d31) + (bitswap(d71)>>4)
    b6 = bitswap(d4) + (bitswap(d8)>>4)
    b7 = bitswap(d41) + (bitswap(d81)>>4)

    return [(b0<<8)+b1, (b2<<8)+b3, (b4<<8)+b5, (b6<<8)+b7]

# precompute all the bit shuffling that twiddle does above so we can emulate it
# with a fancy index
def calculate_twiddle_table():
    twiddle_table = np.empty(64, dtype=np.uint8)
    for bit in range(64):
        # set the given bit in the input data
        bits_in = np.zeros(64, dtype=np.bool)
        bits_in[bit] = True
        # pack the 64 bits into 8 bytes, then twiddle them into buttons
        twiddled = twiddle(np.packbits(bits_in))
        # convert the twiddled words back into bytes, then into their bits
        twiddled_bytes = np.asarray(twiddled, dtype=np.uint16).view(np.uint8)
        twiddled_bits = np.unpackbits(twiddled_bytes)
        # the bit that got set in the output came from the bit we set in the
        # input
        twiddle_table[int(np.nonzero(twiddled_bits)[0])] = bit

    return twiddle_table

twiddle_table = calculate_twiddle_table()

leftovers = None
def read_latches(num_latches):
    global leftovers
    pcm_data = sys.stdin.buffer.read(num_latches*8)
    # we can only process one latch (4 samples) at a time
    if leftovers is not None:
        pcm_data = leftovers + pcm_data
        leftovers = None
    if len(pcm_data) % 8 != 0:
        num_bytes = len(pcm_data)//8
        pcm_data, leftovers = pcm_data[:num_bytes], pcm_data[num_bytes:]

    # split apart PCM data into bits
    pcm_bits = np.frombuffer(pcm_data, dtype=np.uint16).reshape(-1, 4)
    pcm_bits = pcm_bits ^ 0xA804 # XOR to prepare for transmission
    pcm_bits = np.unpackbits(pcm_bits.view(np.uint8)).reshape(-1, 64)
    # twiddle them according to the table we prepared earlier
    twiddled_bits = pcm_bits[:, twiddle_table]
    # convert the bits back to buttons
    latch_data = np.packbits(twiddled_bits).view(np.uint16).reshape(-1, 4)
    # add the 5th column, which is the APU frequency control word
    out = np.empty((latch_data.shape[0], 5), dtype=np.uint16)
    out[:, :4] = latch_data

    return out

latch_streamer = LatchStreamer(
    already_latching=True,
    num_priming_latches=3000)
latch_streamer.add_latches(read_latches(3000))
latch_streamer.connect(sys.argv[1], status_cb=print)

while True:
    while latch_streamer.latch_queue_len < 10000:
        latch_streamer.add_latches(read_latches(10000))

    latch_streamer.communicate()

    time.sleep(0.01)

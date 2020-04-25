# play back a TAS

import sys
import struct
import itertools
import serial
import collections
import random

import crcmod.predefined
crc_16_kermit = crcmod.predefined.mkPredefinedCrcFun("kermit")

import numpy as np

latch_file = open(sys.argv[2], "rb")
def read_latches(num_latches):
    # for legacy reasons, the latch file holds data for 8 controllers, but
    # people only use at max 4. it's also big endian, unlike everything else.
    data = latch_file.read(num_latches*16)
    if len(data) == 0:
        return np.zeros((num_latches, 5), dtype=np.uint16).reshape(-1)
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
priming_latches = read_latches(1)
print("Priming with {} latches.".format(len(priming_latches)//5))

print("Downloading playback firmware...")
do_bootload(sys.argv[1], make_firmware(priming_latches))

# excessively prototype streamer

print("Reestablishing connection...")
port = serial.Serial(port=sys.argv[1], baudrate=2_000_000, timeout=0.01)

# wait until we get a valid status packet
while True:
    c1 = port.read(1)
    if c1 != b"\x03":
        continue
    c2 = port.read(1)
    if c2 != b"\x10":
        continue
    rest = b"\x03\x10" + port.read(8)
    if crc_16_kermit(rest) == 0:
        break

stream_pos = len(priming_latches)//5

dp = False

def port_read(c):
    d = port.read(c)
    if len(d) > 0 and dp:
        print("->", end="")
        for b in d:
            print("{:02X}".format(b), end=" ")
        print()
    return d

def port_write(d):
    c = port.write(d)
    if c > 0 and dp:
        print("<-", end="")
        for b in d[:c]:
            print("{:02X}".format(b), end=" ")
        print()
    return c

out_chunks = collections.deque()
out_curr_chunk = None
out_curr_chunk_pos = None

last_error = 0

error_codes = {
    0x00: "success",
    0x01: "invalid command",
    0x02: "bad CRC",
    0x03: "receive error/overflow",
    0x04: "receive timeout",

    0x40: "buffer underrun",
    0x41: "missed latch",
}

in_chunks = []
in_chunk_len = 0
print("Beginning transmission...")
while True:
    # try and receive a status packet
    rx_new = port_read(10)
    if len(rx_new) > 0:
        in_chunks.append(rx_new)
        in_chunk_len += len(rx_new)
    while in_chunk_len >= 10:
        in_data = b''.join(in_chunks)
        packet = in_data[:10]
        in_chunks = [in_data[10:]]
        in_chunk_len = len(in_chunks[0])

        if crc_16_kermit(packet) != 0 or packet[:2] != b'\x03\x10':
            raise Exception("bad packet {!r}".format(packet))

        p_error, p_stream_pos, p_buffer_space = \
            struct.unpack("<5H", packet)[1:4]

        # if this was an error, we need to intervene.
        if p_error > 0:
            in_error = True

            if p_error >= 0x40:
                print("FATAL ", end="")
            print("ERROR:", error_codes.get(p_error, p_error), " "*50)
            if p_error >= 0x40:
                exit(0) # nothing much we can do

            # restart transmission at the last position the device had
            if stream_pos < p_stream_pos:
                stream_pos += 65536
            latch_file.seek(-(stream_pos-p_stream_pos)*16, 1)
            stream_pos = p_stream_pos
            last_error = p_error
        elif p_error == 0:
            # the error has been handled and we've got a good status report
            last_error = 0

        # the device tells us how much it's received and we know how much we've
        # sent. the difference is the number of latches in transit.
        in_transit = (stream_pos-p_stream_pos)&0xFFFF
        # so, we have to remove that number from the amount of space left in the
        # device's buffer because they will shortly end up there and we don't
        # want to overrun it
        actual_buffer_space = p_buffer_space - in_transit
        print("  D:{:05d}<-P:{:05d} B:{:05d} T:{:05d} S:{:05d}".format(
            p_stream_pos, stream_pos, p_buffer_space,
            in_transit, actual_buffer_space), end="\r")
        # queue that many for transmission, in chunks of 100
        while actual_buffer_space > 0:
            num_to_send = min(100, actual_buffer_space)
            data = read_latches(num_to_send)
            num_sent = len(data)//5
            if num_sent == 0: continue
            data = data.tobytes('C')
            cmd = struct.pack("<4H", 0x1003,
                stream_pos, num_sent, 0)
            out_chunks.append(cmd)
            out_chunks.append(
                crc_16_kermit(cmd).to_bytes(2, byteorder="little"))
            if random.random() > -1:
                out_chunks.append(data)
                out_chunks.append(
                    crc_16_kermit(data).to_bytes(2, byteorder="little"))
            else:
                c = crc_16_kermit(data).to_bytes(2, byteorder="little")
                if random.random() > 0.5:
                    data = data[:-2]
                out_chunks.append(data)
                out_chunks.append(c)

            actual_buffer_space -= num_sent
            stream_pos = (stream_pos + num_sent) & 0xFFFF

    # send out the data we do have
    while True:
        if out_curr_chunk is None:
            if len(out_chunks) == 0:
                break
            out_curr_chunk = out_chunks.popleft()
            out_curr_chunk_pos = 0

        sent = port_write(out_curr_chunk[out_curr_chunk_pos:])
        to_send = len(out_curr_chunk) - out_curr_chunk_pos
        if sent != to_send:
            out_curr_chunk_pos += sent
            break
        else:
            out_curr_chunk = None

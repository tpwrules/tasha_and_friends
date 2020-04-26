# stream latches out to the console through TASHA.

# Latch format is an (n, 5) uint16 numpy ndarray, where n is the number of
# latches in the array.
#   Column 0: player 1 data 0
#   Column 1: player 1 data 1
#   Column 2: player 2 data 0
#   Column 3: player 2 data 1
#   Column 4: APU frequency control word

import struct
import random
import collections
import itertools

import numpy as np
import serial
import crcmod.predefined
crc_16_kermit = crcmod.predefined.mkPredefinedCrcFun("kermit")

from ..firmware.latch_streamer import make_firmware, LATCH_BUF_SIZE
from ..firmware import bootload

# todo: gross
error_codes = {
    0x00: "success",
    0x01: "invalid command",
    0x02: "bad CRC",
    0x03: "receive error/overflow",
    0x04: "receive timeout",

    0x40: "buffer underrun",
    0x41: "missed latch",
}

class LatchStreamer:
    def __init__(self):
        self.connected = False
        self.latch_queue = collections.deque()
        # the queue is composed of arrays with many latches in each. keep track
        # of how many latches total are in there.
        self.latch_queue_len = 0

        # everything else will be initialized upon connection

    # Add some latches to the stream queue.
    def add_latches(self, latches):
        if not isinstance(latches, np.ndarray):
            raise TypeError("'latches' must be ndarray, not {!r}".format(
                type(latches)))
        if len(latches.shape) != 2 or latches.shape[1] != 5:
            raise TypeError("'latches' must be shape (n, 5), not {!r}".format(
                latches.shape))
        if latches.dtype != np.uint16:
            raise TypeError("'latches' must be uint16, not {!r}".format(
                latches.dtype))

        if len(latches) == 0: # no point in storing no latches
            return self.latch_queue_len

        # copy the array so we don't have to worry that the caller will do
        # something weird to it. we need to send the data in C order, so we make
        # sure the copy is such.
        self.latch_queue.append(np.copy(latches, order="C"))
        self.latch_queue_len += len(latches)

    # Remove all the latches from the stream queue. Not guaranteed to remove
    # everything unless disconnected.
    def clear_latch_queue(self):
        self.latch_queue = collections.deque()
        self.latch_queue_len = 0

    # Connect to TASHA. status_cb is basically just print for now.
    def connect(self, port, status_cb=print):
        if self.connected is True:
            raise ValueError("already connected")

        if self.latch_queue_len == 0:
            raise ValueError("add some latches to prime the system before "
                "connecting")

        status_cb("Building application...")

        # get the first entry in the queue
        first = self.latch_queue.popleft()
        # pull some latches off it and save the remainder
        priming_latches, first = first[:100], first[100:]
        # if there are any left, stick them back where we got them
        self.latch_queue.appendleft(first)
        self.latch_queue_len -= len(priming_latches)

        firmware = make_firmware(priming_latches.reshape(-1))

        status_cb("Connecting to TASHA...")
        bootloader = bootload.Bootloader()

        # assume the board is responsive and will get back to us quickly
        try:
            bootloader.connect(port, timeout=1)
        except bootload.Timeout: # it isn't
            # ask the user to try and reset the board, then wait for however
            # long it takes for the bootloder to start
            status_cb("    (no response, please reset TASHA)")
            bootloader.connect(port, timeout=None)

        status_cb("Reading information...")
        info_words = bootloader.read_memory(bootload.ROM_INFO_WORDS, 8)
        if info_words[-1] != bootload.BOOTLOADER_VERSION:
            raise bootload.BootloadError("wrong bootloader version {} "
                "(expected {})".format(info_words[-1],
                    bootload.BOOTLOADER_VERSION))

        status_cb("Downloading and verifying application...")
        firmware = tuple(firmware)
        bootloader.write_memory(0, firmware)
        read_firmware = bootloader.read_memory(0, len(firmware))
        if firmware != read_firmware:
            raise bootload.BootloadError("verification failed")

        status_cb("Starting application...")
        bootloader.start_execution(0)

        status_cb("Connecting to application...")
        self.port = serial.Serial(port=port, baudrate=2_000_000, timeout=0.001)

        # wait until we get a valid status packet
        while True:
            c1 = self.port.read(1)
            if c1 != b"\x03":
                continue
            c2 = self.port.read(1)
            if c2 != b"\x10":
                continue
            rest = b"\x03\x10" + self.port.read(8)
            if crc_16_kermit(rest) == 0:
                break

        status_cb("Success!")

        # initialize input and output buffers
        self.out_chunks = collections.deque()
        self.out_curr_chunk = None
        self.out_curr_chunk_pos = None

        self.in_chunks = []
        self.in_chunk_len = 0

        # initialize stream
        self.stream_pos = len(priming_latches)

        self.status_cb = status_cb
        self.connected = True


    # Call repeatedly to perform communication. Reads messages from TASHA and
    # sends latches back out.
    def communicate(self):
        if self.connected is False:
            raise ValueError("you must connect before communicating")

        status_cb = self.status_cb

        # receive any status packet pieces
        rx_new = self.port.read(65536)
        if len(rx_new) > 0:
            self.in_chunks.append(rx_new)
            self.in_chunk_len += len(rx_new)

        # parse status packets out of them
        while self.in_chunk_len >= 10:
            # pull out one packet
            # todo: be less gross
            in_data = b''.join(self.in_chunks)
            packet = in_data[:10]
            self.in_chunks = [in_data[10:]]
            self.in_chunk_len = len(self.in_chunks[0])

            if crc_16_kermit(packet) != 0 or packet[:2] != b'\x03\x10':
                raise Exception("bad packet {!r}".format(packet))

            # get fields of interest; namely the current error, the device
            # stream position, and how much space is in its buffer.
            p_error, p_stream_pos, p_buffer_space = \
                struct.unpack("<3H", packet[2:8])

            # if there is an error, we need to intervene.
            if p_error != 0:
                is_fatal = p_error >= 0x40
                if is_fatal:
                    msg = "FATAL ERROR: "
                else:
                    msg = "ERROR: "
                msg += error_codes.get(p_error, str(p_error))

                status_cb(msg)

                # we can't do anything for fatal errors
                if is_fatal:
                    raise Exception("fatal error :(")

                # but if it's not, we will restart transmission at the last
                # position the device got, so it can pick the stream back up
                # before a part got lost due to an error.
                raise Exception("actually do that")

            # the device us tells us how many latches it's received and we know
            # how many we've sent. the difference is the number in transit.
            in_transit = (self.stream_pos - p_stream_pos) & 0xFFFF
            # we have to remove that number from the amount of space left in the
            # device's buffer because those latches will shortly end up there
            # and we don't want to overflow it
            actual_buffer_space = p_buffer_space - in_transit
            if actual_buffer_space < 20:
                # don't bother sending so few latches, or even printing the
                # status message.
                continue
            msg = "  D:{:05d}<-P:{:05d} B:{:05d} T:{:05d} S:{:05d}".format(
                p_stream_pos, self.stream_pos, p_buffer_space,
                in_transit, actual_buffer_space)
            status_cb(msg)

            # queue that many for transmission
            while actual_buffer_space > 0:
                # we'd like to send at least 20 latches to avoid too much packet
                # overhead, but not more than 200 to avoid having to resend a
                # lot of latches if there is an error. but of course, we can't
                # send so many that we overflow the buffer.
                send_max = min(200, actual_buffer_space)

                latch_data = []
                num_sent = 0
                while num_sent < min(20, send_max):
                    try:
                        more_latches = self.latch_queue.popleft()
                    except IndexError:
                        break # queue is empty
                    self.latch_queue_len -= len(more_latches)

                    # would this put us over the max?
                    if num_sent + len(more_latches) > send_max:
                        # yes, split it up
                        remaining = send_max-num_sent
                        more_latches, leftovers = \
                            more_latches[:remaining], more_latches[remaining:]
                        # and store the extra for next time
                        self.latch_queue.appendleft(leftovers)
                        self.latch_queue_len += len(leftovers)

                    # convert to raw bytes for transmission
                    latch_data.append(more_latches.tobytes('C'))
                    num_sent += len(more_latches)

                if num_sent == 0: break # queue is empty

                # send the latch transmission command
                cmd = struct.pack("<4H", 0x1003, self.stream_pos, num_sent, 0)
                self.out_chunks.append(cmd)
                self.out_chunks.append(
                    crc_16_kermit(cmd).to_bytes(2, byteorder="little"))

                # merge all the data together into one chunk for transmission
                latch_data = b''.join(latch_data)
                # and send it too
                self.out_chunks.append(latch_data)
                self.out_chunks.append(
                    crc_16_kermit(latch_data).to_bytes(2, byteorder="little"))

                # we've filled up the buffer some
                actual_buffer_space -= num_sent
                # and advanced the stream position
                self.stream_pos = (self.stream_pos + num_sent) & 0xFFFF

        # send out the data we prepared earlier
        while True:
            # get a new chunk
            if self.out_curr_chunk is None:
                if len(self.out_chunks) == 0:
                    break
                self.out_curr_chunk = self.out_chunks.popleft()
                self.out_curr_chunk_pos = 0

            # calculate how much data is remaining in it
            to_send = len(self.out_curr_chunk) - self.out_curr_chunk_pos
            # send out all the data
            sent = self.port.write(
                self.out_curr_chunk[self.out_curr_chunk_pos:])
            if sent != to_send: # did we send all of it?
                # nope, remember what we did send
                self.out_curr_chunk_pos += sent
                # and try to send the rest later
                break
            else:
                # yup, we are done with this chunk
                self.out_curr_chunk = None


    def disconnect(self):
        if self.connected is False:
            return

        # close and delete buffers to avoid hanging on to junk
        self.port.close()
        del self.port

        del self.out_chunks
        del self.out_curr_chunk
        del self.in_chunks
        del self.status_cb

        self.connected = False

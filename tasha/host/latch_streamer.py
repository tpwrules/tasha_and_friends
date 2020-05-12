# stream latches out to the console through TASHA.

# Latch format is an (n, 5) uint16 numpy ndarray, where n is the number of
# latches in the array.
#   Column 0: player 1 data 0
#   Column 1: player 1 data 1
#   Column 2: player 2 data 0
#   Column 3: player 2 data 1
#   Column 4: APU frequency control word

# LATCH STREAMER SETTINGS (parameters to connect())

# num_priming_latches: Number of latches to download with the firmware. These
#   latches must tide the firmware over until communication is reestablished.
#   This must be at least one, and not greater than the latch buffer size. If
#   None, the value will be the latch buffer size. At least this many latches
#   must be in the latch queue before connecting, as this many will be
#   downloaded with the firmware.

# apu_freq_basic and apu_freq_advanced: Configure the initial values for the APU
#   basic and advanced frequency setting registers. If None, the defaults
#   compiled into the gateware are used. Consult calculate_advanced in
#   gateware/apu_calc.py for information on how to choose the value.

import struct
import random
import collections
import itertools

import numpy as np
import serial
import crcmod.predefined
crc_16_kermit = crcmod.predefined.mkPredefinedCrcFun("kermit")

from ..firmware.latch_streamer import make_firmware, LATCH_BUF_SIZE
from . import bootload

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
    def connect(self, port, status_cb=print,
            num_priming_latches=None,
            apu_freq_basic=None,
            apu_freq_advanced=None):
        if self.connected is True:
            raise ValueError("already connected")

        if num_priming_latches is None:
            num_priming_latches = LATCH_BUF_SIZE

        # we can't pre-fill the buffer with more latches than fit in it
        num_priming_latches = min(num_priming_latches, LATCH_BUF_SIZE)

        if self.latch_queue_len < num_priming_latches:
            raise ValueError("{} priming latches requested but only {} "
                "available in the queue".format(
                    num_priming_latches, self.latch_queue_len))

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

        bootloader.identify()

        status_cb("Building firmware...")

        # get the priming latch data and convert it back to words. kinda
        # inefficient but we only do it once.
        priming_latches = struct.unpack(
            "<{}H".format(num_priming_latches*5),
            self._get_latch_data(num_priming_latches, num_priming_latches))

        firmware = make_firmware(priming_latches,
            apu_freq_basic=apu_freq_basic,
            apu_freq_advanced=apu_freq_advanced)

        status_cb("Downloading and starting firmware...")
        firmware = tuple(firmware)
        bootloader.write_memory(0, firmware)
        read_firmware = bootloader.read_memory(0, len(firmware))
        if firmware != read_firmware:
            raise bootload.BootloadError("verification failed")

        bootloader.start_execution(0)
        self.port = serial.Serial(port=port, baudrate=2_000_000, timeout=0.001)

        # initialize input and output buffers
        self.out_chunks = collections.deque()
        self.out_curr_chunk = None
        self.out_curr_chunk_pos = None

        self.in_chunks = bytearray()

        # initialize stream
        self.stream_pos = num_priming_latches
        # keep track of the latches we've sent so we can resend them if there is
        # an error
        self.resend_buf = collections.deque()
        self.resend_buf_len = 0

        self.status_cb = status_cb
        self.connected = True
        self.got_first_packet = False

    # get some latches from the latch queue and return the converted to bytes.
    # may return less than at_least if not enough latches are available. if
    # at_most is None, there is no upper bound on the number of latches
    # returned.
    def _get_latch_data(self, at_least, at_most=None):
        latch_data = []
        num_got = 0
        while num_got < at_least and len(self.latch_queue) > 0:
            more_latches = self.latch_queue.popleft()
            self.latch_queue_len -= len(more_latches)

            # would this put us over the max?
            if at_most is not None and num_got + len(more_latches) > at_most:
                # yes, split it up
                remaining = at_most-num_got
                more_latches, leftovers = \
                    more_latches[:remaining], more_latches[remaining:]
                # and store the extra for next time
                self.latch_queue.appendleft(leftovers)
                self.latch_queue_len += len(leftovers)

            # convert to raw bytes for transmission
            latch_data.append(more_latches.tobytes('C'))
            num_got += len(more_latches)

        return b''.join(latch_data)

    # find, parse, and return the latest packet from in_chunks
    def _parse_latest_packet(self):
        packet = None
        while True:
            pos = self.in_chunks.find(b'\x5A\x7A')
            if pos == -1: # not found
                # we are done if there's no data left
                if len(self.in_chunks) == 0:
                    break
                # if the last byte could be the start of the packet, save it
                if self.in_chunks[-1] == b'\x5A':
                    self.in_chunks = self.in_chunks[-1:]
                else:
                    self.in_chunks.clear()
                break

            packet_data = self.in_chunks[pos:pos+12]
            if len(packet_data) < 12: # packet is not complete
                # save what we've got for later
                self.in_chunks = self.in_chunks[pos:]
                break

            # is the packet valid?
            if crc_16_kermit(packet_data[2:]) != 0:
                # nope. throw away the header. maybe a packet starts after it.
                self.status_cb("WARNING: invalid packet received: {!r}".format(
                    packet_data))
                self.in_chunks = self.in_chunks[pos+2:]
            else:
                # it is. parse the useful bits from it
                packet = struct.unpack("<3H", packet_data[4:10])
                # and remove it from the stream
                self.in_chunks = self.in_chunks[pos+12:]

        return packet

    # Call repeatedly to perform communication. Reads messages from TASHA and
    # sends latches back out.
    def communicate(self):
        if self.connected is False:
            raise ValueError("you must connect before communicating")

        status_cb = self.status_cb

        # receive any status packet pieces, then parse out any status packets
        rx_new = self.port.read(65536)
        packet = None
        if len(rx_new) > 0:
            self.in_chunks.extend(rx_new)
            packet = self._parse_latest_packet()

        # if we got a packet, parse it
        if packet is not None:
            if self.got_first_packet is False:
                print("Initialization complete! Beginning latch transfer...")
                self.got_first_packet = True

            p_error, p_stream_pos, p_buffer_space = packet

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
                # position the device got so it can pick the stream back up.

                # how many latches do we need to resend to get the device back
                # to the position we are at?
                num_to_resend = (self.stream_pos - p_stream_pos) & 0xFFFF
                # pull that many out of the resend buffer
                to_resend = []
                self.resend_buf_len -= num_to_resend
                # we will be sending that many back out
                self.latch_queue_len += num_to_resend
                # because the resend buffer contains whole packets and the
                # device can only lose whole packets, we can just move packets
                while num_to_resend > 0:
                    packet = self.resend_buf.pop() # pop latest transmission
                    # turn it from bytes back into a numpy array
                    packet = np.frombuffer(packet,
                        dtype=np.uint16).reshape(-1, 5)
                    to_resend.append(packet)
                    num_to_resend -= len(packet)
                # put what we pulled out back into the send queue. to_resend is
                # from most recently to least recently transmitted so the
                # packets end up least recently to most recently transmitted.
                self.latch_queue.extendleft(to_resend)
                # finally set the correct stream position
                self.stream_pos = p_stream_pos

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
                pass
            else:
                msg = "  D:{:05d}<-P:{:05d} B:{:05d} T:{:05d} S:{:05d}".format(
                    p_stream_pos, self.stream_pos, p_buffer_space,
                    in_transit, actual_buffer_space)
                status_cb(msg)

            # queue that many for transmission
            while actual_buffer_space >= 20:
                # we'd like to send at least 20 latches to avoid too much packet
                # overhead, but not more than 200 to avoid having to resend a
                # lot of latches if there is an error. but of course, we can't
                # send so many that we overflow the buffer.
                latch_data = self._get_latch_data(
                    min(20, actual_buffer_space), min(200, actual_buffer_space))
                num_sent = len(latch_data)//10

                if num_sent == 0: break # queue was empty.

                # send the latch transmission command
                cmd = struct.pack("<5H",
                    0x7A5A, 0x1003, self.stream_pos, num_sent, 0)
                self.out_chunks.append(cmd)
                # don't CRC the header
                self.out_chunks.append(
                    crc_16_kermit(cmd[2:]).to_bytes(2, byteorder="little"))

                # send all the data along too
                self.out_chunks.append(latch_data)
                self.out_chunks.append(
                    crc_16_kermit(latch_data).to_bytes(2, byteorder="little"))

                # we've filled up the buffer some
                actual_buffer_space -= num_sent
                # and advanced the stream position
                self.stream_pos = (self.stream_pos + num_sent) & 0xFFFF

                # remember what data we sent so we can resend it if necessary
                self.resend_buf.append(latch_data)
                self.resend_buf_len += num_sent

                # clear out old sent data. we never have in transit more latches
                # than can be stored in the device buffer, so that is the
                # maximum number that we can fail to send and need to resend.
                while True:
                    # how many latches would be left if we removed the oldest?
                    oldest_len = len(self.resend_buf[0])//10
                    remaining = self.resend_buf_len - oldest_len
                    # is that more than we could possibly need to resend?
                    if remaining <= LATCH_BUF_SIZE:
                        break # nope, don't do anything
                    # yup, so remove it
                    self.resend_buf.popleft()
                    self.resend_buf_len -= oldest_len


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
        del self.resend_buf
        del self.status_cb

        self.connected = False

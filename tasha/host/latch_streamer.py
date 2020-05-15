# stream latches out to the console through TASHA.

# Latch format is an (n, C) uint16 numpy ndarray, where n is the number of
# latches in the array and C is the number of controllers. The controller order
# is set by the controllers list passed to the LatchStreamer constructor. The
# list is a list of strings (described below) that name each controller. If
# controllers[3] == "p2d0", then latches[:, 3] is expected to contain the
# buttons for player 2 controller on data line 0. If there are duplicate
# controllers, then the data with the greatest index is used. This does waste
# bandwidth and memory on the unused data.

# CONTROLLER NAMES
#   "p1d0": player 1, data line 0 (controller pin 4)
#   "p1d1": player 1, data line 1 (controller pin 5)
#   "p2d0": player 2, data line 0 (controller pin 4)
#   "p2d1": player 2, data line 1 (controller pin 5)
#   "apu_freq_basic": basic APU frequency adjustment. see snes.py (reg 2)
#   "apu_freq_advanced": advanced APU frequency adjustment. see snes.py (reg 3)

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
import enum

import numpy as np
import serial
import crcmod.predefined
crc_16_kermit = crcmod.predefined.mkPredefinedCrcFun("kermit")

from ..firmware.latch_streamer import make_firmware, calc_buf_size, ErrorCode
from . import bootload

# status_cb is called with Messages of the appropriate subclass
class Message:
    pass

class ConnectionMessage(Message, enum.Enum):
    CONNECTING = 1
    NOT_RESPONDING = 2
    BUILDING = 3
    DOWNLOADING = 4
    CONNECTED = 5
    TRANSFER_DONE = 6
    BUFFER_DONE = 7

    def __str__(self):
        if self == ConnectionMessage.CONNECTING:
            return "Connecting to TASHA..."
        elif self == ConnectionMessage.NOT_RESPONDING:
            return "    (no response, please reset TASHA)"
        elif self == ConnectionMessage.BUILDING:
            return "Building firmware..."
        elif self == ConnectionMessage.DOWNLOADING:
            return "Downloading and starting firmware..."
        elif self == ConnectionMessage.CONNECTED:
            return "Initialization complete! Beginning latch transfer..."
        elif self == ConnectionMessage.TRANSFER_DONE:
            return "Transfer complete! Waiting for device buffer to empty..."
        elif self == ConnectionMessage.BUFFER_DONE:
            return "All latches successfully latched! Thanks for playing!"
        else:
            raise Exception("unknown identity {}".format(self))

class DeviceErrorMessage(Message): # messages returned from the device
    def __init__(self, code):
        if not isinstance(code, ErrorCode):
            raise TypeError("must be an ErrorCode")
        self.code = code
        self.is_fatal = code >= ErrorCode.FATAL_ERROR_START

    def __str__(self):
        if self.is_fatal:
            m = "FATAL ERROR: "
        else:
            m = "COMM ERROR: "

        if self.code == ErrorCode.NONE:
            return m + "success"
        elif self.code == ErrorCode.INVALID_COMMAND:
            return m + "invalid command"
        elif self.code == ErrorCode.BAD_CRC:
            return m + "bad CRC"
        elif self.code == ErrorCode.RX_ERROR:
            return m + "receive error/overflow"
        elif self.code == ErrorCode.RX_TIMEOUT:
            return m + "receive timeout"
        elif self.code == ErrorCode.BAD_STREAM_POS:
            return m + "incorrect stream position"
        elif self.code == ErrorCode.BUFFER_UNDERRUN:
            return m + "buffer underrun"
        elif self.code == ErrorCode.MISSED_LATCH:
            return m + "missed latch"

class InvalidPacketMessage(Message):
    def __init__(self, packet):
        self.packet = packet

    def __str__(self):
        return "WARNING: invalid packet received: {!r}".format(self.packet)

# sent every processed status packet
class StatusMessage(Message):
    # buffer_use: how much buffer on the device is used in latches
    # buffer_size: total device buffer size in latches
    # device_pos: stream position the device reported, mod 65536
    # pc_pos: stream position we (on the PC) are at, mod 65536
    # sent: number of latches sent in response
    # in_transit: number of latches in transit (sent last time but not arrived)
    def __init__(self, buffer_use, buffer_size,
            device_pos, pc_pos, sent, in_transit):
        self.buffer_use = buffer_use
        self.buffer_size = buffer_size
        self.device_pos = device_pos
        self.pc_pos = pc_pos
        self.sent = sent
        self.in_transit = in_transit

    def __str__(self):
        return "D:{:05d}<-P:{:05d} B:{:05d} T:{:05d} S:{:05d}".format(
            self.device_pos, self.pc_pos, self.buffer_size-self.buffer_use,
            self.in_transit, self.sent)

# how the communication is proceeding
class ConnectionState(enum.Enum):
    # ... no connection
    DISCONNECTED = 0
    # connect()ed but we haven't got the status packet back
    INITIALIZING = 1
    # connected and everything is going well
    TRANSFERRING = 2
    # we're finishing up by emptying the host latch queue
    EMPTYING_HOST = 3
    # we're finishing up by waiting for the device to empty its buffer
    EMPTYING_DEVICE = 4

class LatchStreamer:
    def __init__(self, controllers):
        self.controllers = controllers
        self.num_controllers = len(controllers)
        self.device_buf_size = calc_buf_size(self.num_controllers)

        self.connected = False
        self.latch_queue = collections.deque()
        # the queue is composed of arrays with many latches in each. keep track
        # of how many latches total are in there.
        self.latch_queue_len = 0
        self.conn_state = ConnectionState.DISCONNECTED

        # everything else will be initialized upon connection

    # Add some latches to the stream queue. If latches is None, the latches are
    # assumed to be finished and the streamer transitions to waiting for the
    # buffers to empty. If it's not None, then normal operation resumes.
    def add_latches(self, latches):
        if latches is None:
            if self.conn_state in (ConnectionState.INITIALIZING,
                    ConnectionState.TRANSFERRING):
                self.conn_state = ConnectionState.EMPTYING_HOST
            return
        elif self.conn_state != ConnectionState.TRANSFERRING:
            if self.conn_state in (ConnectionState.EMPTYING_HOST,
                    ConnectionState.EMPTYING_DEVICE):
                self.conn_state = ConnectionState.TRANSFERRING

        if not isinstance(latches, np.ndarray):
            raise TypeError("'latches' must be ndarray, not {!r}".format(
                type(latches)))
        if len(latches.shape) != 2 or latches.shape[1] != self.num_controllers:
            raise TypeError("'latches' must be shape (n, {}), not {!r}".format(
                self.num_controllers, latches.shape))
        if latches.dtype != np.uint16:
            raise TypeError("'latches' must be uint16, not {!r}".format(
                latches.dtype))

        if len(latches) == 0: # no point in storing no latches
            return

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
        if self.conn_state != ConnectionState.DISCONNECTED:
            raise ValueError("already connected")

        if num_priming_latches is None:
            num_priming_latches = self.device_buf_size

        # we can't pre-fill the buffer with more latches than fit in it
        num_priming_latches = min(num_priming_latches, self.device_buf_size)

        if self.latch_queue_len < num_priming_latches:
            raise ValueError("{} priming latches requested but only {} "
                "available in the queue".format(
                    num_priming_latches, self.latch_queue_len))

        status_cb(ConnectionMessage.CONNECTING)
        bootloader = bootload.Bootloader()

        # assume the board is responsive and will get back to us quickly
        try:
            bootloader.connect(port, timeout=1)
            connected_quickly = True
        except bootload.Timeout: # it isn't
            connected_quickly = False

        if not connected_quickly:
            # ask the user to try and reset the board, then wait for however
            # long it takes for the bootloder to start
            status_cb(ConnectionMessage.NOT_RESPONDING)
            bootloader.connect(port, timeout=None)

        bootloader.identify()

        status_cb(ConnectionMessage.BUILDING)

        # get the priming latch data and convert it back to words. kinda
        # inefficient but we only do it once.
        priming_latches = struct.unpack(
            "<{}H".format(num_priming_latches*self.num_controllers),
            self._get_latch_data(num_priming_latches, num_priming_latches))

        firmware = make_firmware(self.controllers, priming_latches,
            apu_freq_basic=apu_freq_basic,
            apu_freq_advanced=apu_freq_advanced)

        status_cb(ConnectionMessage.DOWNLOADING)
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
        self.conn_state = ConnectionState.INITIALIZING

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
                self.status_cb(InvalidPacketMessage(packet_data))
                self.in_chunks = self.in_chunks[pos+2:]
            else:
                # it is. parse the useful bits from it
                packet = struct.unpack("<3H", packet_data[4:10])
                # and remove it from the stream
                self.in_chunks = self.in_chunks[pos+12:]

        return packet

    # Call repeatedly to perform communication. Reads messages from TASHA and
    # sends latches back out. Returns True if still connected and False to say
    # that the connection has terminated.
    def communicate(self):
        if self.conn_state == ConnectionState.DISCONNECTED:
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
            if self.conn_state == ConnectionState.INITIALIZING:
                # let the user know the device is alive
                status_cb(ConnectionMessage.CONNECTED)
                self.conn_state = ConnectionState.TRANSFERRING

            p_error, p_stream_pos, p_buffer_space = packet

            if self.conn_state == ConnectionState.EMPTYING_HOST:
                # do we have anything more to send to the device? did it get
                # everything we sent?
                stuff_in_transit = self.stream_pos != p_stream_pos
                if len(self.latch_queue) == 0 and not stuff_in_transit:
                    # yup, we are done sending. now we wait for the device's
                    # buffer to be emptied.
                    self.conn_state = ConnectionState.EMPTYING_DEVICE
                    status_cb(ConnectionMessage.TRANSFER_DONE)

            # if there is an error, we need to intervene.
            if p_error != 0:
                error = ErrorCode(p_error)
                if error == ErrorCode.BUFFER_UNDERRUN and \
                        self.conn_state == ConnectionState.EMPTYING_DEVICE:
                    # if we're waiting for the device buffer to empty, it's just
                    # happened and we are done with our job
                    status_cb(ConnectionMessage.BUFFER_DONE)
                    self.disconnect()
                    return False

                msg = DeviceErrorMessage(error)
                status_cb(msg)

                # we can't do anything for fatal errors except disconnect
                if msg.is_fatal:
                    self.disconnect()
                    return False

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
                        dtype=np.uint16).reshape(-1, self.num_controllers)
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

            # queue that many for transmission. we don't send less than 20
            # because it's kind of a waste of time.
            actual_sent = 0
            # filling the device's buffer with latches is counterproductive to
            # emptying it
            if self.conn_state == ConnectionState.EMPTYING_DEVICE:
                actual_buffer_space = 0 # stop anything from being sent
            while actual_buffer_space >= 20:
                # we'd like to send at least 20 latches to avoid too much packet
                # overhead, but not more than 200 to avoid having to resend a
                # lot of latches if there is an error. but of course, we can't
                # send so many that we overflow the buffer.
                latch_data = self._get_latch_data(
                    min(20, actual_buffer_space), min(200, actual_buffer_space))
                num_sent = len(latch_data)//(self.num_controllers*2)
                actual_sent += num_sent

                if num_sent == 0: break # queue was empty

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
                    oldest_len = len(self.resend_buf[0])
                    oldest_len //= (self.num_controllers*2)
                    remaining = self.resend_buf_len - oldest_len
                    # is that more than we could possibly need to resend?
                    if remaining <= self.device_buf_size:
                        break # nope, don't do anything
                    # yup, so remove it
                    self.resend_buf.popleft()
                    self.resend_buf_len -= oldest_len

            status_cb(StatusMessage(self.device_buf_size-p_buffer_space,
                self.device_buf_size, p_stream_pos, self.stream_pos,
                actual_sent, in_transit))

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

        return True # everything's still going good

    def disconnect(self):
        if self.conn_state == ConnectionState.DISCONNECTED:
            return

        # close and delete buffers to avoid hanging on to junk
        self.port.close()
        del self.port

        del self.out_chunks
        del self.out_curr_chunk
        del self.in_chunks
        del self.resend_buf
        del self.status_cb

        self.conn_state = ConnectionState.DISCONNECTED

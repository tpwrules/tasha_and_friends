# bootload a system running the bootloader firmware

import serial
import time
import struct

import crcmod.predefined
crc_16_kermit = crcmod.predefined.mkPredefinedCrcFun("kermit")

from .bootloader_fw import ROM_INFO_WORDS, BOOTLOADER_VERSION

class BootloadError(Exception): pass

class BadCRC(BootloadError):
    def __init__(self, received):
        self.received = received

    def __repr__(self):
        return "BadCRC(received=0x{:4X})".format(self.received)

    def __str__(self):
        return "Bad CRC: expected 0 but received 0x{:04X}".format(self.received)

class Timeout(BootloadError): pass

class Bootloader:
    def __init__(self):
        # we don't have a port until we are connected to the target
        self.port = None

    def _ser_read(self, length):
        read = b""
        while length > 0:
            new = self.port.read(length)
            if len(new) == 0:
                raise Timeout("read timeout")
            read += new
            length -= len(new)
        return read

    def _ser_write(self, data):
        sent_len = 0
        while sent_len != len(data):
            sent_len += self.port.write(data[sent_len:])

    def _send_command(self, command, param1, param2):
        if self.port is None:
            raise BootloadError("not connected to target")

        # command is always length 2
        cmd_words = [(command << 8) + 2, param1, param2]
        cmd_bytes = struct.pack("<{}H".format(len(cmd_words)), *cmd_words)

        # reset the buffers to get rid of any junk from previous (perhaps
        # failed) commands
        self.port.reset_input_buffer()
        self.port.reset_output_buffer()

        self._ser_write(cmd_bytes)
        self._ser_write(
            crc_16_kermit(cmd_bytes).to_bytes(2, byteorder="little"))

    def _check_response(self):
        if self.port is None:
            raise BootloadError("not connected to target")

        resp_bytes = self._ser_read(6)
        # the last bytes of the response are the response's CRC. if we CRC those
        # too, then we will get a CRC of 0 if everything is correct.
        crc = crc_16_kermit(resp_bytes)
        if crc != 0:
            raise BadCRC(crc)

        resp_words = struct.unpack("<3H", resp_bytes)
        if resp_words[0] != 0x0101:
            raise BootloadError("unexpected response word 0x{:04X}".format(
                resp_words[0]))

        if resp_words[1] == 3: # success
            return

        if resp_words[1] == 2:
            raise Timeout("target said 'RX error/timeout'")
        problems = {0: "unknown/invalid command", 1: "bad CRC"}
        raise BootloadError("target said '{}'".format(
            problems.get(resp_words[1], resp_words[1])))

    # connect to the target on serial port "port". give up after (about)
    # "timeout" seconds. return if connected or throw exception if failure
    def connect(self, port, timeout=None):
        # create a serial port to connect to the target. we set a 200ms timeout,
        # slightly over the 150ms timeout in the firmware, to make sure we
        # receive timeout errors.

        port = serial.Serial(port=port, baudrate=2_000_000, timeout=0.2)
        self.port = port

        try:
            if timeout is not None:
                timed_out = time.monotonic()+timeout
            while timeout is None or (time.monotonic() < timed_out):
                # say hello
                self._send_command(1, 0, 0)
                try:
                    self._check_response()
                except Timeout as e:
                    # ignore timeouts and try to do it again, hopefully when
                    # the target has timed out and everything is reset.
                    continue
                # if the response was a success, we are done
                return
            else: # loop condition failed, i.e. we timed out
                raise Timeout("connection timeout")
        except:
            self.port = None # we did not actually connect
            raise

    # read "length" words from the target starting at "addr"
    def read_memory(self, addr, length):
        # send the read command first
        self._send_command(4, addr, length)
        # then make sure it was accepted
        self._check_response()

        # now read back all the data (and CRC)
        resp_bytes = self._ser_read(2*(length+1))
        # validate the post-data response
        self._check_response()

        # validate the data CRC. as before, if we CRC the CRC, we expect CRC = 0
        crc = crc_16_kermit(resp_bytes)
        if crc != 0:
            raise BadCRC(crc)

        resp_words = struct.unpack("<{}H".format(length), resp_bytes[:-2])
        return resp_words

    # write the "data" words to the target starting at "addr"
    def write_memory(self, addr, data):
        # send the write command first
        self._send_command(2, addr, len(data))
        # theoretically we should make sure it was accepted here, but then we
        # would have to pay the 16ms latency penalty. so, we don't! and just get
        # on with sending the data.
        data_bytes = struct.pack("<{}H".format(len(data)), *data)
        data_crc = crc_16_kermit(data_bytes).to_bytes(2, byteorder="little")
        self._ser_write(data_bytes)
        self._ser_write(data_crc)

        # validate that the command was processed correctly
        self._check_response()
        # and that the data was received correctly
        self._check_response()

    # start program execution at "addr". if it succeeds, it closes the
    # connection. if it fails, it raises an exception.
    def start_execution(self, addr):
        self._send_command(3, addr, 0)
        self._check_response()

        port = self.port
        self.port = None
        port.close()


def do_bootload(port, program):
    program = tuple(program)
    print("Connecting...")

    bootloader = Bootloader()

    # try to connect while assuming the board is responsive
    try:
        bootloader.connect(port, timeout=1)
    except Timeout: # it wasn't.
        # ask user to try and reset it so the bootloader starts
        print("    (board is unresponsive, please reset it)")
        bootloader.connect(port, timeout=None)

    print("Connected!")

    print("Reading info...")
    info_words = bootloader.read_memory(ROM_INFO_WORDS, 8)
    if info_words[-1] != BOOTLOADER_VERSION:
        raise BootloadError("wrong bootloader version {} (expected {})".format(
            info_words[-1], BOOTLOADER_VERSION))

    print("Downloading program...")
    bootloader.write_memory(0, program)
    print("Verifying program...")
    read_program = bootloader.read_memory(0, len(program))
    if program != read_program:
        raise BootloadError("verification failure")

    print("Starting execution...")
    bootloader.start_execution(0)

    print("Success!")

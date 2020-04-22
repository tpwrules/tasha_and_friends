# bootload a system running the bootloader firmware

import serial
import time
import struct

import crcmod.predefined
crc_16_kermit = crcmod.predefined.mkPredefinedCrcFun("kermit")

from .bootloader_fw import ROM_INFO_WORDS, PACKET_MAX_LENGTH, BOOTLOADER_VERSION

class BootloadError(Exception): pass

class BadCRC(BootloadError):
    def __init__(self, expected, received):
        self.expected = expected
        self.received = received

    def __repr__(self):
        return "BadCRC(expected=0x{:4X}, received=0x{:4X})".format(
            self.expected, self.received)

    def __str__(self):
        return "Bad CRC: expected 0x{:04X} but received 0x{:04X}".format(
            self.expected, self.received)

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

    def _command(self, command, params):
        if self.port is None:
            raise BootloadError("not connected to target")

        cmd_words = []
        # start with the command word
        cmd_words.append((command << 8) + len(params))
        # then send all the parameters
        cmd_words.extend(params)
        cmd_bytes = struct.pack("<{}H".format(len(cmd_words)), *cmd_words)
        # and finally, the CRC of everything above
        cmd_bytes += crc_16_kermit(cmd_bytes).to_bytes(2, byteorder="little")

        # reset the serial transmission to avoid sending or receiving junk from
        # previous (potentially errored) commands
        self.port.reset_input_buffer()
        self.port.reset_output_buffer()
        # then send the current command
        self.port.write(cmd_bytes)

        # read back the response word (which is secretly two bytes)
        resp_length = self._ser_read(1)[0] # + 1 for CRC word
        resp_code = self._ser_read(1)[0]
        resp_bytes = bytes([resp_length, resp_code])
        resp_bytes += self._ser_read(2*(resp_length+1)) # + 1 for CRC word
        # + 2 for CRC and command words
        resp_data = struct.unpack("<{}H".format(resp_length+2), resp_bytes)
        
        # verify CRC (not including the CRC itself)
        calc_crc = crc_16_kermit(resp_bytes[:-2])
        resp_data, claimed_crc = resp_data[:-1], resp_data[-1]
        if calc_crc != claimed_crc:
            raise BadCRC(calc_crc, claimed_crc)

        # handle error response
        if resp_code == 2:
            if resp_data[1] == 3:
                raise Timeout("target said 'timeout'")
            problems = {0: "unknown command", 1: "invalid length", 2: "bad CRC"}
            raise BootloadError("target said '{}'".format(
                problems.get(resp_data[1], resp_data[1])))

        return resp_code, resp_data[1:]

    # connect to the target on serial port "port". give up after (about)
    # "timeout" seconds. return if connected or throw exception if failure
    def connect(self, port, timeout=None):
        # create a serial port to connect to the target. we set a 600ms timeout,
        # slightly over the 500ms timeout in the firmware, to make sure we
        # receive timeout errors.

        port = serial.Serial(port=port, baudrate=2_000_000, timeout=0.6)
        self.port = port

        try:
            if timeout is not None:
                timed_out = time.monotonic()+timeout
            while timeout is None or (time.monotonic() < timed_out):
                # say hello
                try:
                    resp_code, resp_data = self._command(1, [])
                except Timeout as e:
                    # ignore timeouts and try to do it again, hopefully when
                    # the target has timed out and everything is reset.
                    continue
                # if we succeeded, we are done
                if resp_code == 1:
                    return # port is saved and we are connected
                else:
                    raise BootloadError("unexpected response {}".format(
                        resp_code))
            else: # loop condition failed, i.e. we timed out
                raise Timeout("connection timeout")
        except:
            self.port = None # we did not actually connect
            raise

    # read "length" words from the target starting at "addr"
    def read_memory(self, addr, length):
        all_data = []
        # we can only read a certain number of words at a time
        for start in range(0, length, PACKET_MAX_LENGTH):
            curr_addr = addr + start
            end = min(start+PACKET_MAX_LENGTH, length)
            resp_code, resp_data = self._command(4, [curr_addr, end-start])
            if resp_code != 3:
                raise BootloadError("unexpected response {}".format(resp_code))
            all_data.extend(resp_data)

        return all_data

    # write the "data" words to the target starting at "addr"
    def write_memory(self, addr, data):
        # we can only write a certain number of words at a time
        for start in range(0, len(data), PACKET_MAX_LENGTH-1):
            resp_code, resp_data = self._command(2,
                [addr+start, *data[start:start+PACKET_MAX_LENGTH-1]])
            if resp_code != 1:
                raise BootloadError("unexpected response {}".format(resp_code))

    # start program execution at "addr". if it succeeds, it closes the
    # connection. if it fails, it raises an exception.
    def start_execution(self, addr):
        resp_code, resp_data = self._command(3, [addr])
        if resp_code != 1:
            raise BootloadError("unexpected response {}".format(resp_code))

        port = self.port
        self.port = None
        port.close()

def do_bootload(port, program):
    print("Connecting...")

    bootloader = Bootloader()

    # try to connect while assuming the board is responsive
    try:
        bootloader.connect(port, timeout=2)
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

# firmware to play back TASes at high speed

# notational notes:
# boneless is a word-based architecture, it has no concept of the 8 bit byte.
# but we do, so we have to define what a word means.
# * a "word" is a 16 bit unsigned integer, transmitted and stored in
#   little-endian byte order.
# * an "address" selects one "word".

# we define "CRC" as CRC-16/KERMIT (as defined by anycrc). it's computed in
# little-endian order, such that the CRC of words [0x0102, 0x0304] equals the 
# CRC of bytes [0x2, 0x1, 0x3, 0x4]

# HOW IT WORKS

# The TAS is composed of a long sequence of "latches". To us, these are 5 word
# quantities that need to make it out to the hardware in time.

# Including controller information and APU frequency confguration, we need to be
# able to stream around 1.4Mbits/s peak into the firmware. With a 1.6Mbits/s
# maximum rate, this will be a bit tight. Complicating things is the fact that
# the FTDI device imposes a 16ms device -> host latency.

# To handle this, we have a very large ring buffer to hold latches. We keep
# track of how much space remains in the buffer, plus the "stream position", a
# quantity that starts at 0 and increments every latch (and wraps around once it
# overflows a word). "Large" being a relative term; we can hold about 170ms of
# latches.

# Every 25ms, the firmware sends out a status packet, which tells the host the
# current stream position and how much space there is in the buffer. Because of
# the latency, the information is outdated as soon as it is sent. However, the
# host knows its own stream position, so it can calculate how much data has
# arrived and reduce the buffer space correspondingly

# If there is an error, then the firmware will immediately send a status packet
# with the corresponding error code. In response, the host will cancel all
# communications, wait 5ms (for all the buffers to empty and the firmware to
# time out and reset the reception), then resume transmission at the stream
# position sent in the error packet.

# playback command packet format:
# first word: command
#   bits 7-0: number of parameters, always 3 for the playback system's commands
#   bits 15-8: command number, defined later
# second word: parameter 1 (command specific)
# third word: parameter 2 (command specific)
# fourth word: parameter 3 (command specific)
# fifth word: CRC of previous words

# Note: also accepts the bootloader hello command (command number 1 with 2
# unused parameters)

# playback status packet format
# first word: result
#   bits 7-0: number of parameters, always 3 for the playback system's responses
#   bits 15-8: result code, always 0x10 for the playback system's responses
# second word: last error:
#              0=no error, 1=invalid command, 2=bad CRC, 3=RX error/timeout
#              4=buffer underrun
#  third word: stream position
# fourth word: buffer space remaining
#  fifth word: CRC of previous words

# commands
# command 0x10: send latches
#   parameter 1: stream position
#   parameter 2: number of latches
#   parameter 3: unused
#   purpose: send latch data.
#
#            there is no response once the command packet is received and
#            validated. the firmware expects "number of latches"*5 words to
#            follow, and a CRC of them all. if there is a problem, an error
#            status packet will be sent as described above.

# command 0x11: request status
#   parameter 1: unused
#   parameter 2: unused
#   parameter 3: unused
#   purpose: request a status packet be immediately sent.

import random

from boneless.arch.opcode import Instr
from boneless.arch.opcode import *
from .bonetools import *

from ..gateware.periph_map import p_map

# MEMORY MAP We have a 16K word RAM into which we have to fit all the code,
# buffers, and register windows. We need as large a buffer as possible. We don't
# bother with write protection since the system can just be reset and the
# application can be redownloaded in the event of any corruption.

# Address     | Size  | Purpose
# ------------+-------+--------------------------------
# 0x0000-03BF | 960   | Code and variables
# 0x03C0-03FF | 64    | Register windows (8x)
# 0x0400-3FFF | 15360 | Latch buffer

# we want the latch buffer to be a multiple of 5 words, which, conveniently, it
# naturally is.
LATCH_BUF_START = 0x400
LATCH_BUF_END = 0x4000

FW_MAX_LENGTH = 0x3C0
INITIAL_REGISTER_WINDOW = 0x3F8

def make_firmware():
    fw = [
        # start from "reset" (i.e. download is finished)
        
        # set up initial register window. we get a free one from the bootloader
        # (so that we can load a register with the window address), but we can't
        # keep using it.
        MOVI(R0, INITIAL_REGISTER_WINDOW),
        STW(R0),

        # set UART receive timeout to about 2ms. we can't afford to be waiting!
        MOVI(R0, int((12e6*(2/1000))/256)),
        STXA(R0, p_map.uart.w_rt_timer),
        # write something to reset CRC to its initial value
        STXA(R0, p_map.uart.w_crc_reset),
    ]
    r = RegisterManager(
        )
    fw.append([
    L("main_loop"),

    # temporary test
    L("rx_wait"),
        LDXA(R1, p_map.uart.r_rx_lo),
        ROLI(R1, R1, 1),
        BS1("rx_wait"),

        MOVR(R0, "hi"),

    L("tx_wait"),
        LDXA(R1, p_map.uart.r_tx_status),
        ANDI(R1, R1, 1),
        BZ0("tx_wait"),

        LD(R1, R0, 0),
        CMPI(R1, 0),
        BEQ("rx_wait"),
        STXA(R1, p_map.uart.w_tx_lo),
        ADDI(R0, R0, 1),
        J("tx_wait"),

    L("hi"),
        list(ord(c) for c in "Hello, world!"), 0
    ])

    # assemble just the code region
    assembled_fw = Instr.assemble(fw)
    fw_len = len(assembled_fw)
    if len(assembled_fw) > FW_MAX_LENGTH:
        raise ValueError(
            "firmware length {} is over max of {} by {} words".format(
                fw_len, FW_MAX_LENGTH, fw_len-FW_MAX_LENGTH))
    elif True:
        print("firmware length {} is under max of {} by {} words".format(
            fw_len, FW_MAX_LENGTH, FW_MAX_LENGTH-fw_len))

    # we don't need to add anything else. the buffer and the windows will be
    # garbage, but it doesn't matter.

    return assembled_fw

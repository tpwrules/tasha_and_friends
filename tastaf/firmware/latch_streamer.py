# firmware to play back TASes at high speed by just streaming in latches.
# includes APU frequency adjustments too.

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
#              REGULAR ERRORS
#              0x00=no error, 0x01=invalid command, 0x02=bad CRC, 0x03=RX error,
#              0x04=RX timeout
#              FATAL ERRORS (playback must be restarted)
#              0x40=buffer underrun, 0x41=missed latch
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
from enum import IntEnum

from boneless.arch.opcode import Instr
from boneless.arch.opcode import *
from .bonetools import *

from ..gateware.periph_map import p_map

__all__ = ["make_firmware", "ErrorCode"]

class ErrorCode(IntEnum):
    NONE = 0x00
    INVALID_COMMAND = 0x01
    BAD_CRC = 0x02
    RX_ERROR = 0x03
    RX_TIMEOUT = 0x04
    # this code and after are fatal errors
    FATAL_ERROR_START = 0x40
    BUFFER_UNDERRUN = 0x40
    MISSED_LATCH = 0x41

# MEMORY MAP
# We have a 16K word RAM into which we have to fit all the code, buffers, and
# register windows. We need as large a buffer as possible. We don't bother with
# write protection since the system can just be reset and the application can be
# redownloaded in the event of any corruption.

# Address     | Size  | Purpose
# ------------+-------+--------------------------------
# 0x0000-03BF | 960   | Code and variables
# 0x03C0-03FF | 64    | Register windows (8x)
# 0x0400-3FFF | 15360 | Latch buffer

# we want the latch buffer to be a multiple of 5 words, which, conveniently, it
# naturally is.
LATCH_BUF_START = 0x400
LATCH_BUF_END = 0x4000
LATCH_BUF_SIZE = (LATCH_BUF_END-LATCH_BUF_START)//5

FW_MAX_LENGTH = 0x3C0
INITIAL_REGISTER_WINDOW = 0x3F8

# variable number in the "vars" array. we don't bother giving variables
# individual labels because loading a variable from a label requires a register
# equal to zero, and the non-EXTI immediate size is smaller. so if we load the
# base of all the variables into that register, we can load any number of
# variables without having to keep a register zeroed and without having to use
# EXTIs to address anything.
class Vars(IntEnum):
    # the buffer is a ring buffer. head == tail is empty, head-1 == tail is full
    # (mod size). note that these are in units of latches, not words.
    buf_tail = 0
    buf_head = 1

    stream_pos = 2

# queue an error packet for transmission and return to main loop
# on entry (in caller window)
# R5: error code
def f_handle_error():
    lp = "_{}_".format(random.randrange(2**32))
    r = RegisterManager("R6:fp R5:error_code")
    fw = [
        # set up register frame and load parameters
        LDW(r.fp, -8),
        LD(r.error_code, r.fp, 5),

        # for now just blast the error out over the UART
    L(lp+"blast"),
        STXA(r.error_code, p_map.uart.w_tx_lo),
        J(lp+"blast"),
    ]

    return fw

# put a new latch into the SNES interface if necessary
# on entry (in caller window)
# R7: return address
def f_update_interface():
    lp = "_{}_".format(random.randrange(2**32))
    r = RegisterManager("R5:buf_head R4:buf_tail R3:buf_addr R2:status "
        "R1:latch_data R0:vars")
    fw = [
        # set up register frame
        ADJW(-8),
        # did the data in the interface get latched?
        LDXA(r.status, p_map.snes.r_did_latch),
        AND(r.status, r.status, r.status),
        BZ(lp+"ret"), # if zero, then no; we don't need to put anything new in

        # it did, so we have to update it. load the buffer pointers
        MOVR(r.vars, "vars"),
        LD(r.buf_head, r.vars, Vars.buf_head),
        LD(r.buf_tail, r.vars, Vars.buf_tail),
        # is there anything in there?
        CMP(r.buf_head, r.buf_tail),
        BEQ(lp+"empty"), # the pointers are equal, so nope
        # ah, good. there is. convert the buffer tail index into the address
        SLLI(r.buf_addr, r.buf_tail, 2),
        ADD(r.buf_addr, r.buf_addr, r.buf_tail),
        ADDI(r.buf_addr, r.buf_addr, LATCH_BUF_START),
        # then transfer the data to the interface
        LD(r.latch_data, r.buf_addr, 0),
        STXA(r.latch_data, p_map.snes.w_p1d0),
        LD(r.latch_data, r.buf_addr, 1),
        STXA(r.latch_data, p_map.snes.w_p1d1),
        LD(r.latch_data, r.buf_addr, 2),
        STXA(r.latch_data, p_map.snes.w_p2d0),
        LD(r.latch_data, r.buf_addr, 3),
        STXA(r.latch_data, p_map.snes.w_p2d1),
        # soon we will be transferring an APU frequency control word, but that
        # doesn't exist yet. just repeat the last store to make sure the timing
        # matches.
        LD(r.latch_data, r.buf_addr, 3),
        STXA(r.latch_data, p_map.snes.w_p2d1),
        # did we miss a latch? if another latch happened while we were
        # transferring data (or before we started), the console would get junk.
        # this read also clears the did latch and missed latch flags.
        LDXA(r.status, p_map.snes.r_missed_latch_and_ack),
        AND(r.status, r.status, r.status),
        BNZ(lp+"missed"), # ah crap, the flag is set.
        # otherwise, we've done our job. advance the buffer pointer.
        ADDI(r.buf_tail, r.buf_tail, 1),
        CMPI(r.buf_tail, LATCH_BUF_SIZE),
        BNE(lp+"advanced"),
        MOVI(r.buf_tail, 0),
    L(lp+"advanced"),
        ST(r.buf_tail, r.vars, Vars.buf_tail),
    L(lp+"ret"),
        ADJW(8),
        JR(R7, 0), # R7 in caller's window
    ]
    r -= "buf_head"
    r += "R5:error_code"
    fw.append([
    L(lp+"empty"), # the buffer is empty so we are screwed
        MOVI(r.error_code, ErrorCode.BUFFER_UNDERRUN),
        J("handle_error"),
    L(lp+"missed"), # we missed a latch so we are screwed
        MOVI(r.error_code, ErrorCode.MISSED_LATCH),
        J("handle_error"),
    ])

    return fw

# we accept some priming latches to download with the code. this way there is
# some stuff in the buffer before communication gets reestablished. really we
# only need one latch that we can put in the interface at the very start. just
# sticking it in the buffer to begin with avoids special-casing that latch, and
# the extra is nice to jumpstart the buffer.
def make_firmware(priming_latches=[]):
    num_priming_latches = len(priming_latches)//5
    if len(priming_latches) % 5 != 0:
        raise ValueError("priming latches must have 5 words per latch")

    if num_priming_latches > LATCH_BUF_SIZE-1:
        raise ValueError("too many priming latches: got {}, max is {}".format(
            num_priming_latches, LATCH_BUF_SIZE-1))

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
        # write something to force a latch so the first latch makes its way into
        # the interface
        STXA(R0, p_map.snes.w_force_latch),
    ]
    r = RegisterManager("R7:lr")
    fw.append([
    L("main_loop"),
        # eventually we will communicate but for now just practice sending out
        # latches
        JAL(r.lr, "update_interface"),
        J("main_loop"),
    ])

    # define all the variables
    defs = [0]*len(Vars)
    # the buffer is primed with some latches so that we can start before
    # communication gets reestablished
    defs[Vars.buf_head] = num_priming_latches
    defs[Vars.stream_pos] = num_priming_latches
    fw.append([
    L("vars"),
        defs
    ])

    # include all the functions
    fw.append([
    L("update_interface"),
        f_update_interface(),
    L("handle_error"),
        f_handle_error(),
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

    # pad it out until the latch buffer starts
    assembled_fw.extend([0]*(LATCH_BUF_START-len(assembled_fw)))
    # then fill it with the priming latches
    assembled_fw.extend(priming_latches)

    return assembled_fw

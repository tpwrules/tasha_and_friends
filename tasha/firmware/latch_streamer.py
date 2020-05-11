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
# first word: header (always 0x7A5A)
# second word: command
#   bits 7-0: number of parameters, always 3 for the playback system's commands
#   bits 15-8: command number, defined later
# third word: parameter 1 (command specific)
# fourth word: parameter 2 (command specific)
# fifth word: parameter 3 (command specific)
# sixth word: CRC of previous words (except first)

# Note: also accepts the bootloader hello command (command number 1 with 2
# unused parameters)

# playback status packet format
# first word: header (always 0x7A5A)
# second word: result
#   bits 7-0: number of parameters, always 3 for the playback system's responses
#   bits 15-8: result code, always 0x10 for the playback system's responses
# third word: last error:
#              REGULAR ERRORS
#              0x00=no error, 0x01=invalid command, 0x02=bad CRC, 0x03=RX error,
#              0x04=RX timeout
#              FATAL ERRORS (playback must be restarted)
#              0x40=buffer underrun, 0x41=missed latch
#  fourth word: stream position
# fifth word: buffer space remaining
#  sixth word: CRC of previous words (except first)

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
# We have a 32K word RAM into which we have to fit all the code, buffers, and
# register windows. We need as large a buffer as possible. We don't bother with
# write protection since the system can just be reset and the application can be
# redownloaded in the event of any corruption.

# Address     | Size  | Purpose
# ------------+-------+--------------------------------
# 0x0000-01BF | 448   | Code and variables
# 0x01C0-01FF | 64    | Register windows (8x)
# 0x0200-7FFF | 32256 | Latch buffer

# we want the latch buffer to be a multiple of 5 words so it can hold an integer
# number of latches
LATCH_BUF_START = 0x200
LATCH_BUF_END = 0x8000
LATCH_BUF_SIZE = (LATCH_BUF_END-LATCH_BUF_START)//5

FW_MAX_LENGTH = 0x1C0
INITIAL_REGISTER_WINDOW = 0x1F8

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
    last_error = 3

# queue an error packet for transmission and return to main loop
# on entry (in caller window)
# R5: error code
def f_handle_error():
    lp = "_{}_".format(random.randrange(2**32))
    r = RegisterManager("R5:error_code R4:last_error R0:vars")
    fw = [
        # error code is already in R5. since we don't return, we don't have to
        # set up our own register frame

        # is the current error a fatal error?
        CMPI(r.error_code, ErrorCode.FATAL_ERROR_START),
        BGEU(lp+"transmit"), # yes, send the error out
        # do we already have an error code stored?
        # get the last error
        MOVR(r.vars, "vars"),
        LD(r.last_error, r.vars, Vars.last_error),
        CMPI(r.last_error, ErrorCode.NONE),
        BEQ(lp+"transmit"), # no, so send the current one out

        # otherwise, the host already knows that there was an error, and one
        # error is likely to lead to more. just go back to the main loop and
        # wait.
        J("main_loop"),

    L(lp+"transmit"),
        # store the error
        ST(r.error_code, r.vars, Vars.last_error),
        # then send a status packet containing that error
        J("send_status_packet")
    ]

    return fw

# put a new latch into the SNES interface if necessary
# on entry (in caller window)
# R7: return address
def f_update_interface():
    lp = "_{}_".format(random.randrange(2**32))
    r = RegisterManager("R6:last_error R5:buf_head R4:buf_tail R3:buf_addr "
        "R2:status R1:latch_data R0:vars")
    fw = [
        # set up register frame
        ADJW(-8),
        # did the data in the interface get latched?
        LDXA(r.status, p_map.snes.r_did_latch),
        AND(r.status, r.status, r.status),
        BZ(lp+"ret"), # if zero, then no; we don't need to put anything new in

        # it did, so we have to update it. load the buffer pointers
        MOVR(r.vars, "vars"),
        # first check if we logged a fatal error
        LD(r.last_error, r.vars, Vars.last_error),
        CMPI(r.last_error, ErrorCode.FATAL_ERROR_START),
        # if we did, just return. this makes sure send_status_packet will
        # continue sending the packet instead of us re-entering it through
        # handle_error and sending another packet in the middle of the first
        BGEU(lp+"ret"),
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

# jumps right back to main loop
def send_status_packet():
    lp = "_{}_".format(random.randrange(2**32))
    r = RegisterManager(
        "R7:lr R6:comm_word R5:txlr R4:temp "
        "R3:space_remaining R2:buf_head R1:buf_tail R0:vars")
    fw = [
    L("send_status_packet"),
        # calculate status variables
        MOVR(r.vars, "vars"),
        LD(r.buf_tail, r.vars, Vars.buf_tail),
        LD(r.buf_head, r.vars, Vars.buf_head),
        CMP(r.buf_tail, r.buf_head),
        BGTU(lp+"not_wrapped"),
        ADDI(r.buf_tail, r.buf_tail, LATCH_BUF_SIZE),
    L(lp+"not_wrapped"),
        SUB(r.space_remaining, r.buf_tail, r.buf_head),
        SUBI(r.space_remaining, r.space_remaining, 1), # one is always empty
    ]
    r -= "buf_head buf_tail"
    r += "R2:stream_pos R1:last_error"
    fw.append([
        LD(r.stream_pos, r.vars, Vars.stream_pos),
        LD(r.last_error, r.vars, Vars.last_error),

        # send the header first
        MOVI(r.comm_word, 0x7A5A),
        JAL(r.txlr, lp+"tx_comm_word"),

        # then reset the UART CRC
        STXA(r.temp, p_map.uart.w_crc_reset), # we can write anything

        MOVI(r.comm_word, 0x1003),
        JAL(r.txlr, lp+"tx_comm_word"),
        MOV(r.comm_word, r.last_error),
        JAL(r.txlr, lp+"tx_comm_word"),
        MOV(r.comm_word, r.stream_pos),
        JAL(r.txlr, lp+"tx_comm_word"),
        MOV(r.comm_word, r.space_remaining),
        JAL(r.txlr, lp+"tx_comm_word"),
        # CRC is still being calculated, prepare for return
        MOVR(r.txlr, "main_loop"), # return destination
        # reset the timer to send another status packet in another 25ms
        MOVI(r.temp, int((12e6*(25/1000))/256)),
        STXA(r.temp, p_map.timer.timer[0].w_value),
        # now we can send it
        LDXA(r.comm_word, p_map.uart.r_crc_value),
        # fall through

    L(lp+"tx_comm_word"),
        # set return address to first loop so we can branch to update_interface
        # and have it return correctly
        MOVR(r.lr, lp+"tx_lo"),
    L(lp+"tx_lo"),
        # wait for buffer space
        LDXA(r.temp, p_map.uart.r_tx_status),
        ANDI(r.temp, r.temp, 1),
        # none yet, go update the interface while we wait
        BZ0("update_interface"),
        # then send the low byte
        STXA(r.comm_word, p_map.uart.w_tx_lo),
        # and repeat for the high byte
        MOVR(r.lr, lp+"tx_hi"),
    L(lp+"tx_hi"),
        LDXA(r.temp, p_map.uart.r_tx_status),
        ANDI(r.temp, r.temp, 1),
        BZ0("update_interface"),
        STXA(r.comm_word, p_map.uart.w_tx_hi),
        # and we're done
        JR(r.txlr, 0),
        # WARNING! the CRC is still being calculated, so reading it immediately
        # after this function returns will return garbage
    ])

    return fw

# jumps right back to main loop.
# on entry (in caller window)
# R3: param3
# R2: param2
# R1: param1
# needs to be really fast. we have less than 30 instructions per word!
def cmd_send_latches():
    lp = "_{}_".format(random.randrange(2**32))
    r = RegisterManager(
        "R7:lr R6:latch_word R5:rxlr R4:temp "
        "R3:stream_pos R2:length R1:input_stream_pos R0:vars")
    fw = [
    L("cmd_send_latches"),
        # the host might be sending latches that we already have, so we have to
        # throw them away to avoid duplicates.
        MOVR(r.vars, "vars"),
        LD(r.stream_pos, r.vars, Vars.stream_pos),
    L(lp+"eat_dupes"),
        # keep the interface full
        JAL(r.lr, "update_interface"),

        # do the stream positions match yet?
        CMP(r.stream_pos, r.input_stream_pos),
        BEQ(lp+"done_eating_dupes"), # yup, we're done
        # nope, receive a latch and throw it away
        JAL(r.rxlr, lp+"rx_latch_word"),
        JAL(r.rxlr, lp+"rx_latch_word"),
        JAL(r.rxlr, lp+"rx_latch_word"),
        JAL(r.rxlr, lp+"rx_latch_word"),
        JAL(r.rxlr, lp+"rx_latch_word"),
        # input stream pos is advanced by one more
        ADDI(r.input_stream_pos, r.input_stream_pos, 1),
        # do we have any latches remaining?
        SUBI(r.length, r.length, 1),
        BNZ(lp+"eat_dupes"), # yup, go eat more
    ]
    r -= "stream_pos"
    r += "R3:buf_head"
    fw.append([
        # nope, we don't. load the head so we can save it correctly.
        LD(r.buf_head, r.vars, Vars.buf_head),
        # and reload the stream position because we didn't reach it above.
        LD(r.input_stream_pos, r.vars, Vars.stream_pos),
        J(lp+"loop_done"),

    L(lp+"done_eating_dupes"),
        # we assume we have space at the head
        LD(r.buf_head, r.vars, Vars.buf_head),
    ])
    r -= "vars"
    r += "R0:buf_addr"
    fw.append([
        # figure out its address
        SLLI(r.buf_addr, r.buf_head, 2),
        ADD(r.buf_addr, r.buf_addr, r.buf_head),
        ADDI(r.buf_addr, r.buf_addr, LATCH_BUF_START),

    L(lp+"loop"),
        # keep the interface full
        JAL(r.lr, "update_interface"),

        # receive all the words in this latch
        JAL(r.rxlr, lp+"rx_latch_word"),
        ST(r.latch_word, r.buf_addr, 0),
        JAL(r.rxlr, lp+"rx_latch_word"),
        ST(r.latch_word, r.buf_addr, 1),
        JAL(r.rxlr, lp+"rx_latch_word"),
        ST(r.latch_word, r.buf_addr, 2),
        JAL(r.rxlr, lp+"rx_latch_word"),
        ST(r.latch_word, r.buf_addr, 3),
        JAL(r.rxlr, lp+"rx_latch_word"),
        ST(r.latch_word, r.buf_addr, 4),

        # keep the interface full
        JAL(r.lr, "update_interface"),

        # stream advanced by 1
        ADDI(r.input_stream_pos, r.input_stream_pos, 1),

        # bump the head correspondingly
        ADDI(r.buf_head, r.buf_head, 1),
        CMPI(r.buf_head, LATCH_BUF_SIZE),
        BNE(lp+"not_wrapped"),
        # we're at the end, reset back to the start
        MOVI(r.buf_head, 0),
        MOVI(r.buf_addr, LATCH_BUF_START),
        # do we have any latches remaining?
        SUBI(r.length, r.length, 1),
        BNZ(lp+"loop"), # yup, go take care of them
        J(lp+"loop_done"),
    L(lp+"not_wrapped"),
        # we're not at the end, advance the buffer appropriately
        ADDI(r.buf_addr, r.buf_addr, 5),
        # do we have any latches remaining?
        SUBI(r.length, r.length, 1),
        BNZ(lp+"loop"), # yup, go take care of them

    L(lp+"loop_done"),
        # receive and validate the CRC
        JAL(r.rxlr, lp+"rx_latch_word"),
        LDXA(r.temp, p_map.uart.r_crc_value),
        AND(r.temp, r.temp, r.temp),
        BZ0(lp+"bad_crc"),
    ])
    r -= "buf_addr"
    r += "R0:vars"
    fw.append([
        # if the CRC validated, then we need to update the head pointer
        MOVR(r.vars, "vars"),
        ST(r.buf_head, r.vars, Vars.buf_head),
        # and stream position
        ST(r.input_stream_pos, r.vars, Vars.stream_pos),
        # and now, we are done
        J("main_loop"),
    ])
    r -= "rxlr"
    r += "R5:error_code"
    fw.append([
    L(lp+"bad_crc"),
        # handle the error
        MOVI(r.error_code, ErrorCode.BAD_CRC),
        J("handle_error"),
    ])
    r -= "error_code"
    r += "R5:rxlr"
    fw.append([
    L(lp+"rx_latch_word"),
        # set return address to first loop so we can branch to update_interface
        # and have it return correctly
        MOVR(r.lr, lp+"rlw_lo"),
    L(lp+"rlw_lo"),
        # check for UART errors (timeouts, overflows, etc.)
        LDXA(r.temp, p_map.uart.r_error),
        AND(r.temp, r.temp, r.temp), # set flags
        BZ0(lp+"rlw_error"),
        # check if we have a new byte
        LDXA(r.latch_word, p_map.uart.r_rx_lo),
        ROLI(r.latch_word, r.latch_word, 1),
        # nope, go keep the interface up to date (it will return to rlw_lo)
        BS1("update_interface"),
        # we have the low byte in latch_word

        MOVR(r.lr, lp+"rlw_hi"),
    L(lp+"rlw_hi"),
        # check again for UART errors
        LDXA(r.temp, p_map.uart.r_error),
        AND(r.temp, r.temp, r.temp),
        BZ0(lp+"rlw_error"),
        # and see if we have the high byte yet
        LDXA(r.temp, p_map.uart.r_rx_hi),
        ADD(r.temp, r.temp, r.temp),
        # nope, go keep the interface up to date (it will return to rlw_hi)
        BC1("update_interface"),
        # put the bytes together
        OR(r.latch_word, r.latch_word, r.temp),
        # and we are done
        JR(r.rxlr, 0),
    ])
    r -= "rxlr"
    r += "R5:error_code"
    fw.append([
    L(lp+"rlw_error"),
        # assume it was a timeout error
        MOVI(r.error_code, ErrorCode.RX_TIMEOUT),
        # was it a timeout error?
        ANDI(r.latch_word, r.temp, 2),
        BZ0("handle_error"), # it was. go deal with it
        # otherwise, it must have been a framing error
        MOVI(r.error_code, ErrorCode.RX_ERROR),
        # go deal with it
        J("handle_error"),
    ])

    return fw

def main_loop_body():
    lp = "_{}_".format(random.randrange(2**32))
    r = RegisterManager(
        "R7:lr R6:comm_word R5:rxlr R4:temp "
        "R3:param3 R2:param2 R1:param1 R0:command")
    fw = [
    L("main_loop"),
        # make sure the interface is kept up to date
        JAL(r.lr, "update_interface"),

        # is it time to send the status packet?
        LDXA(r.temp, p_map.timer.timer[0].r_ended),
        AND(r.temp, r.temp, r.temp),
        BZ0("send_status_packet"), # the timer ended

        # clear any UART errors and reset the receive timeout
        MOVI(r.temp, 0xFFFF),
        STXA(r.temp, p_map.uart.w_error_clear),

        # wait for the low header byte 0x5A. if we time out here, we just wait
        # some more.
        MOVR(r.lr, "rx_header_lo"),
    L("rx_header_lo"),
        LDXA(r.temp, p_map.uart.r_error),
        CMPI(r.temp, 2),
        BEQ("main_loop"),
        AND(r.temp, r.temp, r.temp),
        BZ0(lp+"rcw_error"),
        
        # receive the byte and go complain if it doesn't match
        LDXA(r.comm_word, p_map.uart.r_rx_hi),
        ADD(r.comm_word, r.comm_word, r.comm_word),
        BC1("update_interface"), # update the interface if nothing's come yet

        CMPI(r.comm_word, 0x5A << 8),
        BNE(lp+"header_bad"),

        MOVI(r.comm_word, 0),
    L("rx_header_hi"),
        # now receive the actual high byte 0x7A
        JAL(r.rxlr, lp+"rx_comm_byte_hi"),
        # keep the interface full
        JAL(r.lr, "update_interface"),
        # if we actually received the low byte, look for the high byte again
        CMPI(r.comm_word, 0x5A << 8),
        BEQ("rx_header_hi"),
        # if we didn't receive the high byte, go complain
        CMPI(r.comm_word, 0x7A << 8),
        BNE(lp+"header_bad"),

        # we have confirmed both header bytes. who knows what the CRC is now.
        STXA(r.temp, p_map.uart.w_crc_reset), # write something to reset it

        # receive the command packet
        JAL(r.rxlr, lp+"rx_comm_word"),
        MOV(r.command, r.comm_word),
        JAL(r.rxlr, lp+"rx_comm_word"),
        MOV(r.param1, r.comm_word),
        JAL(r.rxlr, lp+"rx_comm_word"),
        MOV(r.param2, r.comm_word),
        JAL(r.rxlr, lp+"rx_comm_word"),
        # if the host sent the hello command, we need to check for it now
        # because it's a word shorter than all the others
        CMPI(r.command, 0x0102),
        BEQ(lp+"handle_hello"),

        MOV(r.param3, r.comm_word),
        JAL(r.rxlr, lp+"rx_comm_word"),
        # if the current CRC is x, then CRC(x) = 0, always. we use to reset the
        # CRC to 0 when we are done sending or receiving.
        # so, we've received all the data words and the CRC. if everything went
        # okay, the CRC should now be 0.
        LDXA(r.temp, p_map.uart.r_crc_value),
        AND(r.temp, r.temp, r.temp),
        BZ(lp+"crc_ok"),
    ]
    r -= "rxlr"
    r += "R5:error_code"
    fw.append([
    L(lp+"crc_bad"),
        # aw heck, it didn't go okay. send the appropriate error.
        MOVI(r.error_code, ErrorCode.BAD_CRC),
        J("handle_error"),

    L(lp+"header_bad"),
        MOVI(r.error_code, ErrorCode.INVALID_COMMAND),
        J("handle_error"),

    L(lp+"crc_ok"),
        # we've got a valid packet, so reset the error state (if the error was
        # not fatal)

        # rudely borrow LR
        MOVR(r.lr, "vars"),
        LD(r.error_code, r.lr, Vars.last_error),
        CMPI(r.error_code, ErrorCode.FATAL_ERROR_START),
        BGEU(lp+"error_done"),

        MOVI(r.error_code, ErrorCode.NONE),
        ST(r.error_code, r.lr, Vars.last_error),

    L(lp+"error_done"),

        # make sure the interface is kept up to date
        JAL(r.lr, "update_interface"),

        # now we need to figure out the command. the low 8 bits are the length,
        # which is always 3. the high 8 bits are the command number, and the
        # first command number is 0x10. each command is separated by 0x100.
        
        SUBI(r.command, r.command, 0x1003),
        BEQ("cmd_send_latches"),
        SUBI(r.command, r.command, 0x100),
        BEQ("send_status_packet"),

        # oh no, we don't know the command
        MOVI(r.error_code, ErrorCode.INVALID_COMMAND),
        J("handle_error"),

    L(lp+"handle_hello"),
        # validate the CRC (the word was already received for us)
        LDXA(r.temp, p_map.uart.r_crc_value),
        AND(r.temp, r.temp, r.temp),
        BNZ(lp+"crc_bad"),
        # we got a valid hello. reset into the bootloader.
        MOVI(R0, 0xFADE),
        MOVI(R1, 0xDEAD),
        STXA(R0, p_map.reset_req.w_enable_key_fade),
        STXA(R1, p_map.reset_req.w_perform_key_dead),
        J(-1), # hang until it happens
    ])
    r -= "error_code"
    r += "R5:rxlr"
    fw.append([
    L(lp+"rx_comm_word"),
        # set return address to first loop so we can branch to update_interface
        # and have it return correctly
        MOVR(r.lr, lp+"rcw_lo"),
    L(lp+"rcw_lo"),
        # check for UART errors (timeouts, overflows, etc.)
        LDXA(r.temp, p_map.uart.r_error),
        AND(r.temp, r.temp, r.temp), # set flags
        BZ0(lp+"rcw_error"),
        # check if we have a new byte
        LDXA(r.comm_word, p_map.uart.r_rx_lo),
        ROLI(r.comm_word, r.comm_word, 1),
        # nope, go keep the interface up to date (it will return to rcw_lo)
        BS1("update_interface"),
        # we have the low byte in comm_word

    L(lp+"rx_comm_byte_hi"),
        MOVR(r.lr, lp+"rcw_hi"),
    L(lp+"rcw_hi"),
        # check again for UART errors
        LDXA(r.temp, p_map.uart.r_error),
        AND(r.temp, r.temp, r.temp),
        BZ0(lp+"rcw_error"),
        # and see if we have the high byte yet
        LDXA(r.temp, p_map.uart.r_rx_hi),
        ADD(r.temp, r.temp, r.temp),
        # nope, go keep the interface up to date (it will return to rcw_hi)
        BC1("update_interface"),
        # put the bytes together
        OR(r.comm_word, r.comm_word, r.temp),
        # and we are done
        JR(r.rxlr, 0),
    ])
    r -= "rxlr"
    r += "R5:error_code"
    fw.append([
    L(lp+"rcw_error"),
        # assume it was a timeout error
        MOVI(r.error_code, ErrorCode.RX_TIMEOUT),
        # was it a timeout error?
        ANDI(r.comm_word, r.temp, 2),
        BZ0("handle_error"), # it was. go deal with it
        # otherwise, it must have been a framing error
        MOVI(r.error_code, ErrorCode.RX_ERROR),
        # go deal with it
        J("handle_error"),
    ])

    return fw

# we accept some priming latches to download with the code. this way there is
# some stuff in the buffer before communication gets reestablished. really we
# only need one latch that we can put in the interface at the very start. just
# sticking it in the buffer to begin with avoids special-casing that latch, and
# the extra is nice to jumpstart the buffer.
def make_firmware(priming_latches=[],
        apu_freq_basic=None,
        apu_freq_advanced=None):

    if apu_freq_basic is None and apu_freq_advanced is not None:
        raise ValueError("must set apu basic before advanced")

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
        # same timeout for the status timer, just cause it's already in the
        # register. once it expires, the correct value will be loaded.
        STXA(R0, p_map.timer.timer[0].w_value),
    ]

    # out of reset, the button registers are all zero, the APU frequency is
    # 24.607104MHz, and latching is disabled. as long as latching remains
    # disabled, the frequency won't change and the console will see no buttons
    # no matter how much it latches.

    # set the initial APU frequency values
    if apu_freq_basic is not None:
        fw.append([
            MOVI(R2, int(apu_freq_basic) & 0xFFFF),
            STXA(R2, p_map.snes.w_apu_freq_basic),
        ])
    if apu_freq_advanced is not None:
        fw.append([
            MOVI(R2, int(apu_freq_advanced) & 0xFFFF),
            STXA(R2, p_map.snes.w_apu_freq_advanced),
        ])
    # force a latch so the APU clock generator gets updated
    fw.append(STXA(R2, p_map.snes.w_force_latch))

    # load the initial buttons into the registers
    fw.append([
        MOVI(R2, priming_latches[0]),
        STXA(R2, p_map.snes.w_p1d0),
        MOVI(R2, priming_latches[1]),
        STXA(R2, p_map.snes.w_p1d1),
        MOVI(R2, priming_latches[2]),
        STXA(R2, p_map.snes.w_p2d0),
        MOVI(R2, priming_latches[3]),
        STXA(R2, p_map.snes.w_p2d1),
    ])

    # now that the registers are loaded, we can turn latching back on. this
    # setup guarantees the console will transition directly from seeing no
    # buttons to seeing the first set of buttons once it latches. there can't be
    # any intermediate states.
    fw.append([
        MOVI(R2, 1),
        STXA(R2, p_map.snes.w_enable_latch),
    ])

    # initialization is done. let's get the party started!
    fw.append(J("main_loop"))

    fw.append(send_status_packet())
    # run the main loop
    fw.append(main_loop_body())
    fw.append(cmd_send_latches())

    # define all the variables
    defs = [0]*len(Vars)
    # the buffer is primed with some latches so that we can start before
    # communication gets reestablished. but we put one in the interface at the
    # beginning
    defs[Vars.buf_head] = num_priming_latches-1
    defs[Vars.stream_pos] = num_priming_latches
    fw.append([
    L("vars"),
        defs
    ])

    # include all the functions
    fw.append([
    L("handle_error"),
        f_handle_error(),
    L("update_interface"),
        f_update_interface(),
    ])

    # assemble just the code region
    assembled_fw = Instr.assemble(fw)
    fw_len = len(assembled_fw)
    if len(assembled_fw) > FW_MAX_LENGTH:
        raise ValueError(
            "firmware length {} is over max of {} by {} words".format(
                fw_len, FW_MAX_LENGTH, fw_len-FW_MAX_LENGTH))
    elif False:
        print("firmware length {} is under max of {} by {} words".format(
            fw_len, FW_MAX_LENGTH, FW_MAX_LENGTH-fw_len))

    # pad it out until the latch buffer starts
    assembled_fw.extend([0]*(LATCH_BUF_START-len(assembled_fw)))
    # then fill it with the priming latches (skipping the one we stuck in the
    # interface at the beginning)
    assembled_fw.extend(priming_latches[5:])

    return assembled_fw

# firmware for the system bootloader

# notational notes:
# boneless is a word-based architecture, it has no concept of the 8 bit byte.
# but we do, so we have to define what a word means.
# * a "word" is a 16 bit unsigned integer, transmitted and stored in
#   little-endian byte order.
# * an "address" selects one "word".

# UART command packet format:
# first word: command
#   bits 7-0: number of words to follow, excluding CRC word and command word
#   bits 15-8: command number, defined later
# next words: command parameters, as defined in command
# last word: CRC-16/KERMIT result, calculated over all preceding words in
# little-endian order: CRC([0x0102, 0x0304]) = CRC([0x2, 0x1, 0x4, 0x3])

# UART response packet format: (in response to command)
# first word: result
#   bits 7-0: number of words to follow, excluding CRC word and result word
#   bits 15-8: result code, defined later
# next words: result information, as defined in result
# last word: CRC-16/KERMIT result, calculated over all preceding words in
# little-endian order: CRC([0x0102, 0x0304]) = CRC([0x2, 0x1, 0x4, 0x3])

# "number of words to follow" for both cases, i.e. length, has a maximum of 32

# commands
# command 1: hello
#   length: 0
#   parameter words: none
#   result codes: success, invalid length
#   purpose: confirm that the bootloader exists and is alive. applications
#            should respond to this command by resetting the system so that the
#            bootloader starts.

# command 2: write data
#   length: 1-max length
#   parameter words: destination address, data to write*length-1
#   result codes: success, invalid length
#   purpose: write words to arbitrary memory address. note that the bootloader
#            lives from 0xFF00 to 0xFFFF, and overwriting it would be bad.

# command 3: jump to code
#   length: 1
#   parameter words: destination address
#   result codes: success, invalid length
#   purpose: jump to given address. register values are undefined after the
#            jump. W points to EXACTLY ONE valid register window. W MUST BE SET
#            EXPLICITLY before any W-relative/adjust instructions are used.

# command 4: read data
#   length: 2
#   parameter words: source address, source length (up to max length)
#   result codes: read result, invalid length
#   purpose: read words from arbitrary memory address.

# results
# result 1: success
#   length: 0
#   parameter words: none
#   purpose: say that everything went great

# result 2: invalid command
#   length: 1
#   parameter words: reason: 0=unknown cmd, 1=invalid length, 2=bad CRC,
#                            3=timeout
#   purpose: say that the command couldn't be processed for whatever reason

# result 3: read result
#   length: 0-max length
#   parameter words: the words
#   purpose: give back the read words

import random

from boneless.arch.opcode import Instr
from boneless.arch.opcode import *
from .bonetools import *

from ..gateware.periph_map import p_map

# INFO WORDS
# The gateware gets to store seven 16-bit words as information about itself. The
# bootloader gets the 8th to store the version. The PC bootload script verifies
# the bootloader version, then passes the remaining words to the PC application.
BOOTLOADER_VERSION = 1

# MEMORY MAP
# We have a 256 word memory into which we have to fit all the code, buffers, and
# register windows. To ensure the bootloader will always work after a reset,
# only the top 64 words can be written to. To ensure the PC bootload script
# always knows where the info words are, we put them right below the RAM region.
# The memory appears nominally at 0xFF00-0xFFFF, but we omit the leading 0xFF
# from the table below.

# Address | Size | Purpose
# --------+------+--------------------------------
# 0x00-B7 | 184  | (R) Code
# 0xB8-BF | 8    | (R) Info words
# 0xC0-DF | 32   | (RW) Packet buffer
# 0xE0-FF | 32   | (RW) Register windows

FW_MAX_LENGTH = 184
PACKET_MAX_LENGTH = 32
ROM_INFO_WORDS = 0xFFB8
RAM_PACKET_BUFFER = 0xFFC0

# receive a packet
# on entry (in caller window):
# R7: return address
# on exit (in our window):
# R2: command number
# R1: command length
# R0: issue: 0 = ok, 1 = bad length, 2 = bad CRC, 3 = timeout,
#            4 = timeout of command word
def _bfw_rx_packet():
    # generate random prefix so that we effectively can make local labels
    lp = "_{}_".format(random.randrange(2**32))
    r = RegisterManager(
        "R7:lr R6:buf_pos R5:buf_end R4:got_temp "
        "R3:got_word R2:command R1:length R0:issue")
    fw = [
        # create register frame
        ADJW(-8),
        # clear the timeout flag in case it's been too long since receiving the
        # last packet
        MOVI(r.got_temp, 2),
        STXA(r.got_temp, p_map.uart.w_error_clear),
        # reset the UART CRC engine before we start reading out the packet
        STXA(r.got_temp, p_map.uart.w_crc_reset), # what we write doesn't matter

        # secretly the command word is two bytes!
        # issue 4 is timing out while receiving the command word. we treat that
        # separately because we don't send timeout errors on the assumption that
        # the host just didn't send anything
        MOVI(r.issue, 4),
        JAL(r.lr, lp+"rx_word"),
        # length is the low byte
        ANDI(r.length, r.got_word, 0x00FF),
        # and the command is the high byte
        SRLI(r.command, r.got_word, 8),

        # make sure we have the buffer space to accept the packet
        MOVI(r.issue, 1), # that would be issue type 1
        CMPI(r.length, PACKET_MAX_LENGTH),
        BGTU(lp+"ret"), # it's too long! abort

        # now we can start receiving the words
        MOVI(r.issue, 3), # with real timeout errors
        MOVI(r.buf_pos, RAM_PACKET_BUFFER),
        ADD(r.buf_end, r.buf_pos, r.length),
    L(lp+"rx_words"),
        JAL(r.lr, lp+"rx_word"),
        ST(r.got_word, r.buf_pos, 0),
        ADDI(r.buf_pos, r.buf_pos, 1),
        CMP(r.buf_pos, r.buf_end),
        BNE(lp+"rx_words"),
    ]
    r -= "buf_pos buf_end"
    r += "R6:calc_crc"
    fw.append([
        # finally, there is the CRC word. we have to read the CRC result from
        # the UART before we receive the word, otherwise the CRC result will
        # include the CRC word which doesn't make any sense
        LDXA(r.calc_crc, p_map.uart.r_crc_value),
        JAL(r.lr, lp+"rx_word"),
        # assume there is no issue with the CRC
        MOVI(r.issue, 0),
        # if they match, that's true
        CMP(r.calc_crc, r.got_word),
        BEQ(lp+"ret"),
        # but if they don't, that's a problem
        MOVI(r.issue, 2),
    L(lp+"ret"),
        ADJW(8),
        JR(R7, 0), # R7 in caller's window
    ])

    fw.append([
    L(lp+"rx_word"),
        # check for timeouts
        LDXA(r.got_word, p_map.uart.r_error),
        ANDI(r.got_word, r.got_word, 2),
        BZ0(lp+"ret"), # issue already set up by caller
        # check for a character
        LDXA(r.got_word, p_map.uart.r_rx_lo),
        ROLI(r.got_word, r.got_word, 1),
        BS1(lp+"rx_word"),
        # get the other character
    L(lp+"rx_word_cont"),
        # check for timeouts
        LDXA(r.got_temp, p_map.uart.r_error),
        ANDI(r.got_temp, r.got_temp, 2),
        BZ0(lp+"ret"), # issue already set up by caller
        # check for a character
        LDXA(r.got_temp, p_map.uart.r_rx_hi),
        ADD(r.got_temp, r.got_temp, r.got_temp),
        BC1(lp+"rx_word_cont"),
        # put characters together
        OR(r.got_word, r.got_word, r.got_temp),
        # and we are done
        JR(r.lr, 0),
    ])

    return fw

# transmit a packet
# on entry (in caller window):
# R7: return address
# R5: result word
# on exit (in our window):
# nothing of interest
def _bfw_tx_packet():
    # generate random prefix so that we effectively can make local labels
    lp = "_{}_".format(random.randrange(2**32))
    r = RegisterManager(
        "R7:lr R6:fp R5:buf_pos R4:buf_end R3:send_word "
        "R2:send_temp R0:length")
    fw = [
        # create register frame
        LDW(r.fp, -8),
        # reset the UART CRC engine before we start sending out the packet
        STXA(r.fp, p_map.uart.w_crc_reset), # what we write doesn't matter

        # get the result word from our caller
        LD(r.send_word, r.fp, 5),
        # save the length
        ANDI(r.length, r.send_word, 0x00FF),
        # send out the word to start the packet
        JR(r.lr, lp+"tx_word"),

        CMPI(r.length, 0), # don't try to send any words if there aren't any
        BEQ(lp+"words_done"),

        MOVI(r.buf_pos, RAM_PACKET_BUFFER),
        ADD(r.buf_end, r.buf_pos, r.length),
    L(lp+"tx_words"),
        LD(r.send_word, r.buf_pos, 0),
        JAL(r.lr, lp+"tx_word"),
        ADDI(r.buf_pos, r.buf_pos, 1),
        CMP(r.buf_pos, r.buf_end),
        BNE(lp+"tx_words"),

    L(lp+"words_done"),
        # get the CRC of everything we've sent so far and send it too
        LDXA(r.send_word, p_map.uart.r_crc_value),
        JAL(r.lr, lp+"tx_word"),

        ADJW(8),
        JR(R7, 0), # R7 in caller's window

    L(lp+"tx_word"),
        # wait for space
        LDXA(r.send_temp, p_map.uart.r_tx_status),
        ANDI(r.send_temp, r.send_temp, 1),
        BZ0(lp+"tx_word"),
        # send the low character
        STXA(r.send_word, p_map.uart.w_tx_lo),
    L(lp+"tx_word_cont"),
        # wait for more space
        LDXA(r.send_temp, p_map.uart.r_tx_status),
        ANDI(r.send_temp, r.send_temp, 1),
        BZ0(lp+"tx_word_cont"),
        # then send the high character
        STXA(r.send_word, p_map.uart.w_tx_hi),
        # and we are done
        JR(r.lr, 0),
    ]

    return fw


def make_bootloader(info_words):

    cleaned_info_words = [int(info_word) & 0xFFFF for info_word in info_words]
    if len(cleaned_info_words) != 7:
        raise ValueError("expected exactly seven info words")
    cleaned_info_words.append(BOOTLOADER_VERSION)

    FW_MAX_LEN = 184


    fw = [
    L("reset"),
        # start from reset. we are always going to start from reset, so we don't
        # have to worry about e.g. changing peripherals back to default modes.

        # set UART receive timeout to about 500ms
        MOVI(R0, int((12e6*.5)/256)),
        STXA(R0, p_map.uart.w_rt_timer),
    ]
    r = RegisterManager(
        "R7:lr R6:fp R5:result_word R3:buf_ptr R2:command R1:length R0:issue")
    fw.append([
    L("main_loop"),
        # receive a packet
        JAL(r.lr, "rx_packet"),
        LDW(r.fp, 0), # fetch window so we can get the return values

        LD(r.issue, r.fp, -8+0),
        # if the issue was 4, it was a timeout when receiveing the command word.
        # we ignore these because they will happen regularly as long as the
        # other side isn't sending commands and so aren't an error.
        CMPI(r.issue, 4),
        BEQ("main_loop"),

        # load LR with the main loop so that subfunctions can just jump to the
        # tx packet routine and have it return to be ready for another packet
        MOVR(r.lr, "main_loop"),
        # and load the pointer to the buffer so the subfunctions can easily
        # access it
        MOVI(r.buf_ptr, RAM_PACKET_BUFFER),

        # if there was any other issue, we need to send it back out
        CMPI(r.issue, 0),
        BNE("sys_packet_tx_issue"),

        LD(r.length, r.fp, -8+1),
        LD(r.command, r.fp, -8+2),
        # figure out what command it is. ideally we would use a switch table but
        # we can't declare them yet
        SUBI(r.command, r.command, 1), # command 1
        BEQ("sys_cmd_hello"),
        SUBI(r.command, r.command, 1), # command 2
        BEQ("sys_cmd_write_data"),
        SUBI(r.command, r.command, 1), # command 3
        BEQ("sys_cmd_jump_to_code"),
        SUBI(r.command, r.command, 1), # command 4
        BEQ("sys_cmd_read_data"),
        # oh no we don't know what it is. fortunately, issue 0 "received ok" is
        # also "bad command"
        J("sys_packet_tx_issue"),
    ])
    r -= "fp command"
    fw.append([
    L("sys_packet_tx_invalid_length"),
        MOVI(r.issue, 1),
        # fall through to tx issue packet
    L("sys_packet_tx_issue"), # send error packet with the given issue
        # store the issue into the packet
        ST(r.issue, r.buf_ptr, 0),
        # result code 2 with length 1
        MOVI(r.result_word, 0x0201),
        J("tx_packet"), # LR is set to return to main loop
    L("sys_packet_tx_success"), # say everything wnet great
        # result code 1 with length 0
        MOVI(r.result_word, 0x0100),
        J("tx_packet"), # LR is set to return to main loop
    ])
    fw.append([
    L("sys_cmd_hello"),
        # technically there shouldn't be any parameters
        CMPI(r.length, 0),
        BNE("sys_packet_tx_invalid_length"),
        # if we're good, say hi back
        J("sys_packet_tx_success"),
    ])
    r += "R6:dest_addr R4:buf_end R2:temp"
    fw.append([
    L("sys_cmd_write_data"), # write some data to some address
        # we need at least the address and one word
        CMPI(r.length, 2),
        BLTU("sys_packet_tx_invalid_length"),
        LD(r.dest_addr, r.buf_ptr, 0),
        ADD(r.buf_end, r.buf_ptr, r.length),
        ADDI(r.buf_ptr, r.buf_ptr, 1),
    L("_scwd_copy"),
        LD(r.temp, r.buf_ptr, 0),
        ST(r.temp, r.dest_addr, 0),
        ADDI(r.buf_ptr, r.buf_ptr, 1),
        ADDI(r.dest_addr, r.dest_addr, 1),
        CMP(r.buf_ptr, r.buf_end),
        BNE("_scwd_copy"),
        J("sys_packet_tx_success"),
    ])
    r -= "dest_addr buf_end temp"
    r += "R6:code_addr"
    fw.append([
    L("sys_cmd_jump_to_code"), # jump to some address
        CMPI(r.length, 1),
        BNE("sys_packet_tx_invalid_length"),
        LD(r.code_addr, r.buf_ptr, 0),
        # tell the host that we successfully got everything before we give up
        # control
        MOVI(r.result_word, 0x0100),
        JAL(r.lr, "tx_packet"),
        # now we can start running the new program
        JR(r.code_addr, 0),
    ])
    r -= "code_addr"
    r += "R6:src_addr R4:buf_end R2:temp"
    fw.append([
    L("sys_cmd_read_data"), # read some data from some address
        CMPI(r.length, 2),
        BNE("sys_packet_tx_invalid_length"),
        LD(r.src_addr, r.buf_ptr, 0),
        LD(r.length, r.buf_ptr, 1),
        # we return the requested number of words as result type 3
        ORI(r.result_word, r.length, 3<<8),
        # make sure we won't overrun our buffer
        CMPI(r.length, PACKET_MAX_LENGTH),
        BGTU("sys_packet_tx_invalid_length"),
        ADD(r.buf_end, r.buf_ptr, r.length),
    L("_scrd_copy"),
        LD(r.temp, r.src_addr, 0),
        ST(r.temp, r.buf_ptr, 0),
        ADDI(r.src_addr, r.src_addr, 1),
        ADDI(r.buf_ptr, r.buf_ptr, 1),
        CMP(r.buf_ptr, r.buf_end),
        BLTU("_scrd_copy"), # ensure we exit even if we're copying 0 words
        # we set the result word before the loop
        J("tx_packet"),
    ])

    # include all the functions
    fw.append([
    L("tx_packet"),
        _bfw_tx_packet(),
    L("rx_packet"),
        _bfw_rx_packet(),
    ])

    # assemble just the code region
    assembled_fw = Instr.assemble(fw)
    fw_len = len(assembled_fw)
    if len(assembled_fw) > FW_MAX_LENGTH:
        raise ValueError(
            "bootrom length {} is over max of {} by {} words".format(
                fw_len, FW_MAX_LENGTH, fw_len-FW_MAX_LENGTH))
    elif True:
        print("bootrom length {} is under max of {} by {} words".format(
            fw_len, FW_MAX_LENGTH, FW_MAX_LENGTH-fw_len))

    # glue on the info words
    assembled_fw.extend(cleaned_info_words)
    # then the (initially zero) RAM region
    assembled_fw.extend([0]*64)

    return assembled_fw

import sys

from boneless.arch.opcode import Instr
from boneless.arch.opcode import *

from ..gateware.periph_map import p_map
from ..host.bootload import do_bootload

# test program to confirm things are working
fw = [
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
]

# bootload the program to the board on the given port
do_bootload(sys.argv[1], Instr.assemble(fw))

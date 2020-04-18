# the core of this whole deal. contains the main CPU and the peripheral hookups.
from nmigen import *
from nmigen.asserts import Past, Rose, Fell

# boneless CPU architecture stuff
from boneless.gateware import ALSRU_4LUT, CoreFSM
from boneless.arch.opcode import Instr
from boneless.arch.opcode import *

from . import uart

# generate a really simple test for now
def make_bootloader():
    uart_addr = 0
    delay_ms = 5000
    delay = int((12e6*(delay_ms/1e3))//(4*3))
    fw = [
    L("main"),
        # wait for the user to type junk and fill up the FIFO
        MOVI(R7, (delay>>16)+1),
        MOVI(R6, delay&0xFFFF),
    L("wait_1"),
        SUBI(R6, R6, 1),
        SBCI(R7, R7, 0),
        BNZ("wait_1"),

        MOVI(R5, ord("A")),
        STXA(R5, uart_addr+6),

    # blast the FIFO back at them
    L("blast_1"),
        # get a character
        LDXA(R5, uart_addr+4),
        ROLI(R5, R5, 1),
        BS1("done_1"), # there wasn't any, we are done here
        # wait for space to transmit it
    L("txwait_1"),
        LDXA(R4, uart_addr+6),
        ANDI(R4, R4, 1),
        BZ0("txwait_1"),
        # then transmit it
        STXA(R5, uart_addr+6),
        J("blast_1"),
    L("done_1"),

        # wait for the user to type junk and fill up the FIFO
        MOVI(R7, (delay>>16)+1),
        MOVI(R6, delay&0xFFFF),
    L("wait_2"),
        SUBI(R6, R6, 1),
        SBCI(R7, R7, 0),
        BNZ("wait_2"),

    MOVI(R5, ord("B")<<8),
    STXA(R5, uart_addr+7),

    # blast the FIFO back at them
    L("blast_2"),
        # get a character
        LDXA(R5, uart_addr+5),
        ANDI(R4, R5, 1),
        BZ0("main"), # there wasn't any, we are done here
        # wait for space to transmit it
    L("txwait_2"),
        LDXA(R4, uart_addr+7),
        ANDI(R4, R4, 1),
        BZ0("txwait_2"),
        # then transmit it
        STXA(R5, uart_addr+7),
        J("blast_2"),
    ]

    assembled_fw = Instr.assemble(fw)

    return assembled_fw, len(assembled_fw)

class TASHACore(Elaboratable):
    def __init__(self, snes_signals, uart_signals, memory_signals):
        self.snes_signals = snes_signals
        self.uart_signals = uart_signals
        self.memory_signals = memory_signals

        # compile the bootloader first. we have a bootloader so a) the code can
        # be updated without having to reconfigure the FPGA and b) because the
        # main RAM can't always be loaded from configuration anyway.

        # the "rolen" is how much of the bootrom should be read only. it's
        # mostly a nice debugging feature so that a rogue program can't trash
        # the rom and require the fpga to be reconfigured. the whole thing can't
        # be ROM because the CPU registers need to exist in it too.
        self.bootrom_data, self.bootrom_rolen = make_bootloader()
        self.bootrom_len = len(self.bootrom_data)
        max_len = 256
        if self.bootrom_len > max_len:
            raise ValueError(
                "bootrom length {} is over max of {} by {} words".format(
                    self.bootrom_len, max_len, self.bootrom_len-max_len))

        # the main CPU. configured to start in the boot ROM.
        self.cpu_core = CoreFSM(alsru_cls=ALSRU_4LUT,
            reset_pc=0xFF00, reset_w=0xFFF8)
        # the boot ROM, which holds the bootloader.
        self.bootrom = Memory(width=16, depth=max_len, init=self.bootrom_data)

        # the UART peripheral. it runs at a fixed 2 megabaud so we can stream
        # ultra fast TASes in without a problem.
        self.uart = uart.SysUART(divisor=uart.calculate_divisor(12e6, 2000000))

    def elaborate(self, platform):
        m = Module()
        m.submodules.cpu_core = cpu_core = self.cpu_core
        m.submodules.bootrom_r = bootrom_r = self.bootrom.read_port(
            transparent=False)
        m.submodules.bootrom_w = bootrom_w = self.bootrom.write_port()

        m.submodules.uart = uart = self.uart

        # hook up main bus. the main RAM gets the first half and the boot ROM
        # gets the second (though nominally, it's from 0xFF00 to 0xFFFF)
        mainram_en = Signal()
        bootrom_en = Signal()
        # the area of the boot ROM with code can't be written to to avoid
        # destroying it by accident
        bootrom_writable = Signal()
        m.d.comb += [
            mainram_en.eq(cpu_core.o_bus_addr[-1] == 0),
            bootrom_en.eq(cpu_core.o_bus_addr[-1] == 1),
            bootrom_writable.eq(
                (cpu_core.o_bus_addr & 0xFF) >= self.bootrom_rolen)
        ]
        # wire the main bus to the memories
        m.d.comb += [
            # address bus
            bootrom_r.addr.eq(cpu_core.o_bus_addr),
            bootrom_w.addr.eq(cpu_core.o_bus_addr),
            self.memory_signals.o_addr.eq(cpu_core.o_bus_addr),
            # write data
            bootrom_w.data.eq(cpu_core.o_mem_data),
            self.memory_signals.o_wdata.eq(cpu_core.o_mem_data),
            # enables
            bootrom_r.en.eq(bootrom_en & cpu_core.o_mem_re),
            bootrom_w.en.eq(bootrom_en & cpu_core.o_mem_we & bootrom_writable),
            self.memory_signals.o_re.eq(mainram_en & cpu_core.o_mem_re),
            self.memory_signals.o_we.eq(mainram_en & cpu_core.o_mem_we),
        ]
        # mux read results back to the cpu bus. the cpu gets the read value if
        # it addressed the memory last cycle. it can only address one memory at
        # a time (if it did more then all the results would be ORed together).
        mainram_rdata = Signal(16)
        bootrom_rdata = Signal(16)
        m.d.comb += [
            mainram_rdata.eq(Mux(Past(mainram_en),
                self.memory_signals.i_rdata, 0)),
            bootrom_rdata.eq(Mux(Past(bootrom_en), bootrom_r.data, 0)),

            cpu_core.i_mem_data.eq(mainram_rdata | bootrom_rdata),
        ]
        # the main RAM runs with the system clock
        m.d.comb += [
            self.memory_signals.o_clock.eq(ClockSignal("sync")),
            self.memory_signals.o_reset.eq(ResetSignal("sync")),
        ]

        # split up the external bus into (at most) 16 regions of 16 registers.
        # we use the first 128 words and last 128 words of the bus since those
        # regions can be addressed with the 1-word form of the external bus
        # instructions. each peripheral gets 1 read and 1 write enable bit, 4
        # address bits, 16 write data bits, and gives back 16 read data bits
        NUM_PERIPHS = 1
        periph_en = tuple(Signal(1) for _ in range(NUM_PERIPHS))
        periph_re = tuple(Signal(1) for _ in range(NUM_PERIPHS))
        periph_we = tuple(Signal(1) for _ in range(NUM_PERIPHS))
        periph_addr = Signal(4)
        periph_wdata = Signal(16)
        periph_rdata = tuple(Signal(16) for _ in range(NUM_PERIPHS))

        m.d.comb += periph_addr.eq(cpu_core.o_bus_addr[:4])
        m.d.comb += periph_wdata.eq(cpu_core.o_ext_data)
        # hook up enable bits
        x_addr = cpu_core.o_bus_addr
        for pi in range(NUM_PERIPHS):
            m.d.comb += [
                periph_en[pi].eq(
                    (x_addr[-1] == (pi >> 3)) & (x_addr[4:7] == (pi & 7))),

                periph_re[pi].eq(cpu_core.o_ext_re & periph_en[pi]),
                periph_we[pi].eq(cpu_core.o_ext_we & periph_en[pi]),
            ]

        # mux peripheral read data back to the CPU
        result_expr = Const(0, 16)
        for pi in range(NUM_PERIPHS):
            # this peripheral gets to put its result on the bus if it was
            # addressed last cycle
            result_expr = result_expr | \
                Mux(Past(periph_en[pi]), periph_rdata[pi], 0)
        m.d.comb += cpu_core.i_ext_data.eq(result_expr)

        # hook up UART as peripheral zero
        uart_periph_num = 0
        m.d.comb += [
            uart.i_re.eq(periph_re[uart_periph_num]),
            uart.i_we.eq(periph_we[uart_periph_num]),
            uart.i_addr.eq(periph_addr),
            uart.i_wdata.eq(periph_wdata),
            periph_rdata[uart_periph_num].eq(uart.o_rdata),

            uart.i_rx.eq(self.uart_signals.i_rx),
            self.uart_signals.o_tx.eq(uart.o_tx),
        ]

        return m

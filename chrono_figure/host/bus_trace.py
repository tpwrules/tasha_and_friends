import time
import sys

from chrono_figure.host.interface import *

TRACE_PROGRAM = ev_assemble([
    L("start", org=1),
    POKE(SplW.MATCH_BUS_TRACE, 0), # ensure tracing is stopped
    # number of trace events we can queue before the buffers fill up
    POKE(SplW.IMM_B0, 270),
    POKE(SplW.IMM_B1, 1),
    COPY(1, SplR.IMM_VAL),
    POKE(SplW.MOFF_WR_TEMP, 1), # copy to counter
    MODIFY(1, Mod.COPY),
    POKE(SplW.MATCH_ENABLE, 1), # start matching
    COPY(SplW.MATCH_BUS_TRACE, 1), # and tracing
    BRANCH(0),

    L("trace_event_handler", org=508),
    COPY(0, SplR.MATCH_CYCLE_COUNT), # send off trace data
    COPY(SplW.EVENT_FIFO, 0),
    COPY(0, SplR.MATCH_ADDR),
    COPY(SplW.EVENT_FIFO, 0),
    MODIFY(2, Mod.DEC), # process the next event if we haven't finished this run
    BRANCH(0, Cond.NZ),
    POKE(SplW.MOFF_WR_TEMP, 1), # reset counter
    MODIFY(1, Mod.COPY),
    L("not_empty"), # wait for event FIFO to empty before restarting tracing
    COPY(3, SplR.EVENT_FIFO_STATUS),
    MODIFY(3, Mod.TEST_LSB),
    BRANCH("not_empty", Cond.Z),
    # now we can restart tracing and ensure we have room to put the results
    COPY(SplW.MATCH_BUS_TRACE, 1),
    BRANCH(0),
])

if len(sys.argv) != 2:
    print("args: vcd_out")
    exit(1)

# name, id, start bit, number of bits
vcd_vars = [
    # bus clock signal, not synchronous to anything?
    ("clock", "a", 11, 1),
    # bus A address
    ("addr", "b", 32, 24),
    # bus A read, active low
    ("rd", "c", 12, 1),
    # bus A write, active low
    ("wr", "d", 13, 1),
    # bus B address
    ("periph_addr", "e", 16, 8),
    # bus B read, active low
    ("pard", "f", 14, 1),
    # bus B write, active low
    ("pawr", "g", 15, 1),
    # bus data
    ("data", "h", 24, 8),
    # trace start: set high on first cycle of new trace
    ("start", "i", 56, 1),
]

vcd = open(sys.argv[1], "w")
vcd.write("""$comment
hello
$end
$timescale 1ns $end
$scope module test $end
""")
for name, vid, start_bit, bits in vcd_vars:
    vcd.write("$var wire {} {} {} $end\n".format(bits, vid, name))
vcd.write("""$upscope $end
$enddefinitions $end
$dumpvars
""")
for name, vid, start_bit, bits in vcd_vars:
    vcd.write("b0 {}\n".format(vid))
vcd.write("$end\n")

print("chrono figure setup...")
# connect to and set up chrono figure
cf = ChronoFigureInterface()
cf.connect()
# stop saves so our weirdness doesn't screw with the user's saves
cf.prevent_saving(True)
# trigger match 1 for each trace address
cf.configure_matchers([])
cf.assert_reset(True)
# erase save memory to ensure a clean start
cf.destroy_save_ram()
# start the tracing program
cf.exec_program(TRACE_PROGRAM)
# and let the console run
cf.assert_reset(False)

events = []
vcd_time = 1
print("capturing events")
last_cycle = -1
while True:
    events.extend(cf.read_event_fifo())
    while len(events) >= 2:
        a, b = events[:2]
        events = events[2:]
        d = a | (b << 32)
        c = a & 0x3FF
        d |= ((c != (last_cycle+1)&0x3FF) << 56)
        last_cycle = c
        vcd.write("#{}\n".format(vcd_time))
        for name, vid, start_bit, bits in vcd_vars:
            val = (d >> start_bit) & ((1<<bits)-1)
            vcd.write("{} {}\n".format(bin(val)[1:], vid))
        vcd_time += 1
    time.sleep(0.01)

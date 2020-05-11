set_global_assignment -entity "ip_apu_pll" -library "lib_ip_apu_pll" -name IP_TOOL_NAME "altera_pll"
set_global_assignment -entity "ip_apu_pll" -library "lib_ip_apu_pll" -name IP_TOOL_VERSION "19.1"
set_global_assignment -entity "ip_apu_pll" -library "lib_ip_apu_pll" -name IP_TOOL_ENV "mwpim"
set_global_assignment -library "lib_ip_apu_pll" -name SPD_FILE [file join $::quartus(sip_path) "ip_apu_pll.spd"]

set_global_assignment -library "lib_ip_apu_pll" -name MISC_FILE [file join $::quartus(sip_path) "ip_apu_pll_sim/ip_apu_pll.vo"]

set_global_assignment -entity "ip_sys_pll" -library "lib_ip_sys_pll" -name IP_TOOL_NAME "altera_pll"
set_global_assignment -entity "ip_sys_pll" -library "lib_ip_sys_pll" -name IP_TOOL_VERSION "19.1"
set_global_assignment -entity "ip_sys_pll" -library "lib_ip_sys_pll" -name IP_TOOL_ENV "mwpim"
set_global_assignment -library "lib_ip_sys_pll" -name SPD_FILE [file join $::quartus(sip_path) "ip_sys_pll.spd"]

set_global_assignment -library "lib_ip_sys_pll" -name MISC_FILE [file join $::quartus(sip_path) "ip_sys_pll_sim/ip_sys_pll.vo"]

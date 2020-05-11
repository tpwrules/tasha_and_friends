// ============================================================================
// Copyright (c) 2013 by Terasic Technologies Inc.
// ============================================================================
//
// Permission:
//
//   Terasic grants permission to use and modify this code for use
//   in synthesis for all Terasic Development Boards and Altera Development 
//   Kits made by Terasic.  Other use of this code, including the selling 
//   ,duplication, or modification of any portion is strictly prohibited.
//
// Disclaimer:
//
//   This VHDL/Verilog or C/C++ source code is intended as a design reference
//   which illustrates how these types of functions can be implemented.
//   It is the user's responsibility to verify their design for
//   consistency and functionality through the use of formal
//   verification methods.  Terasic provides no warranty regarding the use 
//   or functionality of this code.
//
// ============================================================================
//           
//  Terasic Technologies Inc
//  9F., No.176, Sec.2, Gongdao 5th Rd, East Dist, Hsinchu City, 30070. Taiwan
//  
//  
//                     web: http://www.terasic.com/  
//                     email: support@terasic.com
//
// ============================================================================
//Date:  Tue Jun  4 20:41:15 2013
// ============================================================================


module tasha_c5g(

/*
      ///////// ADC /////////
      output             ADC_CONVST,
      output             ADC_SCK,
      output             ADC_SDI,
      input              ADC_SDO,
*/
/*
      ///////// AUD /////////
      input              AUD_ADCDAT,
      inout              AUD_ADCLRCK,
      inout              AUD_BCLK,
      output             AUD_DACDAT,
      inout              AUD_DACLRCK,
      output             AUD_XCK,
*/
      ///////// CLOCK /////////
      input              CLOCK_125_p,
      input              CLOCK_50_B5B,
      input              CLOCK_50_B6A,
      input              CLOCK_50_B7A,
      input              CLOCK_50_B8A,

      ///////// CPU /////////
      input              CPU_RESET_n,

/*
      ///////// DDR2LP /////////
      output      [9:0]  DDR2LP_CA,
      output      [1:0]  DDR2LP_CKE,
      output             DDR2LP_CK_n,
      output             DDR2LP_CK_p,
      output      [1:0]  DDR2LP_CS_n,
      output      [3:0]  DDR2LP_DM,
      inout       [31:0] DDR2LP_DQ,
      inout       [3:0]  DDR2LP_DQS_n,
      inout       [3:0]  DDR2LP_DQS_p,
      input              DDR2LP_OCT_RZQ,
*/


      ///////// GPIO /////////
      inout       [35:0] GPIO,
/*
      ///////// HEX2 /////////
      output      [6:0]  HEX2,

      ///////// HEX3 /////////
      output      [6:0]  HEX3,            
*/
/*
      ///////// HDMI /////////
      output             HDMI_TX_CLK,
      output      [23:0] HDMI_TX_D,
      output             HDMI_TX_DE,
      output             HDMI_TX_HS,
      input              HDMI_TX_INT,
      output             HDMI_TX_VS,
*/
/*
      ///////// HEX0 /////////
      output      [6:0]  HEX0,

      ///////// HEX1 /////////
      output      [6:0]  HEX1,
*/
/*
      ///////// HSMC /////////
      input              HSMC_CLKIN0,
      input       [2:1]  HSMC_CLKIN_n,
      input       [2:1]  HSMC_CLKIN_p,
      output             HSMC_CLKOUT0,
      output      [2:1]  HSMC_CLKOUT_n,
      output      [2:1]  HSMC_CLKOUT_p,
      inout       [3:0]  HSMC_D,
      input       [3:0]  HSMC_GXB_RX_p,
      output      [3:0]  HSMC_GXB_TX_p,         
      inout       [16:0] HSMC_RX_n,
      inout       [16:0] HSMC_RX_p,
      inout       [16:0] HSMC_TX_n,
      inout       [16:0] HSMC_TX_p,
*/
/*
      ///////// I2C /////////
      output             I2C_SCL,
      inout              I2C_SDA,
*/
/*
      ///////// KEY /////////
      input       [3:0]  KEY,
*/
/*
      ///////// LEDG /////////
      output      [7:0]  LEDG,
*/
/*
      ///////// LEDR /////////
      output      [9:0]  LEDR,
*/
/*
      ///////// REFCLK /////////
      input              REFCLK_p0,
      input              REFCLK_p1,
*/
/*
      ///////// SD /////////
      output             SD_CLK,
      inout              SD_CMD,
      inout       [3:0]  SD_DAT,
*/
/*
      ///////// SMA /////////
      input              SMA_GXB_RX_p,
      output             SMA_GXB_TX_p,
*/
/*
      ///////// SRAM /////////
      output      [17:0] SRAM_A,
      output             SRAM_CE_n,
      inout       [15:0] SRAM_D,
      output             SRAM_LB_n,
      output             SRAM_OE_n,
      output             SRAM_UB_n,
      output             SRAM_WE_n,
*/
/*
      ///////// SW /////////
      input       [9:0]  SW,
*/
      ///////// UART /////////
      input              UART_RX,
      output             UART_TX


);

wire sys_clk_12;
wire apu_clk_24p75;

wire sys_pll_locked;
wire apu_pll_locked;
wire pll_locked = sys_pll_locked & apu_pll_locked;

ip_sys_pll ip_sys_pll(
      .rst(1'b0),
      .refclk(CLOCK_50_B5B),
      .outclk_0(sys_clk_12),
      .locked(sys_pll_locked),
);

ip_apu_pll ip_apu_pll(
      .rst(1'b0),
      .refclk(CLOCK_50_B6A),
      .outclk_0(apu_clk_24p75),
      .locked(apu_pll_locked),
);

wire mem_clock;
wire mem_reset;
wire [14:0] mem_addr;
wire mem_re;
wire [15:0] mem_rdata;
wire mem_we;
wire [15:0] mem_wdata;

ip_main_ram ip_main_ram(
      .address(mem_addr),
      .clock(mem_clock),
      .data(mem_wdata),
      .wren(mem_we),
      .q(mem_rdata),
);

wire apu_ddr_clk;
wire apu_ddr_lo;
wire apu_ddr_hi;

tasha_sys_c5g tasha_sys_c5g(
      .i_reset(~CPU_RESET_n | ~pll_locked), // active high!
      .i_sys_clk_12(sys_clk_12),
      .i_apu_clk_24p75(apu_clk_24p75),

      .i_latch(GPIO[15]),
      .i_p1clk(GPIO[17]),
      .i_p2clk(GPIO[19]),

      .o_p1d0(GPIO[14]),
      .o_p1d1(GPIO[16]),
      .o_p2d0(GPIO[18]),
      .o_p2d1(GPIO[20]),

      .o_apu_ddr_clk(apu_ddr_clk),
      .o_apu_ddr_lo(apu_ddr_lo),
      .o_apu_ddr_hi(apu_ddr_hi),

      .i_rx(UART_RX),
      .o_tx(UART_TX),

      .o_mem_clock(mem_clock),
      .o_mem_reset(mem_reset),

      .o_addr(mem_addr),
      .o_re(mem_re),
      .i_rdata(mem_rdata),
      .o_we(mem_we),
      .o_wdata(mem_wdata)
);

ip_ddrclk driver_0(
      .datain_h(apu_ddr_hi),
      .datain_l(apu_ddr_lo),
      .outclock(apu_ddr_clk),
      .dataout(GPIO[8]),
);
ip_ddrclk driver_1(
      .datain_h(apu_ddr_hi),
      .datain_l(apu_ddr_lo),
      .outclock(apu_ddr_clk),
      .dataout(GPIO[9]),
);
ip_ddrclk driver_2(
      .datain_h(apu_ddr_hi),
      .datain_l(apu_ddr_lo),
      .outclock(apu_ddr_clk),
      .dataout(GPIO[10]),
);
ip_ddrclk driver_3(
      .datain_h(apu_ddr_hi),
      .datain_l(apu_ddr_lo),
      .outclock(apu_ddr_clk),
      .dataout(GPIO[11]),
);

endmodule

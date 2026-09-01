///////////////////////////////////////////
//
// RISC-V Architectural Functional Coverage Covergroups
//
// Written: David Harris david_harris@hmc.edu 29 August 2026
//
// Copyright (C) 2026 Harvey Mudd College, 10x Engineers, UET Lahore, Habib University
//
// SPDX-License-Identifier: Apache-2.0
//
////////////////////////////////////////////////////////////////////////////////////////////////

`define COVER_INTERRUPTSSM

// Interrupt observation helpers (shared by the Interrupts* covergroups; defined once here).
// The reference trace has no trap entries, so a taken interrupt is recognized at the first
// instruction of the M-mode or S-mode trap handler (csrrw sp, xscratch, sp) using the post-trap
// xcause/xstatus, and an interrupt that stays pending is recognized at the coverage sample point
// the generated tests place after waiting (addi x0, x0, 1).
`ifndef INTERRUPTS_COVERAGE_HELPERS
`define INTERRUPTS_COVERAGE_HELPERS
function automatic bit intr_m_entry(ins_t ins);
  return ins.current.insn == 32'h34011173; // csrrw sp, mscratch, sp
endfunction
function automatic bit intr_s_entry(ins_t ins);
  return ins.current.insn == 32'h14011173; // csrrw sp, sscratch, sp
endfunction
function automatic bit intr_mark(ins_t ins);
  return ins.current.insn == 32'h00100013; // addi x0, x0, 1
endfunction
// interrupt with this cause was just taken into M-mode or S-mode
function automatic bit intr_taken(ins_t ins, int cause);
  if (intr_m_entry(ins))
    return ins.current.csr[CSR_MCAUSE][`UDB_MXLEN-1] & (ins.current.csr[CSR_MCAUSE][5:0] == cause);
  if (intr_s_entry(ins))
    return ins.current.csr[CSR_SCAUSE][`UDB_MXLEN-1] & (ins.current.csr[CSR_SCAUSE][5:0] == cause);
  return 0;
endfunction
// interrupt with this cause was taken, or is still pending at the sample point
function automatic bit intr_observed(ins_t ins, int cause);
  return intr_taken(ins, cause) | (intr_mark(ins) & ins.current.csr[CSR_MIP][cause]);
endfunction
// privilege mode the interrupt was raised in (xPP of the handler, else the current mode)
function automatic int intr_mode(ins_t ins);
  if (intr_m_entry(ins)) return ins.current.csr[CSR_MSTATUS][12:11];
  if (intr_s_entry(ins)) return ins.current.csr[CSR_MSTATUS][8] ? 1 : 0;
  return ins.prev.mode;
endfunction
// mstatus.MIE / sstatus.SIE at the time the interrupt was raised (xPIE inside the handler)
function automatic bit intr_mie(ins_t ins);
  return intr_m_entry(ins) ? ins.current.csr[CSR_MSTATUS][7] : ins.current.csr[CSR_MSTATUS][3];
endfunction
function automatic bit intr_sie(ins_t ins);
  return intr_s_entry(ins) ? ins.current.csr[CSR_MSTATUS][5] : ins.current.csr[CSR_SSTATUS][1];
endfunction
// a retiring csrrs/csrrsi to csr after which bit cause is set: the pending bit was raised by a CSR write
function automatic bit intr_csr_set(ins_t ins, int csr, int cause);
  return (ins.current.insn[6:0] == 7'h73) && (ins.current.insn[14:12] inside {3'b010, 3'b110})
         && (ins.current.insn[31:20] == csr) && ins.current.csr[csr][cause];
endfunction
// mode the CSR write was issued from: a T-SBI access (rs1 = a1, rd = a0 or x0) runs in the M-mode handler for xPP
function automatic int intr_csr_mode(ins_t ins);
  if (ins.current.insn[19:15] == 5'd11) return ins.current.csr[CSR_MSTATUS][12:11];
  return ins.prev.mode;
endfunction
// the retiring csrrw that leaves stimecmp at zero (raises STI when menvcfg.STCE = 1); the tests write
// the low word first, so on RV32 the write to stimecmph is the one that arms the comparator
function automatic bit intr_stimecmp_zero(ins_t ins);
  `ifdef UDB_MXLEN_64
  return (ins.current.insn[6:0] == 7'h73) && (ins.current.insn[14:12] == 3'b001)
         && (ins.current.insn[31:20] == CSR_STIMECMP) && (ins.current.csr[CSR_STIMECMP] == 0);
  `else
  return (ins.current.insn[6:0] == 7'h73) && (ins.current.insn[14:12] == 3'b001)
         && (ins.current.insn[31:20] == CSR_STIMECMPH) && (ins.current.csr[CSR_STIMECMPH] == 0)
         && (ins.current.csr[CSR_STIMECMP] == 0);
  `endif
endfunction
function automatic bit intr_stce(ins_t ins);
  `ifdef UDB_MXLEN_64
  return ins.current.csr[CSR_MENVCFG][63];
  `else
  return ins.current.csr[CSR_MENVCFGH][31];
  `endif
endfunction
// some interrupt was just taken into M-mode or S-mode
function automatic bit intr_any_taken(ins_t ins);
  if (intr_m_entry(ins)) return ins.current.csr[CSR_MCAUSE][`UDB_MXLEN-1];
  if (intr_s_entry(ins)) return ins.current.csr[CSR_SCAUSE][`UDB_MXLEN-1];
  return 0;
endfunction
// every supported interrupt pending in mip (all of them / the supervisor-level ones)
function automatic bit intr_mip_ones(ins_t ins);
  bit ones = 1;
  `ifdef UDB_LCOFI_SUPPORTED
  ones &= ins.current.csr[CSR_MIP][13];
  `endif
  `ifdef UDB_MTI_SUPPORTED
  ones &= ins.current.csr[CSR_MIP][7];
  `endif
  `ifdef UDB_MSI_SUPPORTED
  ones &= ins.current.csr[CSR_MIP][3];
  `endif
  `ifdef UDB_MEI_SUPPORTED
  ones &= ins.current.csr[CSR_MIP][11];
  `endif
  `ifdef UDB_STI_SUPPORTED
  ones &= ins.current.csr[CSR_MIP][5];
  `endif
  `ifdef UDB_SSI_SUPPORTED
  ones &= ins.current.csr[CSR_MIP][1];
  `endif
  `ifdef UDB_SEI_SUPPORTED
  ones &= ins.current.csr[CSR_MIP][9];
  `endif
  return ones;
endfunction
function automatic bit intr_sip_ones(ins_t ins);
  bit ones = 1;
  `ifdef UDB_LCOFI_SUPPORTED
  ones &= ins.current.csr[CSR_MIP][13];
  `endif
  `ifdef UDB_STI_SUPPORTED
  ones &= ins.current.csr[CSR_MIP][5];
  `endif
  `ifdef UDB_SSI_SUPPORTED
  ones &= ins.current.csr[CSR_MIP][1];
  `endif
  `ifdef UDB_SEI_SUPPORTED
  ones &= ins.current.csr[CSR_MIP][9];
  `endif
  return ones;
endfunction
// WFI with mstatus.TW = 1 timed out: an illegal-instruction trap whose xtval is the WFI encoding
function automatic bit intr_wfi_timeout(ins_t ins);
  if (intr_m_entry(ins)) return (ins.current.csr[CSR_MCAUSE] == 2) && (ins.current.csr[CSR_MTVAL] == 32'h10500073);
  if (intr_s_entry(ins)) return (ins.current.csr[CSR_SCAUSE] == 2) && (ins.current.csr[CSR_STVAL] == 32'h10500073);
  return 0;
endfunction
// every supported interrupt enable bit set in xie
function automatic bit intr_mie_ones(ins_t ins);
  bit ones = 1;
  `ifdef UDB_LCOFI_SUPPORTED
  ones &= ins.current.csr[CSR_MIE][13];
  `endif
  `ifdef UDB_MTI_SUPPORTED
  ones &= ins.current.csr[CSR_MIE][7];
  `endif
  `ifdef UDB_MSI_SUPPORTED
  ones &= ins.current.csr[CSR_MIE][3];
  `endif
  `ifdef UDB_MEI_SUPPORTED
  ones &= ins.current.csr[CSR_MIE][11];
  `endif
  `ifdef UDB_STI_SUPPORTED
  ones &= ins.current.csr[CSR_MIE][5];
  `endif
  `ifdef UDB_SSI_SUPPORTED
  ones &= ins.current.csr[CSR_MIE][1];
  `endif
  `ifdef UDB_SEI_SUPPORTED
  ones &= ins.current.csr[CSR_MIE][9];
  `endif
  return ones;
endfunction
function automatic bit intr_sie_ones(ins_t ins);
  bit ones = 1;
  `ifdef UDB_LCOFI_SUPPORTED
  ones &= ins.current.csr[CSR_SIE][13];
  `endif
  `ifdef UDB_STI_SUPPORTED
  ones &= ins.current.csr[CSR_SIE][5];
  `endif
  `ifdef UDB_SSI_SUPPORTED
  ones &= ins.current.csr[CSR_SIE][1];
  `endif
  `ifdef UDB_SEI_SUPPORTED
  ones &= ins.current.csr[CSR_SIE][9];
  `endif
  return ones;
endfunction
`endif // INTERRUPTS_COVERAGE_HELPERS

covergroup InterruptsSm_cg with function sample(ins_t ins);
    option.per_instance = 0;
    `include "general/RISCV_coverage_standard_coverpoints.svh"

    // context of the observed interrupt
    intr_priv_m: coverpoint intr_mode(ins) { bins M_mode = {3}; }
    intr_priv_s: coverpoint intr_mode(ins) { bins S_mode = {1}; }
    intr_priv_u: coverpoint intr_mode(ins) { bins U_mode = {0}; }
    mstatus_mie: coverpoint intr_mie(ins) { bins zero = {0}; bins one = {1}; }
    sstatus_sie: coverpoint intr_sie(ins) { bins zero = {0}; bins one = {1}; }
    // context of a CSR write that raises a pending bit (cp_trigger_reg)
    csr_priv_m: coverpoint intr_csr_mode(ins) { bins M_mode = {3}; }
    csr_priv_s: coverpoint intr_csr_mode(ins) { bins S_mode = {1}; }
    csr_priv_u: coverpoint intr_csr_mode(ins) { bins U_mode = {0}; }
    csr_mstatus_mie: coverpoint ins.prev.csr[CSR_MSTATUS][3] { bins zero = {0}; bins one = {1}; }
    csr_sstatus_sie: coverpoint ins.prev.csr[CSR_SSTATUS][1] { bins zero = {0}; bins one = {1}; }
`ifdef S_SUPPORTED
`ifdef UDB_SSI_SUPPORTED
    mip_ssip_set: coverpoint intr_csr_set(ins, CSR_MIP, 1) { bins set = {1}; }
    sip_ssip_set: coverpoint intr_csr_set(ins, CSR_SIP, 1) { bins set = {1}; }
    mideleg_ssi_one: coverpoint ins.current.csr[CSR_MIDELEG][1] { bins one = {1}; }
`endif
`ifdef UDB_SEI_SUPPORTED
    mip_seip_set: coverpoint intr_csr_set(ins, CSR_MIP, 9) { bins set = {1}; }
`endif
    // cp_enable: a single supported enable bit set in xie
    mie_walk: coverpoint ins.current.csr[CSR_MIE][15:0] {
        `ifdef UDB_LCOFI_SUPPORTED
        bins lcofi = {16'h2000};
        `endif
        `ifdef UDB_MTI_SUPPORTED
        bins mti = {16'h0080};
        `endif
        `ifdef UDB_MSI_SUPPORTED
        bins msi = {16'h0008};
        `endif
        `ifdef UDB_MEI_SUPPORTED
        bins mei = {16'h0800};
        `endif
        `ifdef UDB_STI_SUPPORTED
        bins sti = {16'h0020};
        `endif
        `ifdef UDB_SSI_SUPPORTED
        bins ssi = {16'h0002};
        `endif
        `ifdef UDB_SEI_SUPPORTED
        bins sei = {16'h0200};
        `endif
    }
    sie_walk: coverpoint ins.current.csr[CSR_SIE][15:0] {
        `ifdef UDB_LCOFI_SUPPORTED
        bins lcofi = {16'h2000};
        `endif
        `ifdef UDB_STI_SUPPORTED
        bins sti = {16'h0020};
        `endif
        `ifdef UDB_SSI_SUPPORTED
        bins ssi = {16'h0002};
        `endif
        `ifdef UDB_SEI_SUPPORTED
        bins sei = {16'h0200};
        `endif
    }
`ifdef SSTC_SUPPORTED
    // cp_trigger_sti_sstc: the stimecmp = 0 write and menvcfg.STCE at that time
    stimecmp_zero: coverpoint intr_stimecmp_zero(ins) { bins written = {1}; }
    menvcfg_stce:  coverpoint intr_stce(ins) { bins zero = {0}; bins one = {1}; }
    menvcfg_stce_one: coverpoint intr_stce(ins) { bins one = {1}; }
`endif
`endif
    mie_ones:    coverpoint intr_mie_ones(ins) { bins ones = {1}; }
    mtvec_mode: coverpoint ins.current.csr[CSR_MTVEC][1:0] {
        `ifdef UDB_MTVEC_MODES_0
        bins direct = {0};
        `endif
        `ifdef UDB_MTVEC_MODES_1
        bins vector = {1};
        `endif
    }
    stvec_mode: coverpoint ins.current.csr[CSR_STVEC][1:0] {
        `ifdef UDB_STVEC_MODES_0
        bins direct = {0};
        `endif
        `ifdef UDB_STVEC_MODES_1
        bins vector = {1};
        `endif
    }

    // cp_priority_*: pairs of pending / enabled interrupts, sampled when the first of them is taken
    any_taken: coverpoint intr_any_taken(ins) { bins taken = {1}; }
    mip_ones: coverpoint intr_mip_ones(ins) { bins ones = {1}; }
    xip_pair: coverpoint (ins.current.csr[CSR_MIP][15:0] & 16'h2AAA) {
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_MSI_SUPPORTED
        bins ssi_msi = {16'h000a};
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_STI_SUPPORTED
        bins ssi_sti = {16'h0022};
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_MTI_SUPPORTED
        bins ssi_mti = {16'h0082};
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        bins ssi_sei = {16'h0202};
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        bins ssi_mei = {16'h0802};
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins ssi_lcofi = {16'h2002};
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_STI_SUPPORTED
        bins msi_sti = {16'h0028};
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_MTI_SUPPORTED
        bins msi_mti = {16'h0088};
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        bins msi_sei = {16'h0208};
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        bins msi_mei = {16'h0808};
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins msi_lcofi = {16'h2008};
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_MTI_SUPPORTED
        bins sti_mti = {16'h00a0};
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        bins sti_sei = {16'h0220};
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        bins sti_mei = {16'h0820};
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins sti_lcofi = {16'h2020};
        `endif
        `endif
        `ifdef UDB_MTI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        bins mti_sei = {16'h0280};
        `endif
        `endif
        `ifdef UDB_MTI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        bins mti_mei = {16'h0880};
        `endif
        `endif
        `ifdef UDB_MTI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins mti_lcofi = {16'h2080};
        `endif
        `endif
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        `ifndef RVMODEL_SEXT_MEXT_SHARED_SOURCE
        bins sei_mei = {16'h0a00};
        `endif
        `endif
        `endif
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins sei_lcofi = {16'h2200};
        `endif
        `endif
        `ifdef UDB_MEI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins mei_lcofi = {16'h2800};
        `endif
        `endif
    }
    xie_pair: coverpoint (ins.current.csr[CSR_MIE][15:0] & 16'h2AAA) {
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_MSI_SUPPORTED
        bins ssi_msi = {16'h000a};
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_STI_SUPPORTED
        bins ssi_sti = {16'h0022};
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_MTI_SUPPORTED
        bins ssi_mti = {16'h0082};
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        bins ssi_sei = {16'h0202};
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        bins ssi_mei = {16'h0802};
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins ssi_lcofi = {16'h2002};
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_STI_SUPPORTED
        bins msi_sti = {16'h0028};
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_MTI_SUPPORTED
        bins msi_mti = {16'h0088};
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        bins msi_sei = {16'h0208};
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        bins msi_mei = {16'h0808};
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins msi_lcofi = {16'h2008};
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_MTI_SUPPORTED
        bins sti_mti = {16'h00a0};
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        bins sti_sei = {16'h0220};
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        bins sti_mei = {16'h0820};
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins sti_lcofi = {16'h2020};
        `endif
        `endif
        `ifdef UDB_MTI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        bins mti_sei = {16'h0280};
        `endif
        `endif
        `ifdef UDB_MTI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        bins mti_mei = {16'h0880};
        `endif
        `endif
        `ifdef UDB_MTI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins mti_lcofi = {16'h2080};
        `endif
        `endif
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        `ifndef RVMODEL_SEXT_MEXT_SHARED_SOURCE
        bins sei_mei = {16'h0a00};
        `endif
        `endif
        `endif
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins sei_lcofi = {16'h2200};
        `endif
        `endif
        `ifdef UDB_MEI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        bins mei_lcofi = {16'h2800};
        `endif
        `endif
    }
    xip_pair_deleg: coverpoint {ins.current.csr[CSR_MIP][15:0] & 16'h2AAA, ins.current.csr[CSR_MIDELEG][15:0] & 16'h2AAA} {
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_SSI_DELEGATION_SUPPORTED
        bins ssi_msi_deleg_ssi = {32'h000a0002};
        `endif
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_SSI_DELEGATION_SUPPORTED
        bins ssi_sti_deleg_ssi = {32'h00220002};
        `endif
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_STI_DELEGATION_SUPPORTED
        bins ssi_sti_deleg_sti = {32'h00220020};
        `endif
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_MTI_SUPPORTED
        `ifdef UDB_SSI_DELEGATION_SUPPORTED
        bins ssi_mti_deleg_ssi = {32'h00820002};
        `endif
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_SSI_DELEGATION_SUPPORTED
        bins ssi_sei_deleg_ssi = {32'h02020002};
        `endif
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_SEI_DELEGATION_SUPPORTED
        bins ssi_sei_deleg_sei = {32'h02020200};
        `endif
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        `ifdef UDB_SSI_DELEGATION_SUPPORTED
        bins ssi_mei_deleg_ssi = {32'h08020002};
        `endif
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        `ifdef UDB_SSI_DELEGATION_SUPPORTED
        bins ssi_lcofi_deleg_ssi = {32'h20020002};
        `endif
        `endif
        `endif
        `ifdef UDB_SSI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        `ifdef UDB_LCOFI_DELEGATION_SUPPORTED
        bins ssi_lcofi_deleg_lcofi = {32'h20022000};
        `endif
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_STI_DELEGATION_SUPPORTED
        bins msi_sti_deleg_sti = {32'h00280020};
        `endif
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_SEI_DELEGATION_SUPPORTED
        bins msi_sei_deleg_sei = {32'h02080200};
        `endif
        `endif
        `endif
        `ifdef UDB_MSI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        `ifdef UDB_LCOFI_DELEGATION_SUPPORTED
        bins msi_lcofi_deleg_lcofi = {32'h20082000};
        `endif
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_MTI_SUPPORTED
        `ifdef UDB_STI_DELEGATION_SUPPORTED
        bins sti_mti_deleg_sti = {32'h00a00020};
        `endif
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_STI_DELEGATION_SUPPORTED
        bins sti_sei_deleg_sti = {32'h02200020};
        `endif
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_SEI_DELEGATION_SUPPORTED
        bins sti_sei_deleg_sei = {32'h02200200};
        `endif
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        `ifdef UDB_STI_DELEGATION_SUPPORTED
        bins sti_mei_deleg_sti = {32'h08200020};
        `endif
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        `ifdef UDB_STI_DELEGATION_SUPPORTED
        bins sti_lcofi_deleg_sti = {32'h20200020};
        `endif
        `endif
        `endif
        `ifdef UDB_STI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        `ifdef UDB_LCOFI_DELEGATION_SUPPORTED
        bins sti_lcofi_deleg_lcofi = {32'h20202000};
        `endif
        `endif
        `endif
        `ifdef UDB_MTI_SUPPORTED
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_SEI_DELEGATION_SUPPORTED
        bins mti_sei_deleg_sei = {32'h02800200};
        `endif
        `endif
        `endif
        `ifdef UDB_MTI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        `ifdef UDB_LCOFI_DELEGATION_SUPPORTED
        bins mti_lcofi_deleg_lcofi = {32'h20802000};
        `endif
        `endif
        `endif
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_MEI_SUPPORTED
        `ifdef UDB_SEI_DELEGATION_SUPPORTED
        `ifndef RVMODEL_SEXT_MEXT_SHARED_SOURCE
        bins sei_mei_deleg_sei = {32'h0a000200};
        `endif
        `endif
        `endif
        `endif
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        `ifdef UDB_SEI_DELEGATION_SUPPORTED
        bins sei_lcofi_deleg_sei = {32'h22000200};
        `endif
        `endif
        `endif
        `ifdef UDB_SEI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        `ifdef UDB_LCOFI_DELEGATION_SUPPORTED
        bins sei_lcofi_deleg_lcofi = {32'h22002000};
        `endif
        `endif
        `endif
        `ifdef UDB_MEI_SUPPORTED
        `ifdef UDB_LCOFI_SUPPORTED
        `ifdef UDB_LCOFI_DELEGATION_SUPPORTED
        bins mei_lcofi_deleg_lcofi = {32'h28002000};
        `endif
        `endif
        `endif
    }

    // cp_wfi / cp_wfi_timeout
    wfi: coverpoint ins.current.insn { bins wfi = {32'h10500073}; }
    wfi_timeout: coverpoint intr_wfi_timeout(ins) { bins taken = {1}; }
    mstatus_tw: coverpoint ins.current.csr[CSR_MSTATUS][21] { bins zero = {0}; bins one = {1}; }
    mstatus_tw_zero: coverpoint ins.current.csr[CSR_MSTATUS][21] { bins zero = {0}; }
    mstatus_tw_one: coverpoint ins.current.csr[CSR_MSTATUS][21] { bins one = {1}; }
    mie_mtie: coverpoint ins.current.csr[CSR_MIE][7] { bins zero = {0}; bins one = {1}; }
    mie_mtie_one: coverpoint ins.current.csr[CSR_MIE][7] { bins one = {1}; }

    // per-interrupt building blocks
`ifdef UDB_LCOFI_SUPPORTED
`ifdef S_SUPPORTED
    mideleg_lcofi: coverpoint ins.current.csr[CSR_MIDELEG][13] { bins zero = {0}; `ifdef UDB_LCOFI_DELEGATION_SUPPORTED bins one = {1}; `endif }
    lcofi_observed: coverpoint intr_observed(ins, 13) { bins observed = {1}; }
`endif
`endif
`ifdef UDB_MTI_SUPPORTED
    mideleg_mti: coverpoint ins.current.csr[CSR_MIDELEG][7] { bins zero = {0}; }
    mti_observed: coverpoint intr_observed(ins, 7) { bins observed = {1}; }
`endif
`ifdef UDB_MSI_SUPPORTED
    mideleg_msi: coverpoint ins.current.csr[CSR_MIDELEG][3] { bins zero = {0}; }
    msi_observed: coverpoint intr_observed(ins, 3) { bins observed = {1}; }
`endif
`ifdef UDB_MEI_SUPPORTED
    mideleg_mei: coverpoint ins.current.csr[CSR_MIDELEG][11] { bins zero = {0}; }
    mei_observed: coverpoint intr_observed(ins, 11) { bins observed = {1}; }
`endif
`ifdef UDB_STI_SUPPORTED
`ifdef S_SUPPORTED
    mideleg_sti: coverpoint ins.current.csr[CSR_MIDELEG][5] { bins zero = {0}; `ifdef UDB_STI_DELEGATION_SUPPORTED bins one = {1}; `endif }
    sti_observed: coverpoint intr_observed(ins, 5) { bins observed = {1}; }
`endif
`endif
`ifdef UDB_SSI_SUPPORTED
`ifdef S_SUPPORTED
    mideleg_ssi: coverpoint ins.current.csr[CSR_MIDELEG][1] { bins zero = {0}; `ifdef UDB_SSI_DELEGATION_SUPPORTED bins one = {1}; `endif }
    ssi_observed: coverpoint intr_observed(ins, 1) { bins observed = {1}; }
`endif
`endif
`ifdef UDB_SEI_SUPPORTED
`ifdef S_SUPPORTED
    mideleg_sei: coverpoint ins.current.csr[CSR_MIDELEG][9] { bins zero = {0}; `ifdef UDB_SEI_DELEGATION_SUPPORTED bins one = {1}; `endif }
    sei_observed: coverpoint intr_observed(ins, 9) { bins observed = {1}; }
`endif
`endif

    // cp_trigger: raise each interrupt from M, S, U mode
`ifdef UDB_LCOFI_SUPPORTED
`ifdef S_SUPPORTED
    cp_trigger_M_LCOFI: cross intr_priv_m, mstatus_mie, mideleg_lcofi, mie_ones, mtvec_mode, lcofi_observed;
`ifdef S_SUPPORTED
    cp_trigger_S_LCOFI: cross intr_priv_s, sstatus_sie, mideleg_lcofi, mie_ones, stvec_mode, lcofi_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_trigger_U_LCOFI: cross intr_priv_u, sstatus_sie, mideleg_lcofi, mie_ones, stvec_mode, lcofi_observed;
`endif
`endif
`endif
`endif
`ifdef UDB_MTI_SUPPORTED
    cp_trigger_M_MTI: cross intr_priv_m, mstatus_mie, mideleg_mti, mie_ones, mtvec_mode, mti_observed;
`ifdef S_SUPPORTED
    cp_trigger_S_MTI: cross intr_priv_s, sstatus_sie, mideleg_mti, mie_ones, stvec_mode, mti_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_trigger_U_MTI: cross intr_priv_u, sstatus_sie, mideleg_mti, mie_ones, stvec_mode, mti_observed;
`endif
`endif
`endif
`ifdef UDB_MSI_SUPPORTED
    cp_trigger_M_MSI: cross intr_priv_m, mstatus_mie, mideleg_msi, mie_ones, mtvec_mode, msi_observed;
`ifdef S_SUPPORTED
    cp_trigger_S_MSI: cross intr_priv_s, sstatus_sie, mideleg_msi, mie_ones, stvec_mode, msi_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_trigger_U_MSI: cross intr_priv_u, sstatus_sie, mideleg_msi, mie_ones, stvec_mode, msi_observed;
`endif
`endif
`endif
`ifdef UDB_MEI_SUPPORTED
    cp_trigger_M_MEI: cross intr_priv_m, mstatus_mie, mideleg_mei, mie_ones, mtvec_mode, mei_observed;
`ifdef S_SUPPORTED
    cp_trigger_S_MEI: cross intr_priv_s, sstatus_sie, mideleg_mei, mie_ones, stvec_mode, mei_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_trigger_U_MEI: cross intr_priv_u, sstatus_sie, mideleg_mei, mie_ones, stvec_mode, mei_observed;
`endif
`endif
`endif
`ifdef UDB_STI_SUPPORTED
`ifdef S_SUPPORTED
    cp_trigger_M_STI: cross intr_priv_m, mstatus_mie, mideleg_sti, mie_ones, mtvec_mode, sti_observed;
`ifdef S_SUPPORTED
    cp_trigger_S_STI: cross intr_priv_s, sstatus_sie, mideleg_sti, mie_ones, stvec_mode, sti_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_trigger_U_STI: cross intr_priv_u, sstatus_sie, mideleg_sti, mie_ones, stvec_mode, sti_observed;
`endif
`endif
`endif
`endif
`ifdef UDB_SSI_SUPPORTED
`ifdef S_SUPPORTED
    cp_trigger_M_SSI: cross intr_priv_m, mstatus_mie, mideleg_ssi, mie_ones, mtvec_mode, ssi_observed;
`ifdef S_SUPPORTED
    cp_trigger_S_SSI: cross intr_priv_s, sstatus_sie, mideleg_ssi, mie_ones, stvec_mode, ssi_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_trigger_U_SSI: cross intr_priv_u, sstatus_sie, mideleg_ssi, mie_ones, stvec_mode, ssi_observed;
`endif
`endif
`endif
`endif
`ifdef UDB_SEI_SUPPORTED
`ifdef S_SUPPORTED
    cp_trigger_M_SEI: cross intr_priv_m, mstatus_mie, mideleg_sei, mie_ones, mtvec_mode, sei_observed;
`ifdef S_SUPPORTED
    cp_trigger_S_SEI: cross intr_priv_s, sstatus_sie, mideleg_sei, mie_ones, stvec_mode, sei_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_trigger_U_SEI: cross intr_priv_u, sstatus_sie, mideleg_sei, mie_ones, stvec_mode, sei_observed;
`endif
`endif
`endif
`endif

    // cp_trigger_reg: raise SSI/SEI by writing the pending register (mip, or sip where accessible)
`ifdef S_SUPPORTED
`ifdef UDB_SSI_SUPPORTED
    cp_trigger_reg_M_SSI_mip: cross csr_priv_m, csr_mstatus_mie, mideleg_ssi, mie_ones, mtvec_mode, mip_ssip_set;
`endif
`ifdef UDB_SEI_SUPPORTED
    cp_trigger_reg_M_SEI_mip: cross csr_priv_m, csr_mstatus_mie, mideleg_sei, mie_ones, mtvec_mode, mip_seip_set;
`endif
`ifdef UDB_SSI_SUPPORTED
    cp_trigger_reg_S_SSI_sip: cross csr_priv_s, csr_sstatus_sie, mideleg_ssi_one, mie_ones, stvec_mode, sip_ssip_set;
    cp_trigger_reg_S_SSI_mip: cross csr_priv_s, csr_sstatus_sie, mideleg_ssi, mie_ones, stvec_mode, mip_ssip_set;
`endif
`ifdef UDB_SEI_SUPPORTED
    cp_trigger_reg_S_SEI_mip: cross csr_priv_s, csr_sstatus_sie, mideleg_sei, mie_ones, stvec_mode, mip_seip_set;
`endif
`ifdef U_SUPPORTED
`ifdef UDB_SSI_SUPPORTED
    cp_trigger_reg_U_SSI_sip: cross csr_priv_u, csr_sstatus_sie, mideleg_ssi_one, mie_ones, stvec_mode, sip_ssip_set;
    cp_trigger_reg_U_SSI_mip: cross csr_priv_u, csr_sstatus_sie, mideleg_ssi, mie_ones, stvec_mode, mip_ssip_set;
`endif
`ifdef UDB_SEI_SUPPORTED
    cp_trigger_reg_U_SEI_mip: cross csr_priv_u, csr_sstatus_sie, mideleg_sei, mie_ones, stvec_mode, mip_seip_set;
`endif
`endif
`endif

    // cp_trigger_sti_sstc: STI raised through stimecmp with menvcfg.STCE = {0/1}
`ifdef S_SUPPORTED
`ifdef SSTC_SUPPORTED
`ifdef UDB_STI_SUPPORTED
    cp_trigger_sti_sstc_M: cross csr_priv_m, menvcfg_stce, csr_mstatus_mie, mideleg_sti, mie_ones, stimecmp_zero;
    cp_trigger_sti_sstc_S: cross csr_priv_s, menvcfg_stce, csr_sstatus_sie, mideleg_sti, mie_ones, stimecmp_zero;
`ifdef U_SUPPORTED
    cp_trigger_sti_sstc_U: cross csr_priv_u, menvcfg_stce, csr_sstatus_sie, mideleg_sti, mie_ones, stimecmp_zero;
`endif
`endif
`endif
`endif

    // cp_enable: walking 1 in xie against every pending interrupt
`ifdef UDB_LCOFI_SUPPORTED
`ifdef S_SUPPORTED
    cp_enable_M_LCOFI: cross intr_priv_m, mie_walk, lcofi_observed;
`ifdef S_SUPPORTED
    cp_enable_S_LCOFI: cross intr_priv_s, mie_walk, lcofi_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_enable_U_LCOFI: cross intr_priv_u, mie_walk, lcofi_observed;
`endif
`endif
`endif
`endif
`ifdef UDB_MTI_SUPPORTED
    cp_enable_M_MTI: cross intr_priv_m, mie_walk, mti_observed;
`ifdef S_SUPPORTED
    cp_enable_S_MTI: cross intr_priv_s, mie_walk, mti_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_enable_U_MTI: cross intr_priv_u, mie_walk, mti_observed;
`endif
`endif
`endif
`ifdef UDB_MSI_SUPPORTED
    cp_enable_M_MSI: cross intr_priv_m, mie_walk, msi_observed;
`ifdef S_SUPPORTED
    cp_enable_S_MSI: cross intr_priv_s, mie_walk, msi_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_enable_U_MSI: cross intr_priv_u, mie_walk, msi_observed;
`endif
`endif
`endif
`ifdef UDB_MEI_SUPPORTED
    cp_enable_M_MEI: cross intr_priv_m, mie_walk, mei_observed;
`ifdef S_SUPPORTED
    cp_enable_S_MEI: cross intr_priv_s, mie_walk, mei_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_enable_U_MEI: cross intr_priv_u, mie_walk, mei_observed;
`endif
`endif
`endif
`ifdef UDB_STI_SUPPORTED
`ifdef S_SUPPORTED
    cp_enable_M_STI: cross intr_priv_m, mie_walk, sti_observed;
`ifdef S_SUPPORTED
    cp_enable_S_STI: cross intr_priv_s, mie_walk, sti_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_enable_U_STI: cross intr_priv_u, mie_walk, sti_observed;
`endif
`endif
`endif
`endif
`ifdef UDB_SSI_SUPPORTED
`ifdef S_SUPPORTED
    cp_enable_M_SSI: cross intr_priv_m, mie_walk, ssi_observed;
`ifdef S_SUPPORTED
    cp_enable_S_SSI: cross intr_priv_s, mie_walk, ssi_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_enable_U_SSI: cross intr_priv_u, mie_walk, ssi_observed;
`endif
`endif
`endif
`endif
`ifdef UDB_SEI_SUPPORTED
`ifdef S_SUPPORTED
    cp_enable_M_SEI: cross intr_priv_m, mie_walk, sei_observed;
`ifdef S_SUPPORTED
    cp_enable_S_SEI: cross intr_priv_s, mie_walk, sei_observed;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_enable_U_SEI: cross intr_priv_u, mie_walk, sei_observed;
`endif
`endif
`endif
`endif

    // cp_priority_*
    cp_priority_mip_M: cross intr_priv_m, xip_pair, mie_ones, any_taken;
    cp_priority_mie_M: cross intr_priv_m, xie_pair, mip_ones, any_taken;
    cp_priority_mideleg_M: cross intr_priv_m, xip_pair_deleg, mie_ones, any_taken;
`ifdef S_SUPPORTED
    cp_priority_mip_S: cross intr_priv_s, xip_pair, mie_ones, any_taken;
    cp_priority_mie_S: cross intr_priv_s, xie_pair, mip_ones, any_taken;
    cp_priority_mideleg_S: cross intr_priv_s, xip_pair_deleg, mie_ones, any_taken;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_priority_mip_U: cross intr_priv_u, xip_pair, mie_ones, any_taken;
    cp_priority_mie_U: cross intr_priv_u, xie_pair, mip_ones, any_taken;
    cp_priority_mideleg_U: cross intr_priv_u, xip_pair_deleg, mie_ones, any_taken;
`endif
`endif

    // cp_wfi: WFI waits for the timer; cp_wfi_timeout: WFI with TW = 1 traps below M-mode
    cp_wfi_M: cross priv_mode_m, wfi, mstatus_tw, csr_mstatus_mie, mie_mtie_one;
`ifdef S_SUPPORTED
    cp_wfi_S: cross priv_mode_s, wfi, mstatus_tw_zero, csr_sstatus_sie, mie_mtie_one;
    cp_wfi_timeout_S: cross intr_priv_s, wfi_timeout, mstatus_tw_one, mstatus_mie, mie_mtie;
`endif
`ifdef U_SUPPORTED
`ifdef S_SUPPORTED
    cp_wfi_timeout_U: cross intr_priv_u, wfi_timeout, mstatus_tw_one, mstatus_mie, mie_mtie;
`endif
`endif

endgroup

function void interruptssm_sample(int hart, int issue, ins_t ins);
    InterruptsSm_cg.sample(ins);
endfunction

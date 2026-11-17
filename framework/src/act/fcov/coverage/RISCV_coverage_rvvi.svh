//
// Copyright (c) 2023 Imperas Software Ltd., www.imperas.com
// Modified February 2024, jcarlin@hmc.edu
//
// SPDX-License-Identifier: Apache-2.0 WITH SHL-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
// either express or implied.
//
// See the License for the specific language governing permissions and
// limitations under the License.
//
//

`ifdef E_SUPPORTED
    `define NUM_REGS 16
`else
    `define NUM_REGS 32
`endif

riscvTraceData #(ILEN, XLEN, FLEN, VLEN) traceDataQ [(NHART-1):0][(RETIRE-1):0] [$:`NUM_RVVI_DATA];

// The value the last CSR instruction to write each CSR wrote to it (get_csr_written)
logic [(XLEN-1):0] csr_written [(NHART-1):0][4096];
int mem_client;

`include "coverage/RISCV_disasm_fallback.svh"

function void save_rvvi_data(bit trap, int hart, int issue, string disass);
  string inst_name = get_inst_name(trap, hart, issue, disass);
  riscvTraceData #(ILEN, XLEN, FLEN, VLEN) rvviData;
  bit [31:0] mask;
  bit [11:0] csr_addr;
  logic [(XLEN-1):0] csr_src;
  int idx;
  if (inst_name == "illegal") begin
    inst_name = disasm_fallback_vector(this.rvvi.insn[hart][issue]);
  end

  // Load initial prev values to use for checking register values during first (sampled) instruction
  // Todo: initial CSR values would be incorrect
  while (traceDataQ[hart][issue].size() < `NUM_RVVI_DATA) begin
    rvviData = new();
    rvviData.valid = 0;
    rvviData.order = 0;
    rvviData.insn = 0;
    rvviData.trap = 0;
    rvviData.halt = 0;
    rvviData.intr = 0;
    rvviData.mode = 0;
    rvviData.mode_virt = 0; // hypervisor bit
    rvviData.ixl = 0;
    rvviData.pc_rdata = 0;
    rvviData.pc_wdata = 0;
    rvviData.x_wdata = 0;
    rvviData.x_wb = 0;
    rvviData.f_wdata = 0;
    rvviData.f_wb = 0;
    rvviData.v_wdata = 0;
    rvviData.v_wb = 0;
    rvviData.csr = 0;
    rvviData.csr_wb = 0;
    rvviData.lrsc_cancel = 0;
    rvviData.hart = hart;
    rvviData.issue = issue;
    rvviData.disass = "";
    rvviData.inst_name = "";
    traceDataQ[hart][issue].push_front(rvviData);
  end

  // Store signal values for this trace
  rvviData = new();
  rvviData.valid = this.rvvi.valid[hart][issue];
  rvviData.order = this.rvvi.order[hart][issue];
  rvviData.insn = this.rvvi.insn[hart][issue];
  rvviData.trap = this.rvvi.trap[hart][issue];
  rvviData.halt = this.rvvi.halt[hart][issue];
  rvviData.intr = this.rvvi.intr[hart][issue];
  rvviData.mode = this.rvvi.mode[hart][issue];
  rvviData.mode_virt = this.rvvi.mode_virt[hart][issue];
  rvviData.ixl = this.rvvi.ixl[hart][issue];
  rvviData.pc_rdata = this.rvvi.pc_rdata[hart][issue];
  rvviData.pc_wdata = this.rvvi.pc_wdata[hart][issue];

  // For registers, use the existing values and only update the changed ones
  // Assign current values
  rvviData.x_wb = this.rvvi.x_wb[hart][issue];
  rvviData.x_wdata = traceDataQ[hart][issue][0].x_wdata;
  // Update changed values
  if (rvviData.x_wb != 'b0) begin
    for (idx=0; idx<`NUM_REGS; idx++) begin
      mask = 1<<idx;
      if ((mask & rvviData.x_wb) != 'b0) begin
        rvviData.x_wdata[idx] = this.rvvi.x_wdata[hart][issue][idx];
      end
    end
  end

  // Assign current values
  rvviData.f_wb = this.rvvi.f_wb[hart][issue];
  rvviData.f_wdata = traceDataQ[hart][issue][0].f_wdata;
  // Update changed values
  if (rvviData.f_wb != 'b0) begin
    for (idx=0; idx<32; idx++) begin
      mask = 1<<idx;
      if ((mask & rvviData.f_wb) != 'b0) begin
        rvviData.f_wdata[idx] = this.rvvi.f_wdata[hart][issue][idx];
      end
    end
  end

  // Assign current values
  rvviData.v_wb = this.rvvi.v_wb[hart][issue];
  rvviData.v_wdata = traceDataQ[hart][issue][0].v_wdata;
  // Update changed values
  if (rvviData.v_wb != 'b0) begin
    for (idx=0; idx<32; idx++) begin
      mask = 1<<idx;
      if ((mask & rvviData.v_wb) != 'b0) begin
        rvviData.v_wdata[idx] = this.rvvi.v_wdata[hart][issue][idx];
      end
    end
  end

  // Todo: CSR values should use the current values and only update the changed ones
  rvviData.csr = this.rvvi.csr[hart][issue];
  rvviData.csr_wb = this.rvvi.csr_wb[hart][issue];

  // The value a CSR instruction writes, from its operands: rs1 or the immediate for csrrw, combined with the old value
  // for csrrs and csrrc, which write only with a nonzero rs1 or immediate. A trace reports a CSR's readable value,
  // which can differ from what was written (mepc[1] reads as 0 while IALIGN = 32) and can change without a write (an
  // icount trigger counting down). In VS-mode and VU-mode, a supervisor CSR name accesses the VS CSR 0x100 above it.
  if (rvviData.insn[6:0] == 7'b1110011 && rvviData.insn[13:12] != 2'b00 && !rvviData.trap &&
      (rvviData.insn[13:12] == 2'b01 || rvviData.insn[19:15] != 0)) begin
    csr_addr = rvviData.insn[31:20];
    if (rvviData.mode_virt && csr_addr inside {12'h100, 12'h104, 12'h105, [12'h140:12'h144], 12'h14D, [12'h150:12'h157],
                                              12'h15C, 12'h15D, 12'h180, 12'hDB0}) csr_addr += 12'h100;
    csr_src = rvviData.insn[14] ? XLEN'(rvviData.insn[19:15]) : traceDataQ[hart][issue][0].x_wdata[rvviData.insn[19:15]];
    case (rvviData.insn[13:12])
      2'b01:   csr_written[hart][csr_addr] = csr_src;
      2'b10:   csr_written[hart][csr_addr] = traceDataQ[hart][issue][0].csr[csr_addr] | csr_src;
      default: csr_written[hart][csr_addr] = traceDataQ[hart][issue][0].csr[csr_addr] & ~csr_src;
    endcase
  end

  save_mem_data(rvviData, hart, disass, traceDataQ[hart][issue][0].x_wdata);

  // Store additional signals from the current trace
  rvviData.lrsc_cancel = this.rvvi.lrsc_cancel[hart][issue];
  rvviData.disass = disass;
  rvviData.inst_name = inst_name;
  rvviData.hart = hart;
  rvviData.issue = issue;

  // Add new trace data to array
  if (traceDataQ[hart][issue].size() >= `NUM_RVVI_DATA) begin
    traceDataQ[hart][issue].delete(`NUM_RVVI_DATA-1);
  end
  traceDataQ[hart][issue].push_front(rvviData);
endfunction

// Fill the virtual memory fields from the MEM records of this event. The fetch is the last I record and the data
// access the last D record. Page-table reads are D records that carry the PTE they read (PTE, or GPTE for the G
// stage), and come before the access they translate; an access that carries no PTE takes the last PTE read for
// its virtual page, which is the leaf (or, for a fault, the PTE the walk stopped on).
function void save_mem_data(riscvTraceData #(ILEN, XLEN, FLEN, VLEN) rvviData, int hart, string disass,
                            logic [31:0][(XLEN-1):0] xregs);
  rvvi_mem_access_t acc, i_acc, d_acc;
  rvvi_mem_access_t pte_reads[$];
  bit have_i = 0, have_d = 0;
  string mnemonic;
  bit is_load, is_store;
  while (this.rvvi.mem_access_pop(mem_client, hart, acc) != 0) begin
    if (acc.fetch) begin
      i_acc = acc;
      have_i = 1;
    end else begin
      d_acc = acc;
      have_d = 1;
      if (acc.pte != 0 || acc.gpte != 0) pte_reads.push_back(acc);
    end
  end
  if (have_i) i_acc = with_walk_pte(i_acc, pte_reads);
  if (have_d) d_acc = with_walk_pte(d_acc, pte_reads);
  void'($sscanf(disass, "%s %s", mnemonic, mnemonic));
  is_load = mnemonic inside {"lb", "lbu", "lh", "lhu", "lw", "lwu", "ld", "flh", "flw", "fld", "flq",
                             "c.lbu", "c.lh", "c.lhu", "c.lw", "c.ld", "c.lwsp", "c.ldsp",
                             "c.flw", "c.fld", "c.flwsp", "c.fldsp"} ||
            has_prefix(mnemonic, "lr.") || has_prefix(mnemonic, "amo") || has_prefix(mnemonic, "hlv");
  is_store = mnemonic inside {"sb", "sh", "sw", "sd", "fsh", "fsw", "fsd", "fsq",
                              "c.sb", "c.sh", "c.sw", "c.sd", "c.swsp", "c.sdsp",
                              "c.fsw", "c.fsd", "c.fswsp", "c.fsdsp"} ||
             has_prefix(mnemonic, "sc.") || has_prefix(mnemonic, "amo") || has_prefix(mnemonic, "hsv") ||
             has_prefix(mnemonic, "cbo.");
  if (!(is_load || is_store)) have_d = 0;

  rvviData.execute_access = have_i;
  rvviData.read_access = have_d && is_load;
  rvviData.write_access = have_d && is_store;
  rvviData.virt_adr_i = have_i ? XLEN'(i_acc.vaddr) : rvviData.pc_rdata;
  rvviData.pte_i = i_acc.pte[(XLEN-1):0];
  rvviData.page_type_i = i_acc.page_type[1:0];
  rvviData.virt_adr_d = have_d ? XLEN'(d_acc.vaddr) : get_data_vaddr(disass, xregs);
  rvviData.pte_d = d_acc.pte[(XLEN-1):0];
  rvviData.page_type_d = d_acc.page_type[1:0];
  rvviData.g_pte_i = i_acc.gpte[(XLEN-1):0];
  rvviData.g_pte_d = d_acc.gpte[(XLEN-1):0];
  `ifdef UDB_MXLEN_32
    rvviData.phys_adr_i = i_acc.paddr[33:0];
    rvviData.phys_adr_d = d_acc.paddr[33:0];
    rvviData.ppn_i = i_acc.pte[31:10];
    rvviData.ppn_d = d_acc.pte[31:10];
  `else
    rvviData.phys_adr_i = i_acc.paddr[55:0];
    rvviData.phys_adr_d = d_acc.paddr[55:0];
    rvviData.ppn_i = i_acc.pte[53:10];
    rvviData.ppn_d = d_acc.pte[53:10];
  `endif
endfunction

// acc with the PTE and G-stage PTE it lacks taken from the last page-table read for its virtual page
function rvvi_mem_access_t with_walk_pte(rvvi_mem_access_t acc, rvvi_mem_access_t pte_reads[$]);
  bit need_pte = (acc.pte == 0), need_gpte = (acc.gpte == 0);
  for (int i = pte_reads.size() - 1; i >= 0 && (need_pte || need_gpte); i--) begin
    if ((pte_reads[i].vaddr >> 12) != (acc.vaddr >> 12)) continue;
    if (need_pte && pte_reads[i].pte != 0) begin
      acc.pte = pte_reads[i].pte;
      acc.page_type = pte_reads[i].page_type;
      need_pte = 0;
    end
    if (need_gpte && pte_reads[i].gpte != 0) begin
      acc.gpte = pte_reads[i].gpte;
      acc.guest_page_type = pte_reads[i].guest_page_type;
      need_gpte = 0;
    end
  end
  return acc;
endfunction

function bit has_prefix(string str, string prefix);
  return str.len() >= prefix.len() && str.substr(0, prefix.len()-1) == prefix;
endfunction

// Effective address of a scalar load, store, AMO, or CMO, from the "offset(reg)" operand of the
// disassembly and the register values before the instruction. jalr names a jump target, prefetch
// does not access memory, and a vector access has an address per element, so they return 0.
function bit [(XLEN-1):0] get_data_vaddr(string disass, logic [31:0][(XLEN-1):0] xregs);
  string mnemonic;
  int open, close, start, offset;
  void'($sscanf(disass, "%s %s", mnemonic, mnemonic));
  if (mnemonic == "jalr" || mnemonic.substr(0, 8) == "prefetch." || mnemonic[0] == "v") return 0;
  // Stack pointer forms such as "c.lwsp x1, 8" have an implicit sp base
  if (mnemonic inside {"c.lwsp", "c.ldsp", "c.swsp", "c.sdsp", "c.flwsp", "c.fldsp", "c.fswsp", "c.fsdsp"}) begin
    for (start = disass.len()-1; start > 0 && disass[start-1] != " "; start--);
    void'($sscanf(disass.substr(start, disass.len()-1), "%d", offset));
    return xregs[2] + XLEN'(offset);
  end
  for (open = 0; open < disass.len() && disass[open] != "("; open++);
  if (open == disass.len()) return 0;
  for (close = open; close < disass.len() && disass[close] != ")"; close++);
  for (start = open; start > 0 && disass[start-1] != " "; start--);
  offset = 0;
  if (start < open) void'($sscanf(disass.substr(start, open-1), "%d", offset));
  return xregs[get_gpr_num(disass.substr(open+1, close-1))] + XLEN'(offset);
endfunction

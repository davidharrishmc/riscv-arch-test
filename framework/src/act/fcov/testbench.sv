///////////////////////////////////////////
//
// RISC-V Architectural Functional Coverage Testbench
//
// Copyright (C) 2025 Harvey Mudd College, 10x Engineers, UET Lahore
// Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
// Written: Jordan Carlin jcarlin@hmc.edu March 2025
//
// SPDX-License-Identifier: Apache-2.0
//
////////////////////////////////////////////////////////////////////////////////////////////////

// Replays RVVI-TEXT trace files onto the RVVI-Trace interface.
// Each unescaped line of a trace file is one clock step.
module testbench;
  import RISCV_coverage_pkg::rvvi_mem_access_t;

  // Load configuration
  `include "rvtest_config.svh"
  `include "derived_config.svh"

  // Set up variable lengths
  localparam XLEN = `UDB_MXLEN;

  `ifdef Q_SUPPORTED
    localparam FLEN = 128;
  `elsif D_SUPPORTED
    localparam FLEN = 64;
  `else
    localparam FLEN = 32;
  `endif

  localparam VLEN = (`UDB_VLEN > 0) ? `UDB_VLEN : 64;   // no V: size the unused vector trace fields

  // Trace file handling
  string  traceFileList, traceFile;
  integer traceFileListHandler, num;
  integer traceFileHandler = 0; // 0 = no trace file open yet
  string  line;
  string  traceFiles[$];
  int     fileNum = -1;

  // RVVI-TEXT parser state
  string             tokens[$];
  string             token;  // popped before $sscanf, which Questa may evaluate its string argument more than once
  string             key;
  int                hart, issue, count;
  logic [63:0]       orderCount;
  int                regNum;
  logic [(XLEN-1):0] xRegVal;
  logic [(FLEN-1):0] fRegVal;
  logic [(VLEN-1):0] vRegVal;
  longint unsigned   netVal;
  rvvi_mem_access_t  memAccess;

  // RVVI Trace interface signals
  logic              clk;
  logic              valid;
  logic [63:0]       order;
  logic [31:0]       insn;
  logic              trap;
  logic              debug_mode;
  logic [(XLEN-1):0] pc_rdata;
  logic [1:0]        mode;
  logic              mode_virt;
  logic [31:0][(XLEN-1):0]   x_wdata;
  logic [31:0]               x_wb;
  logic [31:0][(FLEN-1):0]   f_wdata;
  logic [31:0]               f_wb;
  logic [31:0][(VLEN-1):0]   v_wdata;
  logic [31:0]               v_wb;
  logic [4095:0][(XLEN-1):0] csr;
  logic [4095:0]             csr_wb;

  // Generate clock
  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  // Load list of trace files from traceFileList plusarg
  initial begin
    if (!$value$plusargs("traceFileList=%s", traceFileList)) begin
      $display("Error: traceFileList not provided");
      $finish;
    end
    traceFileListHandler = $fopen(traceFileList, "r");
    if (traceFileListHandler == 0) begin
      $display("Error: Could not open trace file list");
      $finish;
    end
    while ($fgets(line, traceFileListHandler) != 0) begin
      if (line != "" && line != "\n" && line[0] != "#") begin
        // Strip newline character from the end of the line
        if (line[line.len()-1] == "\n") begin
          line = line.substr(0, line.len()-2);
        end
        traceFiles.push_back(line);
      end
    end
    if(traceFiles.size == 0) begin
      $display("Error: No trace files found in trace file list");
      $finish;
    end
    $fclose(traceFileListHandler);
  end

  // Load coverage model and connect to RVVI trace interface
  rvviTrace #(.XLEN(XLEN), .FLEN(FLEN), .VLEN(VLEN)) rvvi();
  riscv_arch_test riscv_arch_test(rvvi);

  // Drive the interface on the falling edge so all signals and MEM records are stable when
  // the coverage model samples on the rising edge.
  always @(negedge clk) begin
    {valid, insn, trap, debug_mode, pc_rdata, x_wb, f_wb, v_wb, csr_wb, x_wdata, f_wdata, v_wdata} = 0;
    hart = 0;
    issue = 0;

    readLine(tokens);
    while (tokens.size() > 0) begin
      key = tokens.pop_front();
      case(key)
        "VERSION": void'(popN(2));
        "VENDOR":  void'(popN(3));
        "PARAMS":  void'(popN(2*popInt()));
        "HART": begin
          hart = popInt();
          issue = 0;
          if (hart != 0) $fatal(1, "Error: only hart 0 is supported, found HART %0d in %s", hart, traceFile);
        end
        "ISSUE": begin
          issue = popInt();
          if (issue != 0) $fatal(1, "Error: only issue slot 0 is supported, found ISSUE %0d in %s", issue, traceFile);
        end
        "ORDER": orderCount = popInt();
        "RET", "TRAP": begin
          if (valid) $fatal(1, "Error: more than one retirement in one event in %s", traceFile);
          token = tokens.pop_front();
          num = $sscanf(token, "0x%h", pc_rdata);
          token = tokens.pop_front();
          num = $sscanf(token, "0x%h", insn);
          trap = (key == "TRAP");
          valid = 1;
          order = orderCount;
          orderCount++;
        end
        "X": begin
          regNum = popInt();
          token = tokens.pop_front();
          num = $sscanf(token, "0x%h", xRegVal);
          x_wdata[regNum] = xRegVal;
          x_wb[regNum] = 1'b1;
        end
        "F": begin
          regNum = popInt();
          token = tokens.pop_front();
          num = $sscanf(token, "0x%h", fRegVal);
          f_wdata[regNum] = fRegVal;
          f_wb[regNum] = 1'b1;
        end
        "V": begin
          regNum = popInt();
          token = tokens.pop_front();
          num = $sscanf(token, "0x%h", vRegVal);
          v_wdata[regNum] = vRegVal;
          v_wb[regNum] = 1'b1;
        end
        "C": begin
          token = tokens.pop_front();
          num = $sscanf(token, "0x%h", regNum);
          token = tokens.pop_front();
          num = $sscanf(token, "0x%h", xRegVal);
          csr[regNum] = xRegVal;
          csr_wb[regNum] = 1'b1;
        end
        "MODE":  begin token = tokens.pop_front(); num = $sscanf(token, "0x%h", mode); end
        "VIRT":  begin token = tokens.pop_front(); num = $sscanf(token, "0x%h", mode_virt); end
        "DM":    begin token = tokens.pop_front(); num = $sscanf(token, "0x%h", debug_mode); end
        "META":  void'(popN(popInt()));
        "CYCLE", "TIME": void'(popN(1));
        "NET": begin
          key = tokens.pop_front();
          token = tokens.pop_front();
          num = $sscanf(token, "0x%h", netVal);
          rvvi.net_push(key, netVal);
        end
        "CANCEL": rvvi.net_cancel_push(tokens.pop_front());
        "STATE": begin
          key = tokens.pop_front();
          rvvi.state[hart][key] = tokens.pop_front();
        end
        "MEM": parseMem();
        default: $fatal(1, "Error: unknown RVVI-TEXT element %s in %s", key, traceFile);
      endcase
    end
  end

  // Get the tokens of the next line. Moves to the next trace file at end of file and
  // ends the simulation after the last one.
  task automatic readLine(ref string toks[$]);
    forever begin
      if (traceFileHandler == 0) begin
        if (fileNum >= int'(traceFiles.size()) - 1) begin
          $display("All trace files completed");
          $finish;
          return;
        end
        fileNum++;
        traceFile = traceFiles[fileNum];
        $display("Opening trace file: %s", traceFile);
        traceFileHandler = $fopen(traceFile, "r");
        if (traceFileHandler == 0) $fatal(1, "Error: Could not open trace file %s", traceFile);
        orderCount = 0;
      end
      if (readLogicalLine(toks)) return;
      $display("Completed trace file: %s", traceFile);
      $fclose(traceFileHandler);
      traceFileHandler = 0;
    end
  endtask

  // Read one line, joined with its continuation lines, from the open trace file.
  // Returns 0 at end of file.
  function automatic bit readLogicalLine(ref string toks[$]);
    bit more = 1;
    bit got = 0;
    toks.delete();
    while (more) begin
      if ($fgets(line, traceFileHandler) == 0) return got;
      got = 1;
      tokenize(line, toks);
      more = (toks.size() > 0 && toks[toks.size()-1] == "\\");
      if (more) void'(toks.pop_back());
    end
    return 1;
  endfunction

  function automatic int popInt();
    int val;
    token = tokens.pop_front();
    void'($sscanf(token, "%d", val));
    return val;
  endfunction

  function automatic int popN(int n);
    repeat (n) void'(tokens.pop_front());
    return n;
  endfunction

  // MEM <bus> <bytes> <vaddr> <paddr> <count> [<key> <value>]*
  function automatic void parseMem();
    string bus, k, v;
    int pairs;
    longint unsigned val;
    memAccess = '0;
    bus = tokens.pop_front();
    memAccess.fetch = (bus == "I");
    memAccess.size = popInt();
    token = tokens.pop_front();
    void'($sscanf(token, "0x%h", val));
    memAccess.vaddr = val;
    token = tokens.pop_front();
    void'($sscanf(token, "0x%h", val));
    memAccess.paddr = val;
    pairs = popInt();
    repeat (pairs) begin
      k = tokens.pop_front();
      v = tokens.pop_front();
      val = 0;
      void'($sscanf(v, "0x%h", val));
      case (k)
        "PTE":    memAccess.pte = val;
        "GPTE":   memAccess.gpte = val;
        "GPADDR": memAccess.gaddr = val;
        "PT":     memAccess.page_type = pageType(v);
        "GPT":    memAccess.guest_page_type = pageType(v);
        default: ; // Unknown keys are skipped
      endcase
    end
    rvvi.mem_access_push(hart, memAccess);
  endfunction

  function automatic logic [2:0] pageType(string pt);
    case (pt)
      "K": return 3'd0;
      "M": return 3'd1;
      "G": return 3'd2;
      "T": return 3'd3;
      "P": return 3'd4;
      default: $fatal(1, "Error: unknown page type %s in %s", pt, traceFile);
    endcase
    return 3'd0;
  endfunction

  // Split a line into tokens in one pass. Removes '...' comments and the quotes around "..." names.
  // A backslash inside a comment or a quoted name is not a continuation.
  function automatic void tokenize(string str, ref string toks[$]);
    int start = -1;
    for (int i = 0; i < str.len(); i++) begin
      byte c = str[i];
      if (c == "'" || c == "\"") begin
        int close = i + 1;
        if (start >= 0) begin
          toks.push_back(str.substr(start, i-1));
          start = -1;
        end
        while (close < str.len() && str[close] != c) close++;
        if (c == "\"") toks.push_back(close > i + 1 ? str.substr(i+1, close-1) : "");
        i = close;
      end else if (c == " " || c == "\n" || c == "\t" || c == "\r") begin
        if (start >= 0) begin
          toks.push_back(str.substr(start, i-1));
          start = -1;
        end
      end else if (start < 0) start = i;
    end
    if (start >= 0) toks.push_back(str.substr(start, str.len()-1));
  endfunction

  // Connect testbench signals to RVVI trace interface
  assign rvvi.clk = clk;
  assign rvvi.valid[0][0] = valid;
  assign rvvi.order[0][0] = order;
  assign rvvi.insn[0][0] = insn;
  assign rvvi.trap[0][0] = trap;
  assign rvvi.debug_mode[0][0] = debug_mode;
  assign rvvi.pc_rdata[0][0] = pc_rdata;
  assign rvvi.mode[0][0] = mode;
  assign rvvi.mode_virt[0][0] = mode_virt;
  assign rvvi.x_wb[0][0] = x_wb;
  assign rvvi.x_wdata[0][0] = x_wdata;
  assign rvvi.f_wb[0][0] = f_wb;
  assign rvvi.f_wdata[0][0] = f_wdata;
  assign rvvi.v_wb[0][0] = v_wb;
  assign rvvi.v_wdata[0][0] = v_wdata;
  assign rvvi.csr_wb[0][0] = csr_wb;
  assign rvvi.csr[0][0] = csr;

endmodule

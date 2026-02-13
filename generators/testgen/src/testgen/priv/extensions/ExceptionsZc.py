##################################
# priv/extensions/ExceptionsZc.py
#
# ExceptionsZc extension exception test generator.
# jgong@hmc.edu Jan 2026
# SPDX-License-Identifier: Apache-2.0
##################################

"""Zc extension exception test generator."""

from testgen.asm.helpers import comment_banner, write_sigupd
from testgen.data.state import TestData
from testgen.priv.registry import add_priv_test_generator


def _add_load_test(
    ops: list[str],
    offset: int,
    test_data: TestData,
    coverpoint: str,
    covergroup: str,
    addr_reg: int,
    base_reg: int,
    check_reg: int,
    fp_reg: int,
) -> list[str]:
    all_lines = []
    for op in ops:
        is_sp = op.endswith("sp")
        t_lines = []
        suffix = "_sp" if is_sp else ""
        t_lines.append(test_data.add_testcase(coverpoint, f"{op.lower()}{suffix}_off{offset}", covergroup))

        # Load address and apply offset
        if is_sp:
            t_lines.append(f"    mv x{base_reg}, sp")  # Save sp
            t_lines.append("    LA(sp, scratch)")
            t_lines.append(f"    addi sp, sp, {offset}")
        else:
            t_lines.append(f"    LA(x{addr_reg}, scratch)")
            t_lines.append(f"    addi x{addr_reg}, x{addr_reg}, {offset}")

        # Perform load
        reg_str = f"f{fp_reg}" if "f" in op.lower() else f"x{check_reg}"
        sig_reg = fp_reg if "f" in op.lower() else check_reg

        if is_sp:
            t_lines.append(f"    {op} {reg_str}, 0(sp)")
            t_lines.append(f"    mv sp, x{base_reg}")  # Restore sp immediately
        else:
            t_lines.append(f"    {op} {reg_str}, 0(x{addr_reg})")

        t_lines.append(write_sigupd(sig_reg, test_data, sig_type="float"))
        all_lines.extend(t_lines)
    return all_lines


def _add_store_test(
    ops: list[str],
    offset: int,
    test_data: TestData,
    coverpoint: str,
    covergroup: str,
    addr_reg: int,
    base_reg: int,
    check_reg: int,
    fp_reg: int,
) -> list[str]:
    all_lines = []
    for op in ops:
        is_sp = op.endswith("sp")
        t_lines = []
        suffix = "_sp" if is_sp else ""
        t_lines.append(test_data.add_testcase(coverpoint, f"{op.lower()}{suffix}_off{offset}", covergroup))

        # Load address and apply offset
        if is_sp:
            t_lines.append(f"    mv x{base_reg}, sp")  # Save sp
            t_lines.append("    LA(sp, scratch)")
            t_lines.append(f"    addi sp, sp, {offset}")
        else:
            t_lines.append(f"    LA(x{addr_reg}, scratch)")
            t_lines.append(f"    addi x{addr_reg}, x{addr_reg}, {offset}")

        # Perform store
        reg_str = f"f{fp_reg}" if "f" in op.lower() else f"x{check_reg}"

        if is_sp:
            t_lines.append(f"    {op} {reg_str}, 0(sp)")
            t_lines.append(f"    mv sp, x{base_reg}")  # Restore sp immediately
        else:
            t_lines.append(f"    {op} {reg_str}, 0(x{addr_reg})")

        t_lines.append(f"    li x{check_reg}, 0x{offset:08x}")  # Use offset for signature
        t_lines.append(write_sigupd(check_reg, test_data))
        all_lines.extend(t_lines)
    return all_lines


def _add_load_fault(
    ops: list[str],
    test_data: TestData,
    coverpoint: str,
    covergroup: str,
    addr_reg: int,
    base_reg: int,
    check_reg: int,
    fp_reg: int,
) -> list[str]:
    all_lines = []
    for op in ops:
        is_sp = op.endswith("sp")
        t_lines = []
        suffix = "_sp" if is_sp else ""
        test_label = f"{op.lower()}{suffix}_fault"

        # 8-byte alignment
        t_lines.append("    .align 3")
        t_lines.append(test_data.add_testcase(coverpoint, test_label, covergroup))

        t_lines.append(f"    li x{addr_reg}, RVMODEL_ACCESS_FAULT_ADDRESS")

        reg_str = f"f{fp_reg}" if "f" in op.lower() else f"x{check_reg}"

        if is_sp:
            t_lines.append(f"    mv x{base_reg}, sp")
            t_lines.append(f"    mv sp, x{addr_reg}")
            t_lines.append(f"    {op} {reg_str}, 0(sp)")
            t_lines.append(f"    mv sp, x{base_reg}")
        else:
            t_lines.append(f"    {op} {reg_str}, 0(x{addr_reg})")

        t_lines.append("    nop")
        t_lines.append("    nop")

        all_lines.extend(t_lines)
    return all_lines


def _add_store_fault(
    ops: list[str],
    test_data: TestData,
    coverpoint: str,
    covergroup: str,
    addr_reg: int,
    base_reg: int,
    check_reg: int,
    fp_reg: int,
) -> list[str]:
    all_lines = []
    for op in ops:
        is_sp = op.endswith("sp")
        t_lines = []
        suffix = "_sp" if is_sp else ""
        test_label = f"{op.lower()}{suffix}_fault"

        # 8-byte alignment
        t_lines.append("    .align 3")
        t_lines.append(test_data.add_testcase(coverpoint, test_label, covergroup))

        t_lines.append(f"    li x{addr_reg}, RVMODEL_ACCESS_FAULT_ADDRESS")

        reg_str = f"f{fp_reg}" if "f" in op.lower() else f"x{check_reg}"

        if is_sp:
            t_lines.append(f"    mv x{base_reg}, sp")
            t_lines.append(f"    mv sp, x{addr_reg}")
            t_lines.append(f"    {op} {reg_str}, 0(sp)")
            t_lines.append(f"    mv sp, x{base_reg}")
        else:
            t_lines.append(f"    {op} {reg_str}, 0(x{addr_reg})")

        t_lines.append("    nop")
        t_lines.append("    nop")

        all_lines.extend(t_lines)
    return all_lines


def _generate_load_address_misaligned_tests(test_data: TestData) -> list[str]:
    covergroup, coverpoint = "ExceptionsZc_cg", "cp_load_address_misaligned"
    addr_reg, base_reg, check_reg = test_data.int_regs.get_registers(
        3, exclude_regs=[*range(0, 8), *range(16, 32)]
    )  # registers x8-x15 used for compressed instructions

    fp_reg = test_data.float_regs.get_register(
        exclude_regs=[*range(0, 8), *range(16, 32)]
    )  # exclude registers outside of f8-f15

    lines = [comment_banner(coverpoint, "Compressed Misaligned Loads")]

    for offset in range(8):
        lines.append(f"\n# Offset {offset} (LSBs: {offset:03b})")

        # Zca
        base_ops = ["c.lw", "c.lwsp"]
        lines.extend(
            _add_load_test(base_ops, offset, test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg)
        )
        lines.append("#if __riscv_xlen == 64")
        lines.extend(
            _add_load_test(
                ["c.ld", "c.ldsp"], offset, test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg
            )
        )
        lines.append("#endif")

        # Zcb
        lines.append("#ifdef ZCB_SUPPORTED")
        lines.extend(
            _add_load_test(
                ["c.lh", "c.lhu", "c.lbu"],
                offset,
                test_data,
                coverpoint,
                covergroup,
                addr_reg,
                base_reg,
                check_reg,
                fp_reg,
            )
        )
        lines.append("#endif")

        # Zcf
        lines.append("#if defined(ZCF_SUPPORTED)")
        lines.extend(
            _add_load_test(
                ["c.flw", "c.flwsp"], offset, test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg
            )
        )
        lines.append("#endif")

        # Zcd
        lines.append("#ifdef ZCD_SUPPORTED")
        lines.extend(
            _add_load_test(
                ["c.fld", "c.fldsp"], offset, test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg
            )
        )
        lines.append("#endif")

    test_data.int_regs.return_registers([addr_reg, base_reg, check_reg])
    test_data.float_regs.return_registers([fp_reg])
    return lines


def _generate_store_address_misaligned_tests(test_data: TestData) -> list[str]:
    covergroup, coverpoint = "ExceptionsZc_cg", "cp_store_address_misaligned"
    addr_reg, base_reg, check_reg = test_data.int_regs.get_registers(
        3, exclude_regs=[*range(0, 8), *range(16, 32)]
    )  # registers x8-x15 used for compressed instructions

    fp_reg = test_data.float_regs.get_register(
        exclude_regs=[*range(0, 8), *range(16, 32)]
    )  # exclude registers outside of f8-f15

    lines = [comment_banner(coverpoint, "Compressed Misaligned Stores")]

    for offset in range(8):
        lines.append(f"\n# Offset {offset} (LSBs: {offset:03b})")

        # Zca
        base_ops = ["c.sw", "c.swsp"]
        lines.extend(
            _add_store_test(base_ops, offset, test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg)
        )
        lines.append("#if __riscv_xlen == 64")
        lines.extend(
            _add_store_test(
                ["c.sd", "c.sdsp"], offset, test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg
            )
        )
        lines.append("#endif")

        # Zcb
        lines.append("#ifdef ZCB_SUPPORTED")
        lines.extend(
            _add_store_test(
                ["c.sb", "c.sh"], offset, test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg
            )
        )
        lines.append("#endif")

        # Zcf
        lines.append("#if defined(ZCF_SUPPORTED)")
        lines.extend(
            _add_store_test(
                ["c.fsw", "c.fswsp"], offset, test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg
            )
        )
        lines.append("#endif")

        # Zcd
        lines.append("#ifdef ZCD_SUPPORTED")
        lines.extend(
            _add_store_test(
                ["c.fsd", "c.fsdsp"], offset, test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg
            )
        )
        lines.append("#endif")

    test_data.int_regs.return_registers([addr_reg, base_reg, check_reg])
    test_data.float_regs.return_registers([fp_reg])
    return lines


def _generate_load_access_fault_tests(test_data: TestData) -> list[str]:
    covergroup, coverpoint = "ExceptionsZc_cg", "cp_load_access_fault"
    addr_reg, base_reg, check_reg = test_data.int_regs.get_registers(
        3, exclude_regs=[*range(0, 8), *range(16, 32)]
    )  # registers x8-x15 used for compressed instructions

    fp_reg = test_data.float_regs.get_register(
        exclude_regs=[*range(0, 8), *range(16, 32)]
    )  # exclude registers outside of f8-f15

    lines = [comment_banner(coverpoint, "Load Access Fault")]

    # Zca
    base_ops = ["c.lw", "c.lwsp"]
    lines.extend(_add_load_fault(base_ops, test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg))
    lines.append("#if __riscv_xlen == 64")
    lines.extend(
        _add_load_fault(["c.ld", "c.ldsp"], test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg)
    )
    lines.append("#endif")

    # Zcb
    lines.append("#ifdef ZCB_SUPPORTED")
    lines.extend(
        _add_load_fault(
            ["c.lh", "c.lhu", "c.lbu"], test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg
        )
    )
    lines.append("#endif")

    # Zcf
    lines.append("#if defined(ZCF_SUPPORTED)")
    lines.extend(
        _add_load_fault(["c.flw", "c.flwsp"], test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg)
    )
    lines.append("#endif")

    # Zcd
    lines.append("#ifdef ZCD_SUPPORTED")
    lines.extend(
        _add_load_fault(["c.fld", "c.fldsp"], test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg)
    )
    lines.append("#endif")

    test_data.int_regs.return_registers([addr_reg, base_reg, check_reg])
    test_data.float_regs.return_registers([fp_reg])
    return lines


def _generate_store_access_fault_tests(test_data: TestData) -> list[str]:
    covergroup, coverpoint = "ExceptionsZc_cg", "cp_store_access_fault"
    addr_reg, base_reg, check_reg = test_data.int_regs.get_registers(
        3, exclude_regs=[*range(0, 8), *range(16, 32)]
    )  # registers x8-x15 used for compressed instructions

    fp_reg = test_data.float_regs.get_register(
        exclude_regs=[*range(0, 8), *range(16, 32)]
    )  # exclude registers outside of f8-f15

    lines = [comment_banner(coverpoint, "Store Access Fault")]

    # Zca
    base_ops = ["c.sw", "c.swsp"]
    lines.extend(_add_store_fault(base_ops, test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg))
    lines.append("#if __riscv_xlen == 64")
    lines.extend(
        _add_store_fault(["c.sd", "c.sdsp"], test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg)
    )
    lines.append("#endif")

    # Zcb
    lines.append("#ifdef ZCB_SUPPORTED")
    lines.extend(
        _add_store_fault(["c.sb", "c.sh"], test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg)
    )
    lines.append("#endif")

    # Zcf
    lines.append("#if defined(ZCF_SUPPORTED)")
    lines.extend(
        _add_store_fault(["c.fsw", "c.fswsp"], test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg)
    )
    lines.append("#endif")

    # Zcd
    lines.append("#ifdef ZCD_SUPPORTED")
    lines.extend(
        _add_store_fault(["c.fsd", "c.fsdsp"], test_data, coverpoint, covergroup, addr_reg, base_reg, check_reg, fp_reg)
    )
    lines.append("#endif")

    test_data.int_regs.return_registers([addr_reg, base_reg, check_reg])
    test_data.float_regs.return_registers([fp_reg])
    return lines


def _generate_breakpoint_tests(test_data: TestData) -> list[str]:
    """Generate breakpoint exception test."""
    covergroup, coverpoint = "ExceptionsZc_cg", "cp_breakpoint"

    lines = [
        comment_banner(coverpoint, "Breakpoint"),
        test_data.add_testcase(coverpoint, "c_ebreak", covergroup),
        "    c.ebreak",
        "    nop",
    ]

    return lines


def _generate_illegal_instruction_tests(test_data: TestData) -> list[str]:
    """Generate illegal compressed instructions."""
    covergroup, coverpoint = "ExceptionsZc_cg", "cp_illegal_instruction"

    lines = [
        comment_banner(coverpoint, "Illegal Instruction"),
        "    .align 2",  # Add alignment
        test_data.add_testcase(coverpoint, "illegal0", covergroup),
        "    .insn 0x0000",  # use two byte for instruction alignment when trapping
    ]

    return lines


@add_priv_test_generator("ExceptionsZc", extensions=["I", "Zicsr", "Zca", "Zcd", "Zcb", "Sm"])
def make_exceptionszc(test_data: TestData) -> list[str]:
    """Main entry point for Zc exception test generation."""
    lines = []

    sig_reg, data_reg = test_data.int_regs.get_registers(2, exclude_regs=[0])

    lines.extend(
        [
            "#ifdef RVTEST_FP",
            "    li t0, 0x4000",
            "    csrs mstatus, t0",
            "#endif",
            "",
            "# Initialize scratch memory with test data",
            f"    LA(x{sig_reg}, scratch)",
            f"    LI(x{data_reg}, 0xDEADBEEF)",
            f"    sw x{data_reg}, 0(x{sig_reg})",
            f"    sw x{data_reg}, 4(x{sig_reg})",
            f"    sw x{data_reg}, 8(x{sig_reg})",
            f"    sw x{data_reg}, 12(x{sig_reg})",
            "",
            "# Load FP test data if FP is supported",
            "#ifdef RVTEST_FP",
            "    # Load test value into f8 from scratch memory",
            "#if FLEN == 32",
            f"    flw f8, 0(x{sig_reg})",
            "#elif FLEN == 64",
            f"    fld f8, 0(x{sig_reg})",
            "#endif",
            "#endif",
            "",
        ]
    )

    test_data.int_regs.return_registers([sig_reg, data_reg])

    lines.extend(_generate_load_address_misaligned_tests(test_data))
    lines.extend(_generate_store_address_misaligned_tests(test_data))
    lines.extend(_generate_load_access_fault_tests(test_data))
    lines.extend(_generate_store_access_fault_tests(test_data))
    lines.extend(_generate_breakpoint_tests(test_data))
    lines.extend(_generate_illegal_instruction_tests(test_data))

    return lines

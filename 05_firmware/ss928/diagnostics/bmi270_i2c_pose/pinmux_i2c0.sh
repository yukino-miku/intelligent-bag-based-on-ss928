#!/bin/sh
set -eu

# 40Pin Pin3/Pin5 -> I2C0_SDA/I2C0_SCL.
bspmm 0x102F013c 0x2031
bspmm 0x102F0140 0x2031

# Optional interrupt input if INT1 is wired to 40Pin Pin13.
bspmm 0x10230044 0x1200

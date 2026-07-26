#!/bin/sh
set -eu

command -v bspmm >/dev/null 2>&1 || { echo "bspmm not found" >&2; exit 1; }

# BMI270 I2C0
bspmm 0x102F013c 0x2031
bspmm 0x102F0140 0x2031
# DX-GP21 UART4
bspmm 0x102F0134 0x1201
bspmm 0x102F0138 0x1201
# Rev2 left/right indicator lights. TM6605 vibration is on I2C0 via TCA9548A.
bspmm 0x102F0110 0x1205
bspmm 0x102F01EC 0x1201
# MAX98357 I2S
bspmm 0x102F010C 0x1202
bspmm 0x102F0108 0x1102
bspmm 0x102F0104 0x1202

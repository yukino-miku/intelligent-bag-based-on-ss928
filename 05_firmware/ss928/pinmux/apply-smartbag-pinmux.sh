#!/bin/sh
set -eu

command -v bspmm >/dev/null 2>&1 || { echo "bspmm not found" >&2; exit 1; }

PROFILE=${1:-}
if [ -z "$PROFILE" ] && [ -f /etc/smartbag/hardware.json ]; then
    PROFILE=$(python3 -c 'import json; print(json.load(open("/etc/smartbag/hardware.json"))["profile"])')
fi
PROFILE=${PROFILE:-legacy_pwm_haptics}

# BMI270 I2C0
bspmm 0x102F013c 0x2031
bspmm 0x102F0140 0x2031
# DX-GP21 UART4
bspmm 0x102F0134 0x1201
bspmm 0x102F0138 0x1201
case "$PROFILE" in
    rev2_tm6605_mr20)
        # Rev2: Pin7/Pin32 are left/right warning lights. Haptics use I2C0.
        bspmm 0x102F0110 0x1205
        bspmm 0x102F01EC 0x1201
        ;;
    legacy_pwm_haptics)
        # Legacy: four vibration driver PWM inputs.
        bspmm 0x102F0110 0x1205
        bspmm 0x102F01EC 0x1201
        bspmm 0x102F0100 0x1205
        bspmm 0x102F00DC 0x1205
        ;;
    *)
        echo "unsupported hardware profile: $PROFILE" >&2
        exit 1
        ;;
esac
# MAX98357 I2S
bspmm 0x102F010C 0x1202
bspmm 0x102F0108 0x1102
bspmm 0x102F0104 0x1202

echo "applied SS928 pinmux profile=$PROFILE"

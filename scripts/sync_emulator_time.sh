#!/bin/bash
# Sync emulator timezone and time with host (America/Toronto / EDT)
adb root && sleep 2
adb shell setprop persist.sys.timezone "America/Toronto"
adb shell date $(date +'%m%d%H%M%Y.%S')
adb shell am broadcast -a android.intent.action.TIME_SET
adb shell am broadcast -a android.intent.action.TIMEZONE_CHANGED --es time-zone "America/Toronto"
echo "Emulator: $(adb shell date)"

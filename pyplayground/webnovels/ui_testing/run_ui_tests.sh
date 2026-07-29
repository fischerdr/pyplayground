#!/usr/bin/env bash
# Orchestration wrapper for pyplayground/webnovels/ui_testing/'s live UI
# tests: owns starting a real Xvfb + fluxbox display, running the given
# pytest target(s) against it with DISPLAY set, and tearing both back down
# afterward. The Python fixture layer (xdo_helper.py, test_menu_smoke.py)
# deliberately assumes a live display already exists and fails fast if it
# doesn't -- this script is the piece responsible for making sure one does.
#
# Usage:
#   run_ui_tests.sh xvfb      [pytest args...]   # always-clean: kill any
#                                                 # existing Xvfb/fluxbox on
#                                                 # the target display first,
#                                                 # start fresh, tear down on
#                                                 # exit (default, use this
#                                                 # for trustworthy/
#                                                 # reproducible results)
#   run_ui_tests.sh xvfb-keep [pytest args...]   # reuse an already-running
#                                                 # display on the target if
#                                                 # present; otherwise start
#                                                 # one and leave it running
#                                                 # on exit (for iterative
#                                                 # work across many short
#                                                 # tool calls in one
#                                                 # session)
#
# Examples:
#   run_ui_tests.sh xvfb pytest tests/webnovels/ui_automation/test_menu_smoke.py -v
#   run_ui_tests.sh xvfb-keep pytest tests/webnovels/ui_automation/ -v

set -euo pipefail

DISPLAY_NUM=99
SCREEN_GEOMETRY="1920x1080x24"
TARGET_DISPLAY=":${DISPLAY_NUM}"
READY_TIMEOUT=10

XVFB_PID=""
FLUXBOX_PID=""
STARTED_XVFB=0
STARTED_FLUXBOX=0
TEARDOWN_ON_EXIT=1

usage() {
    echo "Usage: $(basename "$0") {xvfb|xvfb-keep} [pytest args...]" >&2
    exit 1
}

log() {
    echo "[run_ui_tests] $*" >&2
}

xvfb_pid_on_display() {
    pgrep -af "Xvfb ${TARGET_DISPLAY} " 2>/dev/null | grep -v "bin/bash -c" | awk '{print $1}' | head -1 || true
}

fluxbox_pid_on_display() {
    pgrep -af "fluxbox" 2>/dev/null | grep -v "bin/bash -c" | awk '{print $1}' | head -1 || true
}

display_is_live() {
    DISPLAY="${TARGET_DISPLAY}" xdpyinfo >/dev/null 2>&1
}

wait_for_display() {
    local deadline
    deadline=$((SECONDS + READY_TIMEOUT))
    while (( SECONDS < deadline )); do
        if display_is_live; then
            return 0
        fi
        sleep 0.2
    done
    return 1
}

wait_for_window_manager() {
    # getactivewindow is not a valid readiness signal -- with no window open,
    # a WM has nothing to make "active" yet, so it never succeeds even once
    # fluxbox is fully up. Poll for fluxbox registering _NET_SUPPORTING_WM_CHECK
    # on the root window instead (confirmed live: reads as "no such atom" for
    # a beat after fluxbox starts, then flips to a real window id once fluxbox
    # has actually claimed the WM role).
    local deadline
    deadline=$((SECONDS + READY_TIMEOUT))
    while (( SECONDS < deadline )); do
        local prop
        prop="$(DISPLAY="${TARGET_DISPLAY}" xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null || true)"
        if [[ "${prop}" == *"window id"* ]]; then
            return 0
        fi
        sleep 0.2
    done
    return 1
}

kill_existing_on_display() {
    local existing_xvfb existing_fluxbox
    existing_xvfb="$(xvfb_pid_on_display)"
    existing_fluxbox="$(fluxbox_pid_on_display)"
    if [[ -n "${existing_fluxbox}" ]]; then
        log "Killing existing fluxbox (pid ${existing_fluxbox})"
        kill -TERM "${existing_fluxbox}" 2>/dev/null || true
    fi
    if [[ -n "${existing_xvfb}" ]]; then
        log "Killing existing Xvfb on ${TARGET_DISPLAY} (pid ${existing_xvfb})"
        kill -TERM "${existing_xvfb}" 2>/dev/null || true
    fi
    if [[ -n "${existing_xvfb}${existing_fluxbox}" ]]; then
        sleep 1
    fi
}

start_xvfb() {
    log "Starting Xvfb ${TARGET_DISPLAY} -screen 0 ${SCREEN_GEOMETRY}"
    Xvfb "${TARGET_DISPLAY}" -screen 0 "${SCREEN_GEOMETRY}" >/tmp/run_ui_tests_xvfb.log 2>&1 &
    XVFB_PID=$!
    STARTED_XVFB=1
    if ! wait_for_display; then
        log "Xvfb did not become ready within ${READY_TIMEOUT}s"
        cat /tmp/run_ui_tests_xvfb.log >&2 || true
        exit 1
    fi
    log "Xvfb ready on ${TARGET_DISPLAY} (pid ${XVFB_PID})"
}

start_fluxbox() {
    log "Starting fluxbox on ${TARGET_DISPLAY}"
    DISPLAY="${TARGET_DISPLAY}" fluxbox >/tmp/run_ui_tests_fluxbox.log 2>&1 &
    FLUXBOX_PID=$!
    STARTED_FLUXBOX=1
    if ! wait_for_window_manager; then
        log "fluxbox did not become ready within ${READY_TIMEOUT}s"
        cat /tmp/run_ui_tests_fluxbox.log >&2 || true
        exit 1
    fi
    log "fluxbox ready on ${TARGET_DISPLAY} (pid ${FLUXBOX_PID})"
}

teardown() {
    if [[ "${TEARDOWN_ON_EXIT}" -ne 1 ]]; then
        log "xvfb-keep mode: leaving Xvfb/fluxbox running on ${TARGET_DISPLAY}"
        return
    fi
    if [[ "${STARTED_FLUXBOX}" -eq 1 && -n "${FLUXBOX_PID}" ]]; then
        log "Stopping fluxbox (pid ${FLUXBOX_PID})"
        kill -TERM "${FLUXBOX_PID}" 2>/dev/null || true
        wait "${FLUXBOX_PID}" 2>/dev/null || true
    fi
    if [[ "${STARTED_XVFB}" -eq 1 && -n "${XVFB_PID}" ]]; then
        log "Stopping Xvfb (pid ${XVFB_PID})"
        kill -TERM "${XVFB_PID}" 2>/dev/null || true
        wait "${XVFB_PID}" 2>/dev/null || true
    fi
}

trap teardown EXIT INT TERM

main() {
    if [[ $# -lt 1 ]]; then
        usage
    fi
    local mode="$1"
    shift
    if [[ $# -lt 1 ]]; then
        usage
    fi

    case "${mode}" in
        xvfb)
            TEARDOWN_ON_EXIT=1
            kill_existing_on_display
            start_xvfb
            start_fluxbox
            ;;
        xvfb-keep)
            TEARDOWN_ON_EXIT=0
            if display_is_live; then
                log "Reusing already-live display ${TARGET_DISPLAY}"
                if ! wait_for_window_manager; then
                    log "Display is live but no window manager detected; starting fluxbox"
                    start_fluxbox
                fi
            else
                start_xvfb
                start_fluxbox
            fi
            ;;
        *)
            usage
            ;;
    esac

    log "Running: DISPLAY=${TARGET_DISPLAY} $*"
    DISPLAY="${TARGET_DISPLAY}" "$@"
}

main "$@"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llama-cpp multi-server TUI monitor.

Polls three data sources per server host:
  1. GET /metrics          — llama-cpp inference stats (Prometheus)
  2. amdgpu_top --json     — AMD GPU / VRAM / clocks / power  (v0.11 schema)
  3. psutil                — CPU%, RSS, threads, I/O for the llama-server PID
                           — system-wide RAM, swap, per-core CPU

Logs     → logs/llama_monitor_<servers>_YYYYMMDD_HHMMSS.log
Raw dump → tmp/amdtop_<pid>_<ts>.json  (written once per process)

Remote hosts:
  # TODO: extract LocalCollector into llama_agent.py (FastAPI, GET /agent).
  #       Swap one line in poll_all() — no TUI changes needed.

Usage:
    python -m pyplayground.llama_monitor -s case=http://localhost:10000
    python -m pyplayground.llama_monitor -s case=http://localhost:10000 --debug
    python -m pyplayground.llama_monitor --config servers.json -i 5
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import psutil
from rich import box
from rich.table import Table
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Input, Label, Log, Sparkline, Static

# ─── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger("llama_monitor")


def _setup_logging(label: Optional[str] = None, level: int = logging.INFO) -> logging.Logger:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = "llama_monitor"
    if label:
        base = f"{base}_{label}"
    log_file = log_dir / f"{base}_{ts}.log"
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)
    root = logging.getLogger("llama_monitor")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(fh)
    root.addHandler(sh)
    root.info("Logging started → %s", log_file)
    return root


# ─── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_SERVERS = [
    {"name": "llama-1", "url": "http://localhost:8080"},
]

POLL_INTERVAL = 3.0
SPARKLINE_LEN = 40
AMDGPU_TIMEOUT = 6.0
_RAW_DUMP_DONE = False


# ─── amdgpu_top v0.11 JSON helpers ────────────────────────────────────────────
#
# Every sensor/activity value is:  {"value": N, "unit": "..."}   or null
# fdinfo entries are:  {pid_str: {"name": str, "usage": {"name": str, "usage": {...}}}}
# gpu_metrics values are bare numbers (or null), with special scaling:
#   average_socket_power  → milliwatts  (÷ 1000 = W)
#   temperature_gfx/soc   → millidegrees (÷ 100 = °C)


def _val(node, default: float = 0.0) -> float:
    """Unwrap {"value": N, "unit": "..."} or return bare number. Null → default."""
    if node is None:
        return default
    if isinstance(node, dict):
        v = node.get("value")
        if v is None:
            return default
        node = v
    try:
        return float(node)
    except (TypeError, ValueError):
        log.debug("_val: cannot convert %r to float", node)
        return default


def _dump_raw(raw: object) -> None:
    global _RAW_DUMP_DONE
    if _RAW_DUMP_DONE:
        return
    try:
        tmp_dir = Path("tmp")
        tmp_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        p = tmp_dir / f"amdtop_{os.getpid()}_{ts}.json"
        p.write_text(json.dumps(raw, indent=2, default=str))
        log.info("amdgpu_top raw JSON → %s", p)
        _RAW_DUMP_DONE = True
    except Exception as exc:
        log.warning("Could not dump raw JSON: %s", exc)


# ─── Data structures ───────────────────────────────────────────────────────────


@dataclass
class GpuMetrics:
    """Point-in-time view of AMD GPU and VRAM metrics."""

    available: bool = False
    error: str = ""
    # Memory
    vram_used_mib: float = 0.0
    vram_total_mib: float = 0.0
    gtt_used_mib: float = 0.0
    gtt_total_mib: float = 0.0
    # Activity
    gfx_pct: float = 0.0
    media_pct: float = 0.0
    # Clocks
    gfxclk_mhz: float = 0.0  # GFX_SCLK from Sensors
    mclk_mhz: float = 0.0  # GFX_MCLK (uclk)
    fclk_mhz: float = 0.0  # FCLK
    socclk_mhz: float = 0.0
    # Power / thermal
    avg_power_w: float = 0.0  # Sensors.Average Power
    gfx_power_w: float = 0.0  # Sensors.GFX Power
    edge_temp_c: float = 0.0  # Sensors.Edge Temperature
    cpu_tctl_c: float = 0.0  # Sensors.CPU Tctl
    gfx_temp_c: float = 0.0  # gpu_metrics.temperature_gfx ÷ 100
    soc_temp_c: float = 0.0  # gpu_metrics.temperature_soc ÷ 100
    socket_power_w: float = 0.0  # gpu_metrics.average_socket_power ÷ 1000
    # Per-process VRAM: {pid_int: vram_mib}
    fdinfo: dict = field(default_factory=dict)

    @property
    def vram_pct(self) -> float:
        """Return VRAM usage percentage based on used/total MiB."""
        return (self.vram_used_mib / self.vram_total_mib * 100) if self.vram_total_mib else 0.0

    @property
    def best_power_w(self) -> float:
        """Pick the most informative power reading available."""
        return self.socket_power_w or self.avg_power_w or self.gfx_power_w

    @property
    def best_temp_c(self) -> float:
        """Pick the most informative temperature reading available."""
        return self.edge_temp_c or self.gfx_temp_c or self.soc_temp_c


@dataclass
class ProcMetrics:
    """Per-process CPU, memory, I/O and VRAM metrics for llama-server."""

    available: bool = False
    error: str = ""
    pid: int = 0
    cpu_pct: float = 0.0
    rss_mib: float = 0.0
    vms_mib: float = 0.0
    num_threads: int = 0
    io_read_bps: float = 0.0
    io_write_bps: float = 0.0
    # VRAM from fdinfo cross-reference
    vram_mib: float = 0.0
    _prev_io_read: int = 0
    _prev_io_write: int = 0
    _prev_io_time: float = 0.0


@dataclass
class SysMetrics:
    """Host-wide CPU, memory, swap, load and uptime metrics."""

    cpu_pct_total: float = 0.0
    cpu_pct_cores: list = field(default_factory=list)
    mem_total_mib: float = 0.0
    mem_used_mib: float = 0.0
    mem_avail_mib: float = 0.0
    mem_buffers_mib: float = 0.0
    mem_cached_mib: float = 0.0
    mem_shared_mib: float = 0.0
    swap_total_mib: float = 0.0
    swap_used_mib: float = 0.0
    swap_cached_mib: float = 0.0
    load_1: float = 0.0
    load_5: float = 0.0
    load_15: float = 0.0
    # task / thread counts
    tasks_total: int = 0
    tasks_running: int = 0
    threads_total: int = 0
    kthreads: int = 0
    # uptime seconds
    uptime_s: float = 0.0

    @property
    def mem_pct(self) -> float:
        """Return percentage of system RAM currently used."""
        return (self.mem_used_mib / self.mem_total_mib * 100) if self.mem_total_mib else 0.0

    @property
    def uptime_str(self) -> str:
        """Return human-readable uptime string in days/hours/minutes/seconds."""
        s = int(self.uptime_s)
        d, s = divmod(s, 86400)
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return f"{d} days, {h:02d}:{m:02d}:{s:02d}" if d else f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class ServerMetrics:
    """Combined llama-server, GPU, process and system metrics for a single host."""

    name: str
    url: str
    reachable: bool = False
    last_updated: Optional[float] = None
    error: str = ""
    prompt_tokens_total: float = 0.0
    generated_tokens_total: float = 0.0
    n_busy: float = 0.0
    kv_cache_usage: float = 0.0
    kv_cache_tokens: float = 0.0
    requests_processing: float = 0.0
    requests_deferred: float = 0.0
    n_decode_total: float = 0.0
    prompt_seconds_total: float = 0.0
    predicted_seconds_total: float = 0.0
    n_tokens_max: float = 0.0
    tokens_per_sec_history: list = field(default_factory=list)
    prompt_tps_history: list = field(default_factory=list)
    _prev_generated: float = 0.0
    _prev_prompt: float = 0.0
    _prev_time: float = 0.0
    gpu: GpuMetrics = field(default_factory=GpuMetrics)
    proc: ProcMetrics = field(default_factory=ProcMetrics)
    sys: SysMetrics = field(default_factory=SysMetrics)

    @property
    def status_text(self) -> str:
        """Return a short ONLINE/OFFLINE status marker."""
        return "● ONLINE" if self.reachable else "○ OFFLINE"

    @property
    def status_color(self) -> str:
        """Return color name corresponding to current reachability."""
        return "bright_green" if self.reachable else "red"

    @property
    def current_tps(self) -> float:
        """Return most recent generated tokens/second value."""
        return self.tokens_per_sec_history[-1] if self.tokens_per_sec_history else 0.0

    @property
    def current_prompt_tps(self) -> float:
        """Return most recent prompt tokens/second value."""
        return self.prompt_tps_history[-1] if self.prompt_tps_history else 0.0

    @property
    def age_str(self) -> str:
        """Return age of the last successful metrics update."""
        if not self.last_updated:
            return "never"
        d = time.time() - self.last_updated
        return f"{d:.0f}s ago" if d < 60 else f"{d / 60:.1f}m ago"


# ─── Prometheus parser ─────────────────────────────────────────────────────────


def parse_prometheus(text: str) -> dict:
    """Parse Prometheus text exposition format into a flat metric dict."""
    out: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        m = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*(?:\{[^}]*\})?)\s+([\d.eE+\-nan]+)", line)
        if m:
            key = re.sub(r"\{[^}]*\}", "", m.group(1))
            try:
                out[key] = float(m.group(2))
            except ValueError:
                pass
    return out


# ─── Local Collector ───────────────────────────────────────────────────────────
# TODO: Remote support — extract into llama_agent.py (FastAPI GET /agent).
#       poll_all() calls httpx.get(f"{host}/agent") instead. Zero TUI changes.


class LocalCollector:
    """Local host collectors for GPU, process and system metrics."""

    # ── GPU via amdgpu_top v0.11 ─────────────────────────────────────────────

    @staticmethod
    async def fetch_gpu() -> GpuMetrics:
        """Invoke `amdgpu_top --json` once and parse GPU metrics."""
        g = GpuMetrics()
        log.debug("fetch_gpu: spawning amdgpu_top --json")
        try:
            proc = await asyncio.create_subprocess_exec(
                "amdgpu_top",
                "--json",
                "-d",
                "1",
                "-n",
                "1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=AMDGPU_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                g.error = "amdgpu_top timeout"
                log.warning("fetch_gpu: timed out after %.1fs", AMDGPU_TIMEOUT)
                return g

            if stderr:
                log.debug("amdgpu_top stderr: %s", stderr.decode(errors="replace").strip()[:200])

            raw_text = stdout.decode(errors="replace").strip()
            if not raw_text:
                g.error = "amdgpu_top: empty output"
                log.warning("fetch_gpu: empty stdout")
                return g

            # amdgpu_top --json may emit multiple frames; decode only the first
            raw = json.JSONDecoder().raw_decode(raw_text)[0]
            _dump_raw(raw)

            # v0.11 schema: {"amdgpu_top_version": {...}, "devices": [...]}
            if isinstance(raw, dict) and "devices" in raw:
                ver = raw.get("amdgpu_top_version", {})
                log.debug("fetch_gpu: amdgpu_top v%s.%s.%s", ver.get("major", "?"), ver.get("minor", "?"), ver.get("patch", "?"))
                devices = raw["devices"]
            elif isinstance(raw, list):
                devices = raw
            else:
                devices = [raw]

            if not devices:
                g.error = "amdgpu_top: no devices in output"
                return g

            dev = devices[0]  # APU = single GPU
            log.debug("fetch_gpu: device keys=%s", list(dev.keys()))

            # ── VRAM  {"Total VRAM": {value, unit}, "Total VRAM Usage": ...}
            vram_sec = dev.get("VRAM", {})
            g.vram_total_mib = _val(vram_sec.get("Total VRAM"))
            g.vram_used_mib = _val(vram_sec.get("Total VRAM Usage"))
            g.gtt_total_mib = _val(vram_sec.get("Total GTT"))
            g.gtt_used_mib = _val(vram_sec.get("Total GTT Usage"))
            log.debug("fetch_gpu: VRAM used=%.0f/%.0f MiB", g.vram_used_mib, g.vram_total_mib)

            # ── Activity  {"GFX": {value, unit}, "MediaEngine": ..., "Memory": ...}
            act = dev.get("gpu_activity", {})
            g.gfx_pct = _val(act.get("GFX"))
            g.media_pct = _val(act.get("MediaEngine"))
            log.debug("fetch_gpu: GFX=%.1f%% Media=%.1f%%", g.gfx_pct, g.media_pct)

            # ── Sensors  all {"value": N, "unit": "..."} or None
            sen = dev.get("Sensors", {})
            g.gfxclk_mhz = _val(sen.get("GFX_SCLK"))
            g.mclk_mhz = _val(sen.get("GFX_MCLK"))
            g.fclk_mhz = _val(sen.get("FCLK"))
            g.avg_power_w = _val(sen.get("Average Power"))
            g.gfx_power_w = _val(sen.get("GFX Power"))
            g.edge_temp_c = _val(sen.get("Edge Temperature"))
            g.cpu_tctl_c = _val(sen.get("CPU Tctl"))
            log.debug("fetch_gpu: SCLK=%.0f MCLK=%.0f FCLK=%.0f Power=%.1fW EdgeTemp=%.1f°C", g.gfxclk_mhz, g.mclk_mhz, g.fclk_mhz, g.avg_power_w, g.edge_temp_c)

            # ── gpu_metrics  bare numbers, special scaling
            gm = dev.get("gpu_metrics", {})
            raw_pwr = gm.get("average_socket_power")  # milliwatts
            raw_tgfx = gm.get("temperature_gfx")  # millidegrees C
            raw_tsoc = gm.get("temperature_soc")
            if raw_pwr is not None:
                g.socket_power_w = raw_pwr / 1000.0
            if raw_tgfx is not None:
                g.gfx_temp_c = raw_tgfx / 100.0
            if raw_tsoc is not None:
                g.soc_temp_c = raw_tsoc / 100.0
            # clocks from gpu_metrics as fallback if Sensors gave 0
            if g.gfxclk_mhz == 0:
                g.gfxclk_mhz = float(gm.get("average_gfxclk_frequency") or 0)
            if g.fclk_mhz == 0:
                g.fclk_mhz = float(gm.get("average_fclk_frequency") or 0)
            if g.mclk_mhz == 0:
                g.mclk_mhz = float(gm.get("average_uclk_frequency") or 0)
            g.socclk_mhz = float(gm.get("average_socclk_frequency") or 0)
            log.debug("fetch_gpu: socket_power=%.2fW gfx_temp=%.1f°C soc_temp=%.1f°C", g.socket_power_w, g.gfx_temp_c, g.soc_temp_c)

            # ── fdinfo  {pid_str: {"name": str, "usage": {"name":str, "usage": {...}}}}
            fdinfo_raw = dev.get("fdinfo", {})
            for pid_str, entry in fdinfo_raw.items():
                if not isinstance(entry, dict):
                    continue
                try:
                    pid = int(pid_str)
                    name = entry.get("name", "")
                    # double-nested: entry["usage"]["usage"]["VRAM"]
                    inner = entry.get("usage", {}).get("usage", {})
                    vram = _val(inner.get("VRAM"))
                    gtt = _val(inner.get("GTT"))
                    g.fdinfo[pid] = {"name": name, "vram": vram, "gtt": gtt}
                    log.debug("fetch_gpu: fdinfo pid=%d name=%s VRAM=%.0f GTT=%.0f", pid, name, vram, gtt)
                except (ValueError, AttributeError) as exc:
                    log.debug("fetch_gpu: fdinfo parse error pid=%s: %s", pid_str, exc)

            g.available = True
            log.info(
                "fetch_gpu OK  VRAM=%0.f/%0.f MiB  GFX=%.1f%%  " "Power=%.1fW  SCLK=%.0f  FCLK=%.0f  MCLK=%.0f  " "EdgeTemp=%.1f°C  CPUTctl=%.1f°C",
                g.vram_used_mib,
                g.vram_total_mib,
                g.gfx_pct,
                g.best_power_w,
                g.gfxclk_mhz,
                g.fclk_mhz,
                g.mclk_mhz,
                g.best_temp_c,
                g.cpu_tctl_c,
            )

        except FileNotFoundError:
            g.error = "amdgpu_top not found in PATH"
            log.warning("fetch_gpu: amdgpu_top not found")
        except json.JSONDecodeError as exc:
            g.error = f"JSON error: {exc}"
            log.error("fetch_gpu: JSON decode failed: %s", exc)
        except Exception as exc:
            g.error = str(exc)[:80]
            log.exception("fetch_gpu: unexpected error")

        return g

    # ── Process ──────────────────────────────────────────────────────────────

    @staticmethod
    def find_llama_pid(port: int) -> Optional[int]:
        """Best-effort search for the llama-server PID listening on the given port."""
        candidates = []
        for p in psutil.process_iter(["pid", "cmdline", "name"]):
            try:
                cmdline = " ".join(p.info["cmdline"] or [])
                name = p.info["name"] or ""
                if "llama" not in cmdline.lower() and "llama" not in name.lower():
                    continue
                if str(port) in cmdline:
                    log.debug("find_llama_pid: port match pid=%d port=%d", p.pid, port)
                    return p.pid
                candidates.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if candidates:
            log.debug("find_llama_pid: fallback pid=%d (port %d not found in cmdline)", candidates[0].pid, port)
            return candidates[0].pid
        log.warning("find_llama_pid: no llama process found (port=%d)", port)
        return None

    @staticmethod
    def collect_proc(prev: ProcMetrics, port: int, gpu: GpuMetrics) -> ProcMetrics:
        """Collect CPU, memory, I/O and VRAM metrics for the llama-server process."""
        p = ProcMetrics()
        try:
            pid = LocalCollector.find_llama_pid(port)
            if pid is None:
                p.error = "llama-server PID not found"
                return p

            proc = psutil.Process(pid)
            p.pid = pid
            p.cpu_pct = proc.cpu_percent(interval=None)
            mem = proc.memory_info()
            p.rss_mib = mem.rss / 1024 / 1024
            p.vms_mib = mem.vms / 1024 / 1024
            p.num_threads = proc.num_threads()

            # Cross-reference VRAM from amdgpu_top fdinfo
            if pid in gpu.fdinfo:
                p.vram_mib = gpu.fdinfo[pid]["vram"]

            now = time.time()
            try:
                io = proc.io_counters()
                if prev.available and prev._prev_io_time > 0:
                    dt = now - prev._prev_io_time
                    if dt > 0:
                        p.io_read_bps = max(0, (io.read_bytes - prev._prev_io_read) / dt)
                        p.io_write_bps = max(0, (io.write_bytes - prev._prev_io_write) / dt)
                p._prev_io_read = io.read_bytes
                p._prev_io_write = io.write_bytes
            except (psutil.AccessDenied, AttributeError) as exc:
                log.debug("collect_proc: io_counters unavailable pid=%d: %s", pid, exc)
                p._prev_io_read = prev._prev_io_read
                p._prev_io_write = prev._prev_io_write
            p._prev_io_time = now
            p.available = True
            log.debug("collect_proc: pid=%d cpu=%.1f%% rss=%.1fMiB vram=%.0fMiB threads=%d", pid, p.cpu_pct, p.rss_mib, p.vram_mib, p.num_threads)

        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            p.error = str(exc)[:80]
            log.warning("collect_proc: psutil error: %s", exc)
        except Exception as exc:
            p.error = str(exc)[:80]
            log.exception("collect_proc: unexpected error")
        return p

    # ── System ───────────────────────────────────────────────────────────────

    @staticmethod
    def collect_sys() -> SysMetrics:
        """Collect host-wide CPU, memory, swap, load and uptime metrics."""
        s = SysMetrics()
        try:
            s.cpu_pct_total = psutil.cpu_percent(interval=None)
            s.cpu_pct_cores = psutil.cpu_percent(interval=None, percpu=True)

            vm = psutil.virtual_memory()
            s.mem_total_mib = vm.total / 1024 / 1024
            s.mem_used_mib = vm.used / 1024 / 1024
            s.mem_avail_mib = vm.available / 1024 / 1024
            s.mem_shared_mib = getattr(vm, "shared", 0) / 1024 / 1024
            s.mem_buffers_mib = getattr(vm, "buffers", 0) / 1024 / 1024
            s.mem_cached_mib = getattr(vm, "cached", 0) / 1024 / 1024

            sw = psutil.swap_memory()
            s.swap_total_mib = sw.total / 1024 / 1024
            s.swap_used_mib = sw.used / 1024 / 1024
            s.swap_cached_mib = getattr(sw, "sin", 0) / 1024 / 1024  # Linux sin ≈ cached

            la = psutil.getloadavg()
            s.load_1, s.load_5, s.load_15 = la

            # Task / thread counts
            procs = list(psutil.process_iter(["status", "num_threads"]))
            s.tasks_total = len(procs)
            s.tasks_running = sum(1 for p in procs if p.info.get("status") == psutil.STATUS_RUNNING)
            s.threads_total = sum(p.info.get("num_threads") or 0 for p in procs)
            # kernel threads: name in brackets, or ppid==2, or pid==2
            try:
                s.kthreads = sum(
                    1 for p in psutil.process_iter(["pid", "ppid", "name"]) if p.info["ppid"] in (0, 2) or p.info["pid"] == 2 or (p.info["name"] or "").startswith("[")
                )
            except Exception:
                s.kthreads = 0

            # Uptime
            s.uptime_s = time.time() - psutil.boot_time()

            log.debug(
                "collect_sys: cpu=%.1f%% mem=%.0f/%.0fMiB tasks=%d threads=%d load=%.2f uptime=%s",
                s.cpu_pct_total,
                s.mem_used_mib,
                s.mem_total_mib,
                s.tasks_total,
                s.threads_total,
                s.load_1,
                s.uptime_str,
            )
        except Exception as exc:
            log.exception("collect_sys: error: %s", exc)
        return s


# ─── llama /metrics ────────────────────────────────────────────────────────────

_METRICS_DUMP_DONE: set = set()  # per-url, dump raw metrics once for key inspection


async def fetch_llama_metrics(url: str, timeout: float = 5.0) -> tuple:
    """Fetch and parse the llama-server /metrics endpoint for a single URL."""
    log.debug("fetch_llama: GET %s/metrics", url)
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{url}/metrics", timeout=timeout)
            r.raise_for_status()
            data = parse_prometheus(r.text)
            log.debug("fetch_llama: %s -> %d metrics parsed", url, len(data))

            # On first successful fetch (per-process), dump raw text + key list so we can
            # verify the exact Prometheus metric names this llama-server emits.
            if url not in _METRICS_DUMP_DONE:
                _METRICS_DUMP_DONE.add(url)
                try:
                    safe = re.sub(r"[^a-zA-Z0-9]", "_", url)
                    tmp_dir = Path("tmp")
                    tmp_dir.mkdir(exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    p = tmp_dir / f"llama_metrics_{safe}_{os.getpid()}_{ts}.txt"
                    p.write_text(r.text)
                    log.info("raw /metrics dump -> %s", p)
                except Exception:
                    pass
                log.info("fetch_llama keys [%s]: %s", url, sorted(data.keys()))

            return True, data, ""
    except Exception as exc:
        log.warning("fetch_llama: %s error: %s", url, exc)
        return False, {}, str(exc)


def _pick(raw: dict, *keys, default: float = 0.0) -> float:
    """Return first matching key value from raw metrics dict."""
    for k in keys:
        if k in raw:
            return float(raw[k])
    return default


def apply_llama_metrics(s: ServerMetrics, raw: dict, now: float) -> None:
    """Parse llama-server Prometheus metrics.

    This server emits the llamacpp: prefix schema.  Key observations:
      - Throughput is exposed directly as gauges (no delta needed):
          llamacpp:predicted_tokens_seconds   — gen t/s
          llamacpp:prompt_tokens_seconds      — prompt t/s
      - Cumulative counters also present (used for sparkline history):
          llamacpp:tokens_predicted_total
          llamacpp:prompt_tokens_total
      - No kv_cache_usage_ratio or n_busy in this version; derived from
          llamacpp:n_busy_slots_per_decode  (avg busy slots per decode call)
    """
    s.reachable = True
    s.last_updated = now
    s.error = ""

    # ── Direct throughput gauges (most reliable — no delta math) ─────────────
    gen_tps_gauge = _pick(
        raw,
        "llamacpp:predicted_tokens_seconds",  # this server
        "llama_tokens_predicted_seconds",
        "predicted_tokens_seconds",
    )
    prompt_tps_gauge = _pick(
        raw,
        "llamacpp:prompt_tokens_seconds",  # this server
        "llama_prompt_tokens_seconds",
        "prompt_tokens_seconds",
    )

    # ── Cumulative counters (for delta sparkline) ─────────────────────────────
    s.prompt_tokens_total = _pick(
        raw,
        "llamacpp:prompt_tokens_total",
        "llama_prompt_tokens_total",
        "prompt_tokens_total",
    )
    s.generated_tokens_total = _pick(
        raw,
        "llamacpp:tokens_predicted_total",
        "llama_tokens_predicted_total",
        "llama_generated_tokens_total",
        "tokens_predicted_total",
    )

    # ── Busy / KV ─────────────────────────────────────────────────────────────
    s.n_busy = _pick(
        raw,
        "llamacpp:n_busy_slots_per_decode",  # this server (avg, not instantaneous)
        "llama_n_busy",
        "n_busy_slots_per_decode",
    )
    kv_ratio = _pick(
        raw,
        "llamacpp:kv_cache_usage_ratio",
        "llama_kv_cache_usage_ratio",
        "kv_cache_usage_ratio",
    )
    s.kv_cache_usage = kv_ratio * 100.0
    s.kv_cache_tokens = _pick(
        raw,
        "llamacpp:kv_cache_tokens_count",
        "llama_kv_cache_tokens_count",
        "llama_kv_cache_tokens",
        "kv_cache_tokens_count",
    )
    s.requests_processing = _pick(
        raw,
        "llamacpp:requests_processing",
        "llama_requests_processing",
        "requests_processing",
    )
    s.requests_deferred = _pick(
        raw,
        "llamacpp:requests_deferred",
        "llama_requests_deferred",
        "requests_deferred",
    )
    s.n_decode_total = _pick(raw, "llamacpp:n_decode_total", "llama_n_decode_total")
    s.n_tokens_max = _pick(raw, "llamacpp:n_tokens_max", "llama_n_tokens_max")
    s.prompt_seconds_total = _pick(raw, "llamacpp:prompt_seconds_total", "llama_prompt_seconds_total")
    s.predicted_seconds_total = _pick(raw, "llamacpp:tokens_predicted_seconds_total", "llama_tokens_predicted_seconds_total")

    log.debug(
        "apply_llama [%s]: gen_tps_gauge=%.2f prompt_tps_gauge=%.2f " "gen_total=%.0f prompt_total=%.0f kv=%.1f%% busy=%.1f proc=%d",
        s.name,
        gen_tps_gauge,
        prompt_tps_gauge,
        s.generated_tokens_total,
        s.prompt_tokens_total,
        s.kv_cache_usage,
        s.n_busy,
        s.requests_processing,
    )

    # ── Sparkline history ─────────────────────────────────────────────────────
    # Prefer the direct gauge; fall back to delta from counters
    if s._prev_time > 0:
        dt = now - s._prev_time
        if dt > 0:
            # Use gauge if nonzero, else compute delta
            gen_tps = gen_tps_gauge if gen_tps_gauge > 0 else max(0.0, (s.generated_tokens_total - s._prev_generated) / dt)
            prompt_tps = prompt_tps_gauge if prompt_tps_gauge > 0 else max(0.0, (s.prompt_tokens_total - s._prev_prompt) / dt)
            s.tokens_per_sec_history.append(gen_tps)
            s.prompt_tps_history.append(prompt_tps)
            for lst in (s.tokens_per_sec_history, s.prompt_tps_history):
                if len(lst) > SPARKLINE_LEN:
                    lst.pop(0)
    else:
        # First poll — seed with gauge values so display is immediate
        if gen_tps_gauge > 0:
            s.tokens_per_sec_history.append(gen_tps_gauge)
        if prompt_tps_gauge > 0:
            s.prompt_tps_history.append(prompt_tps_gauge)

    s._prev_generated = s.generated_tokens_total
    s._prev_prompt = s.prompt_tokens_total
    s._prev_time = now


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _bar(value: float, maximum: float, width: int = 14) -> str:
    pct = min(value / maximum, 1.0) if maximum else 0.0
    filled = int(pct * width)
    color = "green" if pct < 0.60 else ("yellow" if pct < 0.85 else "red")
    return f"[{color}]{'█' * filled}{'░' * (width - filled)}[/]"


def _fmt_bps(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024**2:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / 1024 ** 2:.1f} MB/s"


def _tc(c: float, use_f: bool) -> str:
    """Format temperature in C or F."""
    if use_f:
        return f"{c * 9 / 5 + 32:.1f}°F"
    return f"{c:.1f}°C"


def _port_from_url(url: str) -> int:
    m = re.search(r":(\d+)", url.split("//")[-1])
    return int(m.group(1)) if m else 8080


def _safe(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", name)


def _cores_sparkline(cores: list) -> str:
    """Compact per-core bar: one braille/block char per core for inline use."""
    if not cores:
        return "[dim]—[/]"
    chars = " ▁▂▃▄▅▆▇█"
    parts = []
    for pct in cores:
        idx = min(int(pct / 100 * 8), 8)
        color = "green" if pct < 50 else ("yellow" if pct < 80 else "red")
        parts.append(f"[{color}]{chars[idx]}[/]")
    return "".join(parts)


def _mini_core_bar(pct: float, w: int = 4) -> str:
    """Tiny filled bar for inline per-core display, handles zero-fill correctly."""
    filled = int(min(pct / 100.0, 1.0) * w)
    empty = w - filled
    color = "green" if pct < 60 else ("yellow" if pct < 85 else "red")
    # always emit at least the empty section so markup is never empty-tag
    bar = (f"[{color}]{'█' * filled}[/]" if filled else "") + (f"[dim]{'░' * empty}[/]" if empty else "")
    return bar


# ─── System Panel (compact 3-line header) ──────────────────────────────────────


class SysPanel(Widget):
    """Single-line system bar: mem + swap + tasks + load + uptime."""

    DEFAULT_CSS = """
    SysPanel {
        height: 1;
        padding: 0 1;
        border-bottom: solid $primary-darken-2;
        background: $surface-darken-1;
    }
    """

    def compose(self) -> ComposeResult:
        """Create the inner static widget used for rendering."""
        yield Static("", id="syspanel_body")

    def refresh_data(self, sy: SysMetrics) -> None:
        """Update the system panel with the latest `SysMetrics` sample."""

        def _g(v: float) -> str:
            return f"{v / 1024:.1f}G" if v >= 1024 else f"{v:.0f}M"

        mem_bar = _bar(sy.mem_used_mib, sy.mem_total_mib, width=10)
        swap_bar = _bar(sy.swap_used_mib, sy.swap_total_mib, width=6) if sy.swap_total_mib else ""

        line = (
            f"[dim]Mem[/] {mem_bar} [bold]{_g(sy.mem_used_mib)}[/][dim]/{_g(sy.mem_total_mib)}[/]"
            f"  [dim]buf:{_g(sy.mem_buffers_mib)} cache:{_g(sy.mem_cached_mib)} avail:[/][bold green]{_g(sy.mem_avail_mib)}[/]"
            f"    [dim]Swp[/] {swap_bar} [bold]{_g(sy.swap_used_mib)}[/][dim]/{_g(sy.swap_total_mib)}[/]"
            f"    [dim]Tasks:[/] [bold]{sy.tasks_total}[/][dim] ({sy.threads_total} thr  {sy.kthreads} kthr)"
            f"  {sy.tasks_running} running[/]"
            f"    [dim]Load:[/] [bold]{sy.load_1:.2f}[/] [dim]{sy.load_5:.2f} {sy.load_15:.2f}[/]"
            f"    [dim]Up:[/] [bold cyan]{sy.uptime_str}[/]"
        )
        self.query_one("#syspanel_body", Static).update(line)


# ─── Server Card ───────────────────────────────────────────────────────────────


class ServerCard(Widget):
    """Per-server detailed card combining inference, GPU, process and system data."""

    DEFAULT_CSS = """
    ServerCard {
        border: solid $primary-darken-2;
        padding: 0 1;
        height: auto;
        min-width: 80;
    }
    ServerCard.offline {
        border: solid $error-darken-2;
        opacity: 0.60;
    }
    ServerCard .spark-label {
        color: $text-muted;
        margin-top: 1;
    }
    """

    def __init__(self, server: ServerMetrics, **kwargs):
        super().__init__(**kwargs)
        self.server = server

    def _sid(self, suffix: str) -> str:
        """Return a stable element id suffix for this server card."""
        return f"_{_safe(self.server.name)}_{suffix}"

    def compose(self) -> ComposeResult:
        """Compose the child widgets that make up the server card."""
        sid = self._sid
        yield Label("", id=sid("title"))
        yield Label(f"[dim]{self.server.url}[/]")
        # top split: inference | gpu  — single Static, rendered as Rich Table
        yield Static("", id=sid("top_split"))
        # bottom split: process | system — single Static, rendered as Rich Table
        yield Static("", id=sid("bot_split"))
        yield Label("gen t/s", classes="spark-label")
        yield Sparkline([], id=sid("spark_gen"), summary_function=max)
        yield Label("prompt t/s", classes="spark-label")
        yield Sparkline([], id=sid("spark_prompt"), summary_function=max)

    def refresh_data(self, use_fahrenheit: bool = False) -> None:
        """Refresh card contents from the latest metrics and temperature preference."""
        s = self.server
        sid = self._sid

        self.query_one(f"#{sid('title')}", Label).update(f"[bold]{s.name}[/]  [{s.status_color}]{s.status_text}[/]")
        self.set_class(not s.reachable, "offline")

        def _g(v: float) -> str:
            return f"{v / 1024:.1f}G" if v >= 1024 else f"{v:.0f}M"

        def _split_table() -> Table:
            t = Table(box=None, show_header=False, expand=True, padding=(0, 1), show_edge=False)
            t.add_column("left", ratio=1)
            t.add_column("right", ratio=1)
            return t

        nl = "\n"

        # ══ TOP SPLIT: Inference (left) | GPU (right) ════════════════════════
        g = s.gpu

        if not s.reachable:
            inf_lines = "[red]" + s.error[:60] + "[/]" + nl + "[dim]Last seen: " + s.age_str + "[/]"
        else:
            kv_bar = _bar(s.kv_cache_usage, 100, width=12)
            avg_gen_ms = (s.predicted_seconds_total / s.n_decode_total * 1000) if s.n_decode_total > 0 else 0.0
            avg_prompt_ms = s.prompt_seconds_total / max(s.prompt_tokens_total, 1) * 1000
            rows = [
                "[bold cyan]\u2500\u2500 Inference \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/]",
                f"[dim]{'Gen t/s':<20}[/] [bold cyan]{s.current_tps:>8.1f}[/]  [dim]avg {avg_gen_ms:.1f}ms[/]",
                f"[dim]{'Prompt t/s':<20}[/] [bold yellow]{s.current_prompt_tps:>8.1f}[/]  [dim]avg {avg_prompt_ms:.3f}ms[/]",
                f"[dim]{'KV cache':<20}[/] {kv_bar} [bold]{s.kv_cache_usage:>5.1f}%[/]",
                f"[dim]{'KV tokens':<20}[/] [bold]{int(s.kv_cache_tokens):>8,}[/]",
                f"[dim]{'Busy slots':<20}[/] [bold]{s.n_busy:>8.1f}[/]",
                f"[dim]{'Req processing':<20}[/] [bold]{int(s.requests_processing):>8}[/]",
                f"[dim]{'Req deferred':<20}[/] [bold]{int(s.requests_deferred):>8}[/]",
                f"[dim]{'Total gen tokens':<20}[/] [bold]{int(s.generated_tokens_total):>8,}[/]",
                f"[dim]{'Total prompt tok':<20}[/] [bold]{int(s.prompt_tokens_total):>8,}[/]",
                f"[dim]{'Decode calls':<20}[/] [bold]{int(s.n_decode_total):>8,}[/]",
                f"[dim]{'Updated':<20}[/] [dim]{s.age_str:>8}[/]",
            ]
            inf_lines = nl.join(rows)

        if not g.available:
            gpu_lines = "[bold magenta]\u2500\u2500 GPU  (amdgpu_top v0.11) \u2500\u2500\u2500\u2500\u2500\u2500[/]" + nl + "[dim red]" + (g.error or "no data yet") + "[/]"
        else:
            vram_bar = _bar(g.vram_used_mib, g.vram_total_mib, width=12)
            gtt_bar = _bar(g.gtt_used_mib, g.gtt_total_mib, width=12)
            gfx_bar = _bar(g.gfx_pct, 100, width=12)
            rows = [
                "[bold magenta]\u2500\u2500 GPU  (amdgpu_top v0.11) \u2500\u2500\u2500\u2500\u2500\u2500[/]",
                f"[dim]{'VRAM':<16}[/] {vram_bar} [bold]{g.vram_used_mib:>6.0f}[/][dim]/{g.vram_total_mib:.0f} MiB[/]",
                f"[dim]{'GTT':<16}[/] {gtt_bar} [bold]{g.gtt_used_mib:>6.0f}[/][dim]/{g.gtt_total_mib:.0f} MiB[/]",
                f"[dim]{'GFX':<16}[/] {gfx_bar} [bold]{g.gfx_pct:>5.1f}%[/]",
                f"[dim]{'Socket power':<16}[/] [bold magenta]{g.best_power_w:>5.1f}W[/]",
                f"[dim]{'Edge temp':<16}[/] [bold red]{_tc(g.best_temp_c, use_fahrenheit)}[/]  [dim]tctl {_tc(g.cpu_tctl_c, use_fahrenheit)}  soc {_tc(g.soc_temp_c, use_fahrenheit)}[/]",
                f"[dim]{'GFX_SCLK':<16}[/] [bold]{g.gfxclk_mhz:>5.0f}[/] [dim]MHz[/]",
                f"[dim]{'FCLK':<16}[/] [bold]{g.fclk_mhz:>5.0f}[/] [dim]MHz[/]",
                f"[dim]{'MCLK (uclk)':<16}[/] [bold]{g.mclk_mhz:>5.0f}[/] [dim]MHz[/]",
                f"[dim]{'SOCCLK':<16}[/] [bold]{g.socclk_mhz:>5.0f}[/] [dim]MHz[/]",
            ]
            gpu_lines = nl.join(rows)

        top = _split_table()
        top.add_row(inf_lines, gpu_lines)
        self.query_one(f"#{sid('top_split')}", Static).update(top)

        # ══ BOTTOM SPLIT: Process (left) | System (right) ════════════════════
        p = s.proc
        sy = s.sys

        if not p.available:
            proc_lines = (
                "[bold green]\u2500\u2500 Process  (psutil) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/]" + nl + "[dim red]" + (p.error or "no data yet") + "[/]"
            )
        else:
            rows = [
                "[bold green]\u2500\u2500 Process  (psutil) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/]",
                f"[dim]{'PID':<18}[/] [bold]{p.pid:>8}[/]",
                f"[dim]{'CPU %':<18}[/] [bold cyan]{p.cpu_pct:>8.1f}%[/]",
                f"[dim]{'RSS':<18}[/] [bold]{p.rss_mib:>8.1f}[/] [dim]MiB[/]",
                f"[dim]{'Threads':<18}[/] [bold]{p.num_threads:>8}[/]",
                f"[dim]{'I/O read':<18}[/] [bold]{_fmt_bps(p.io_read_bps):>12}[/]",
                f"[dim]{'I/O write':<18}[/] [bold]{_fmt_bps(p.io_write_bps):>12}[/]",
            ]
            if p.vram_mib > 0:
                rows.append(f"[dim]{'VRAM (fdinfo)':<18}[/] [bold magenta]{p.vram_mib:>6.0f}[/] [dim]MiB[/]")
            proc_lines = nl.join(rows)

        cores = _cores_sparkline(sy.cpu_pct_cores)
        sys_rows = [
            "[bold yellow]\u2500\u2500 System \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/]",
            f"[dim]{'CPU':<18}[/] [bold cyan]{sy.cpu_pct_total:>5.1f}%[/]  {cores}",
            f"[dim]{'load':<18}[/] [bold]{sy.load_1:.2f}[/] [dim]{sy.load_5:.2f} {sy.load_15:.2f}[/]",
            f"[dim]{'RAM':<18}[/] {_bar(sy.mem_used_mib, sy.mem_total_mib, 12)} [bold]{_g(sy.mem_used_mib)}[/][dim]/{_g(sy.mem_total_mib)}[/]",
            f"[dim]{'  avail':<18}[/] [bold green]{_g(sy.mem_avail_mib)}[/]  [dim]buf:{_g(sy.mem_buffers_mib)} cache:{_g(sy.mem_cached_mib)}[/]",
            f"[dim]{'Swap':<18}[/] {_bar(sy.swap_used_mib, sy.swap_total_mib, 12) if sy.swap_total_mib else '[dim]\u2014[/]'} [bold]{_g(sy.swap_used_mib)}[/][dim]/{_g(sy.swap_total_mib)}[/]",
            f"[dim]{'Tasks':<18}[/] [bold]{sy.tasks_total}[/][dim] / {sy.threads_total} thr / {sy.kthreads} kthr[/]",
            f"[dim]{'Uptime':<18}[/] [bold cyan]{sy.uptime_str}[/]",
        ]
        sys_lines = nl.join(sys_rows)

        bot = _split_table()
        bot.add_row(proc_lines, sys_lines)
        self.query_one(f"#{sid('bot_split')}", Static).update(bot)

        # ── Sparklines
        self.query_one(f"#{sid('spark_gen')}", Sparkline).data = s.tokens_per_sec_history or [0.0]
        self.query_one(f"#{sid('spark_prompt')}", Sparkline).data = s.prompt_tps_history or [0.0]


# ─── Summary Table ─────────────────────────────────────────────────────────────


class SummaryTable(Widget):
    """Compact tabular overview of all configured servers."""

    DEFAULT_CSS = """
    SummaryTable {
        height: auto;
        padding: 0 1;
        border-bottom: solid $primary-darken-3;
    }
    """

    def compose(self) -> ComposeResult:
        """Create the static container used for rendering the Rich table."""
        yield Static("", id="summary_static")

    def refresh_data(self, servers: list, use_f: bool = False) -> None:
        """Render the summary table for the given servers."""
        t = Table(
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold dim",
            expand=True,
            padding=(0, 1),
        )
        for col, kw in [
            ("", {}),
            ("Name", {"style": "bold"}),
            ("URL", {"style": "dim"}),
            ("Gen t/s", {"justify": "right"}),
            ("Prompt t/s", {"justify": "right"}),
            ("KV%", {"justify": "right"}),
            ("VRAM%", {"justify": "right"}),
            ("GFX%", {"justify": "right"}),
            ("CPU%", {"justify": "right"}),
            ("RAM%", {"justify": "right"}),
            ("Pwr W", {"justify": "right"}),
            ("Temp", {"justify": "right"}),
        ]:
            t.add_column(col, **kw)

        for s in servers:
            g, p, sy = s.gpu, s.proc, s.sys
            t.add_row(
                "[bright_green]●[/]" if s.reachable else "[red]○[/]",
                s.name,
                s.url,
                f"{s.current_tps:.1f}" if s.reachable else "—",
                f"{s.current_prompt_tps:.1f}" if s.reachable else "—",
                f"{s.kv_cache_usage:.1f}%" if s.reachable else "—",
                f"{g.vram_pct:.1f}%" if g.available else "—",
                f"{g.gfx_pct:.1f}%" if g.available else "—",
                f"{p.cpu_pct:.1f}%" if p.available else "—",
                f"{sy.mem_pct:.1f}%" if sy.mem_total_mib else "—",
                f"{g.best_power_w:.1f}W" if g.available else "—",
                (_tc(g.best_temp_c, use_f) if g.available else "—"),
            )

        self.query_one("#summary_static", Static).update(t)


# ─── Add-Server Screen ─────────────────────────────────────────────────────────


class AddServerScreen(Screen):
    """Modal dialog for interactively adding a new monitored server."""

    DEFAULT_CSS = """
    AddServerScreen { align: center middle; }
    #dialog {
        width: 62; height: auto;
        border: double $accent; padding: 2 4; background: $surface;
    }
    """
    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        """Build the dialog layout with name and URL inputs."""
        with Container(id="dialog"):
            yield Label("[bold]Add Server[/]\n")
            yield Label("Name:")
            yield Input(placeholder="llama-2", id="inp_name")
            yield Label("URL:")
            yield Input(placeholder="http://hostname:8080", id="inp_url")
            yield Label("")
            with Horizontal():
                yield Button("Add", variant="primary", id="btn_add")
                yield Button("Cancel", id="btn_cancel")

    @on(Button.Pressed, "#btn_add")
    def do_add(self):
        """Validate inputs and dismiss with the new server configuration."""
        name = self.query_one("#inp_name", Input).value.strip()
        url = self.query_one("#inp_url", Input).value.strip().rstrip("/")
        self.dismiss({"name": name, "url": url} if name and url else None)

    @on(Button.Pressed, "#btn_cancel")
    def do_cancel(self):
        """Dismiss the dialog without adding a server."""
        self.dismiss(None)


# ─── Main App ──────────────────────────────────────────────────────────────────


class LlamaMonitor(App):
    """Textual TUI application that monitors one or more llama-cpp servers."""

    CSS = """
    Screen { background: $background; }
    #cards_container {
        layout: grid;
        grid-size: 2;
        grid-gutter: 0;
        height: auto;
        padding: 0;
    }
    #log_panel {
        height: 7;
        border-top: solid $primary-darken-3;
        padding: 0 1;
    }
    #statusbar {
        height: 1;
        background: $primary-darken-3;
        padding: 0 2;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("a", "add_server", "Add Server"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("1", "set_cols(1)", "1-col"),
        Binding("2", "set_cols(2)", "2-col"),
        Binding("3", "set_cols(3)", "3-col"),
        Binding("t", "toggle_temp", "°C/°F"),
    ]

    TITLE = "llama-cpp Server Monitor"
    SUB_TITLE = f"polling every {POLL_INTERVAL:.0f}s  │  amdgpu_top v0.11 + psutil"

    def __init__(self, server_configs: list | None = None):
        super().__init__()
        self.servers: list[ServerMetrics] = [ServerMetrics(name=c["name"], url=c["url"].rstrip("/")) for c in (server_configs or DEFAULT_SERVERS)]
        self._poll_timer: Optional[Timer] = None
        self.use_fahrenheit: bool = False
        log.info("LlamaMonitor init: %d server(s): %s", len(self.servers), [s.url for s in self.servers])

    def compose(self) -> ComposeResult:
        """Compose the main layout: header, system panel, cards, log and footer."""
        yield Header(show_clock=True)
        yield SysPanel(id="sys_panel")
        yield SummaryTable(id="summary_table")
        yield ScrollableContainer(
            *[ServerCard(s, id=f"card_{_safe(s.name)}") for s in self.servers],
            id="cards_container",
        )
        yield Log(id="log_panel", max_lines=300)
        yield Static("", id="statusbar")
        yield Footer()

    def on_mount(self):
        """Start the periodic polling timer and perform an immediate refresh."""
        self._poll_timer = self.set_interval(POLL_INTERVAL, self.poll_all)
        self.poll_all()

    @work(exclusive=False, thread=False)
    async def poll_all(self):
        """Poll llama /metrics, GPU, process and system data, then refresh the UI."""
        now = time.time()
        log.debug("poll_all: cycle start")

        # 1. llama /metrics — all servers concurrently
        llama_results = await asyncio.gather(*[fetch_llama_metrics(s.url) for s in self.servers])

        # 2. GPU — single amdgpu_top call (shared APU)
        gpu_data = await LocalCollector.fetch_gpu()

        # 3. psutil — executor (synchronous)
        loop = asyncio.get_event_loop()
        proc_results = await asyncio.gather(
            *[
                loop.run_in_executor(
                    None,
                    LocalCollector.collect_proc,
                    s.proc,
                    _port_from_url(s.url),
                    gpu_data,
                )
                for s in self.servers
            ]
        )
        sys_data = await loop.run_in_executor(None, LocalCollector.collect_sys)

        for s, (ok, raw, err), proc in zip(self.servers, llama_results, proc_results):
            if ok:
                apply_llama_metrics(s, raw, now)
            else:
                s.reachable = False
                s.error = err
            s.gpu = gpu_data
            s.proc = proc
            s.sys = sys_data

        self._refresh_ui()

        ts = datetime.now().strftime("%H:%M:%S")
        online = sum(1 for s in self.servers if s.reachable)
        gpu_ok = "gpu✓" if gpu_data.available else f"gpu✗ {gpu_data.error[:28]}"

        status = f" {ts}  │  {online}/{len(self.servers)} online  │  {gpu_ok}" + (
            f"  │  VRAM {gpu_data.vram_used_mib:.0f}/{gpu_data.vram_total_mib:.0f} MiB"
            f"  │  GFX {gpu_data.gfx_pct:.0f}%"
            f"  │  {gpu_data.best_power_w:.1f}W  {_tc(gpu_data.best_temp_c, self.use_fahrenheit)}"
            f"  │  CPU {sys_data.cpu_pct_total:.0f}%  RAM {sys_data.mem_pct:.0f}%"
            if gpu_data.available
            else f"  │  CPU {sys_data.cpu_pct_total:.0f}%  RAM {sys_data.mem_pct:.0f}%"
        )
        self.query_one("#statusbar", Static).update(status)

        log_msg = (
            f"[{ts}] {online}/{len(self.servers)} online"
            + (
                f"  VRAM {gpu_data.vram_used_mib:.0f}/{gpu_data.vram_total_mib:.0f} MiB"
                f"  GFX {gpu_data.gfx_pct:.0f}%  SCLK {gpu_data.gfxclk_mhz:.0f}"
                f"  FCLK {gpu_data.fclk_mhz:.0f}  MCLK {gpu_data.mclk_mhz:.0f} MHz"
                f"  {gpu_data.best_power_w:.1f}W  {_tc(gpu_data.best_temp_c, self.use_fahrenheit)}"
                if gpu_data.available
                else f"  {gpu_data.error}"
            )
            + f"  CPU {sys_data.cpu_pct_total:.0f}%  RAM {sys_data.mem_pct:.0f}%"
            f"  load {sys_data.load_1:.2f}"
        )
        self.query_one("#log_panel", Log).write_line(log_msg)
        log.info(log_msg.strip())

    def _refresh_ui(self):
        """Refresh all UI widgets from the latest collected metrics."""
        # update sys panel with latest data from any server (shared host)
        if self.servers:
            try:
                self.query_one("#sys_panel", SysPanel).refresh_data(self.servers[0].sys)
            except Exception as exc:
                log.debug("_refresh_ui: sys_panel: %s", exc)
        use_f = self.use_fahrenheit
        for s in self.servers:
            try:
                self.query_one(f"#card_{_safe(s.name)}", ServerCard).refresh_data(use_f)
            except Exception as exc:
                log.debug("_refresh_ui: card %s: %s", s.name, exc)
        try:
            self.query_one("#summary_table", SummaryTable).refresh_data(self.servers, use_f)
        except Exception as exc:
            log.debug("_refresh_ui: summary: %s", exc)

    def action_refresh_now(self):
        """Trigger an immediate metrics poll."""
        log.debug("manual refresh")
        self.poll_all()

    def action_add_server(self):
        """Open the add-server dialog and append a new card on success."""

        def on_result(r):
            if r:
                s = ServerMetrics(name=r["name"], url=r["url"])
                self.servers.append(s)
                log.info("add_server: %s → %s", s.name, s.url)
                self.query_one("#cards_container", ScrollableContainer).mount(ServerCard(s, id=f"card_{_safe(s.name)}"))
                self.poll_all()

        self.push_screen(AddServerScreen(), on_result)

    def action_toggle_temp(self):
        """Toggle between Celsius and Fahrenheit temperature display."""
        self.use_fahrenheit = not self.use_fahrenheit
        self._refresh_ui()

    def action_set_cols(self, n: str):
        """Set the number of columns used to lay out server cards."""
        self.query_one("#cards_container", ScrollableContainer).styles.grid_size_columns = int(n)


# ─── Entry Point ───────────────────────────────────────────────────────────────


def main():
    """Parse CLI arguments, configure logging and run the TUI."""
    import argparse

    parser = argparse.ArgumentParser(
        description="llama-cpp monitor  (llama /metrics + amdgpu_top v0.11 + psutil)\n"
        "Logs    → logs/llama_monitor_<servers>_<ts>.log\n"
        "Raw GPU → tmp/amdtop_<pid>_<ts>.json  (written once per process)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--servers", "-s", nargs="+", metavar="NAME=URL", help="e.g.  case=http://localhost:10000")
    parser.add_argument("--config", "-c", metavar="FILE", help='JSON: [{"name":"...","url":"..."}]')
    global POLL_INTERVAL  # noqa: PLW0603
    parser.add_argument("--interval", "-i", type=float, default=POLL_INTERVAL, help=f"Poll interval in seconds (default {POLL_INTERVAL})")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable DEBUG log level (very verbose)")
    args = parser.parse_args()

    POLL_INTERVAL = args.interval

    configs: list = []
    if args.config:
        with open(args.config) as f:
            configs = json.load(f)
    elif args.servers:
        for spec in args.servers:
            if "=" in spec:
                name, url = spec.split("=", 1)
                configs.append({"name": name, "url": url})
            else:
                log.error("Invalid spec '%s', expected NAME=URL", spec)
                sys.exit(1)
    else:
        configs = DEFAULT_SERVERS

    label_parts: list[str] = []
    for cfg in configs:
        name = cfg.get("name") or cfg.get("url") or "server"
        label_parts.append(_safe(name))
    label = "-".join(label_parts) if label_parts else "servers"
    level = logging.DEBUG if args.debug else logging.INFO
    _setup_logging(label, level=level)
    if args.debug:
        log.debug("Debug logging enabled")

    log.info("Starting  configs=%s  interval=%.1fs", configs, POLL_INTERVAL)
    LlamaMonitor(server_configs=configs).run()


if __name__ == "__main__":
    main()

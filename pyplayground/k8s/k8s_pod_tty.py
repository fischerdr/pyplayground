#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This example used code(the `Interceptor` related part) from
# http://sqizit.bartletts.id.au/2011/02/14/pseudo-terminals-in-python/
# which is licensed under the MIT license: Copyright (c) 2011 Joshua D. Bartlett
"""This script is used to execute a command in a pod and interact with it.

It uses a pseudo terminal to interact with the pod.

Usage:
    k8s_pod_tty.py <pod_name> <namespace> <command> [options]
    Options:
        -c, --container: Specify container name within pod (if multiple exist).
        -x, --create-if-missing: Create a default Nginx pod if target pod is not found.
        -d, --debug: Enable verbose debug logging.

Example:
    k8s_pod_tty.py nginx-test default /bin/bash
    k8s_pod_tty.py nginx-test default -c nginx-container /bin/bash
    k8s_pod_tty.py nginx-test default -x /bin/bash
    k8s_pod_tty.py nginx-test default -c nginx-container -x /bin/bash
    k8s_pod_tty.py nginx-test default -c nginx-container -x -d /bin/bash
"""
import errno
import fcntl
import json
import logging
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time
import tty
from typing import Any, List, Optional, Tuple

# Third-party imports
import click  # Use click for CLI
from kubernetes.client import V1Pod  # Import V1Pod for type hint
from kubernetes.client.api import core_v1_api
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream
from kubernetes.stream.ws_client import WSClient  # Import for type hint

# Add import for logging utilities
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Import K8s utilities
from utils import k8s_utils

# Setup logger for module level
logger = get_logger(__name__)

# The following escape codes are xterm codes.
# See http://rtfm.etla.org/xterm/ctlseq.html for more.
START_ALTERNATE_MODE = set(f"\\x1b[?{i}h" for i in ("1049", "47", "1047"))
END_ALTERNATE_MODE = set(f"\\x1b[?{i}l" for i in ("1049", "47", "1047"))
ALTERNATE_MODE_FLAGS = tuple(START_ALTERNATE_MODE) + tuple(END_ALTERNATE_MODE)


def findlast(s: str, substrs: Tuple[str, ...]) -> Optional[str]:
    """Finds whichever of the given substrings occurs last in the given string and returns that substring.

    Args:
        s: The string to search.
        substrs: The substrings to search for.

    Returns:
        The substring that occurs last in the given string, or None if no such strings occur.
    """
    i = -1
    result: Optional[str] = None
    for substr in substrs:
        pos = s.rfind(substr)
        if pos > i:
            i = pos
            result = substr
    return result


class Interceptor:
    """Handles the pseudo-terminal interaction between the user and the Kubernetes pod exec stream."""

    def __init__(self, k8s_stream: WSClient):
        """Initialize the Interceptor object.

        Args:
            k8s_stream: The Kubernetes stream object (WSClient).
        """
        self.k8s_stream: Optional[WSClient] = k8s_stream
        self.master_fd: Optional[int] = None
        self.restore_term: bool = False
        self.original_mode: Optional[List[Any]] = None

    def spawn(self, argv: Tuple[str, ...]):
        """Create a spawned process in the pty and manage I/O.

        Args:
            argv: The command and arguments to run in the spawned process.
        """
        if not argv:
            shell = os.environ.get("SHELL", "/bin/sh")
            argv_list = [shell]
            logger.warning(f"No command provided, defaulting to SHELL: {shell}")
        else:
            argv_list = list(argv)

        pid, master_fd = pty.fork()
        self.master_fd = master_fd

        if pid == pty.CHILD:
            # Child process: execute the command
            try:
                os.execlp(argv_list[0], *argv_list)
            except OSError as e:
                # Log error in child before exiting if execlp fails
                sys.stderr.write(f"Child process failed to execute command '{' '.join(argv_list)}': {e}\\n")
                os._exit(1)  # Use _exit in child to avoid running finally blocks

        # Parent process
        old_handler = signal.signal(signal.SIGWINCH, self._signal_winch)
        try:
            # Put the user's terminal in raw mode
            self.original_mode = tty.tcgetattr(pty.STDIN_FILENO)
            tty.setraw(pty.STDIN_FILENO)
            self.restore_term = True
        except tty.error as e:  # termios.error
            logger.warning(f"Failed to set raw mode on tty: {e}. Interaction might be limited.")
            self.restore_term = False

        try:
            self._init_fd()
            self._copy()
        except (IOError, OSError) as e:
            logger.error(f"I/O error during pty copy: {e}", exc_info=True)
        finally:
            # Cleanup
            if self.restore_term and self.original_mode:
                logger.debug("Restoring original terminal settings.")
                tty.tcsetattr(pty.STDIN_FILENO, tty.TCSAFLUSH, self.original_mode)

            if self.k8s_stream:
                logger.debug("Closing Kubernetes stream.")
                self.k8s_stream.close()
                self.k8s_stream = None

            if self.master_fd is not None:
                logger.debug(f"Closing master file descriptor: {self.master_fd}")
                os.close(self.master_fd)
                self.master_fd = None

            # Restore original signal handler
            signal.signal(signal.SIGWINCH, old_handler)
            logger.debug("Restored SIGWINCH handler.")

    def _init_fd(self):
        """Called once when the pty is first set up to set the initial size."""
        self._set_pty_size()

    def _signal_winch(self, signum: int, frame: Optional[Any]):
        """Signal handler for SIGWINCH - window size has changed."""
        logger.debug("SIGWINCH received, resizing pty.")
        self._set_pty_size()

    def _set_pty_size(self):
        """Sets the window size of the child pty based on the window size of our own controlling terminal."""
        if not self.k8s_stream or not self.k8s_stream.is_open():
            logger.warning("Cannot set pty size: Kubernetes stream is not open.")
            return
        try:
            # Get terminal size
            packed = fcntl.ioctl(pty.STDOUT_FILENO, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
            rows, cols, h_pixels, v_pixels = struct.unpack("HHHH", packed)
            logger.debug(f"Terminal size: {rows} rows, {cols} cols")

            # Send resize event via stream channel 4
            resize_message = json.dumps({"Height": rows, "Width": cols})
            self.k8s_stream.write_channel(4, resize_message)
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"Error setting pty size: {e}", exc_info=True)

    def _copy(self):  # noqa: C901
        """Main select loop. Passes data between user's stdin/stdout and the Kubernetes stream."""
        if not self.k8s_stream or self.master_fd is None:
            logger.error("Cannot start copy loop: Stream or master_fd not initialized.")
            return

        while self.k8s_stream.is_open():
            try:
                read_fds = [pty.STDIN_FILENO, self.k8s_stream.sock.sock]
                # select might fail if stdin is closed (e.g., piping input)
                try:
                    rfds, wfds, xfds = select.select(read_fds, [], [], 1)  # Add timeout
                except ValueError:  # Handle case where STDIN_FILENO is invalid/closed
                    rfds, wfds, xfds = select.select([self.k8s_stream.sock.sock], [], [], 1)
                    if pty.STDIN_FILENO in read_fds:
                        read_fds.remove(pty.STDIN_FILENO)

            except select.error as e:
                # Removed six dependency
                if e.args[0] == errno.EINTR:
                    logger.debug("Select interrupted, continuing.")
                    continue
                else:
                    logger.error(f"Select error: {e}", exc_info=True)
                    break
            except Exception as e:  # Catch other potential select errors
                logger.error(f"Unexpected error during select: {e}", exc_info=True)
                break

            if not rfds:  # Handle timeout case
                continue

            # Handle user input
            if pty.STDIN_FILENO in rfds:
                try:
                    data = os.read(pty.STDIN_FILENO, 1024)
                    if data:
                        self.stdin_read(data)
                    else:  # EOF on stdin
                        logger.info("EOF received from stdin.")
                        # Optionally close stream stdin? self.k8s_stream.write_stdin(None) # Or equivalent signal
                        break  # Or break? Depends on desired behavior
                except OSError as e:
                    logger.error(f"Error reading from stdin: {e}")
                    break  # Stop processing if stdin has error

            # Handle stream input (from pod)
            if self.k8s_stream.sock.sock in rfds:
                try:
                    # Check for errors first
                    if self.k8s_stream.peek_channel(3):  # Stderr channel
                        error_data = self.k8s_stream.read_channel(3)
                        logger.warning(f"Received error from pod: {error_data.strip()}")
                        # Continue reading stdout? Or break? Assuming continue for now.
                    if self.k8s_stream.peek_channel(2):  # Error channel (different from stderr)
                        error_status = self.k8s_stream.read_channel(2)
                        logger.error(f"Received error status from stream: {error_status}")
                        break  # Exit on stream-level error

                    # Check for stdout
                    if self.k8s_stream.peek_stdout():
                        stdout_data = self.k8s_stream.read_stdout()
                        if stdout_data:
                            self.master_read(stdout_data)
                        # No else needed, empty read is fine

                except Exception as e:
                    logger.error(f"Error reading from Kubernetes stream: {e}", exc_info=True)
                    break  # Exit loop on stream read error

        logger.debug("Exiting copy loop.")

    def write_stdout(self, data: str):
        """Writes data (received from pod) to the user's stdout."""
        try:
            # os.write expects bytes
            os.write(pty.STDOUT_FILENO, data.encode())
        except OSError as e:
            logger.error(f"Error writing to stdout: {e}")

    def write_master(self, data: bytes):
        """Writes data (received from user) to the pod's stdin via the stream."""
        if self.k8s_stream and self.k8s_stream.is_open():
            try:
                self.k8s_stream.write_stdin(data.decode())  # Stream expects str
            except Exception as e:
                logger.error(f"Error writing to k8s stream stdin: {e}")
        else:
            logger.warning("Skipping write to master: k8s stream is closed or not initialized.")

    def master_read(self, data: str):
        """Processes data received from the pod's stdout/stderr stream."""
        # Basic handling of alternate mode - could be more sophisticated
        flag = findlast(data, ALTERNATE_MODE_FLAGS)
        if flag is not None:
            if flag in START_ALTERNATE_MODE:
                logger.debug("Detected terminal alternate mode start.")
                # self.write_master(b"IEntering special mode.\\x1b") # Example interaction
            elif flag in END_ALTERNATE_MODE:
                logger.debug("Detected terminal alternate mode end.")
                # self.write_master(b'echo "Leaving special mode."\\r') # Example interaction

        self.write_stdout(data)

    def stdin_read(self, data: bytes):
        """Processes data received from the user's stdin."""
        self.write_master(data)


# --- Helper Functions ---


def _ensure_pod_exists(  # noqa: C901
    api: core_v1_api.CoreV1Api,
    pod_name: str,
    namespace: str,
    create_if_missing: bool = False,  # Add parameter
) -> Optional[V1Pod]:
    """Checks if pod exists. If not found and create_if_missing is True, creates it and waits for readiness."""
    logger.info(f"Checking for pod '{pod_name}' in namespace '{namespace}'...")
    try:
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        logger.info(f"Pod '{pod_name}' found.")
        return pod
    except ApiException as e:
        if e.status == 404:
            if create_if_missing:
                logger.info(f"Pod '{pod_name}' not found. Creating it as requested...")
                # Proceed with creation logic below
            else:
                logger.error(f"Pod '{pod_name}' not found in namespace '{namespace}'. Creation not requested.")
                return None  # Pod not found, creation not requested
        else:
            logger.error(f"Kubernetes API error checking pod: {e}")
            raise  # Re-raise unexpected API errors

    # --- Pod Creation Logic (only runs if pod not found and create_if_missing is True) ---
    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": pod_name},
        "spec": {
            "containers": [
                {
                    "image": "nginx:alpine",  # Smaller base image
                    "name": "shell",  # More descriptive name
                    # Keep container running indefinitely for exec
                    "command": ["/bin/sh", "-c", "trap : TERM INT; sleep infinity & wait"],
                }
            ]
        },
    }
    try:
        api.create_namespaced_pod(body=pod_manifest, namespace=namespace)
        logger.info(f"Pod '{pod_name}' creation request sent. Waiting for it to be ready...")
        while True:
            pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
            if pod.status and pod.status.phase == "Running":
                # Check container readiness as well if possible
                if pod.status.container_statuses:
                    ready = all(cs.ready for cs in pod.status.container_statuses)
                    if ready:
                        logger.info(f"Pod '{pod_name}' is Running and Ready.")
                        return pod
                else:  # Fallback if container statuses not yet available
                    logger.debug(f"Pod '{pod_name}' is Running, waiting for container readiness...")

            elif pod.status and pod.status.phase in ["Failed", "Unknown"]:
                logger.error(f"Pod '{pod_name}' entered Failed/Unknown state.")
                return None  # Indicate failure
            logger.debug(f"Pod '{pod_name}' current phase: {pod.status.phase if pod.status else 'Unknown'}. Waiting...")
            time.sleep(2)  # Shorter sleep interval
    except ApiException as e:
        logger.error(f"API error creating/waiting for pod '{pod_name}': {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating/waiting for pod '{pod_name}': {e}")
        raise
    return None  # Should not be reached ideally


def _setup_stream(
    api: core_v1_api.CoreV1Api,
    pod_name: str,
    namespace: str,
    command: Tuple[str, ...],
    container_name: Optional[str] = None,  # Add container_name parameter
) -> WSClient:
    """Initializes and returns the Kubernetes exec stream."""
    exec_command = list(command)  # stream expects a list
    log_msg = f"Establishing exec stream to pod '{pod_name}' ns '{namespace}'"
    if container_name:
        log_msg += f" container '{container_name}'"
    log_msg += f" command: {' '.join(exec_command)}"
    logger.info(log_msg)

    try:
        stream_kwargs = {
            "api_method": api.connect_post_namespaced_pod_exec,
            "name": pod_name,
            "namespace": namespace,
            "command": exec_command,
            "stderr": True,
            "stdin": True,
            "stdout": True,
            "tty": True,
            "_preload_content": False,
        }
        if container_name:
            stream_kwargs["container"] = container_name

        return stream(**stream_kwargs)
    except ApiException as e:
        logger.error(f"API error establishing stream: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error establishing stream: {e}")
        raise


# --- Main Execution ---


@click.command()
@click.argument("pod_name", required=True, metavar="POD_NAME", help="Name of the target pod.")
@click.argument("namespace", required=True, metavar="NAMESPACE", help="Namespace of the target pod.")
@click.argument(
    "command",
    required=True,
    nargs=-1,
    metavar="COMMAND",
    help="Command and arguments to execute in the pod.",
)
@click.option("-c", "--container", default=None, help="Specify container name within pod (if multiple exist).")
@click.option(
    "-x",
    "--create-if-missing",
    is_flag=True,
    default=False,
    help="Create a default Nginx pod if target pod is not found.",
)
@click.option("-d", "--debug", is_flag=True, default=False, help="Enable verbose debug logging.")
def main(
    pod_name: str,
    namespace: str,
    command: Tuple[str, ...],
    container: Optional[str],
    create_if_missing: bool,
    debug: bool,
):
    """Executes COMMAND in POD_NAME (within NAMESPACE) via an interactive TTY.

    This script uses a pseudo terminal to interact with the pod.
    If the pod has multiple containers, specify the target using -c/--container.
    Use -x/--create-if-missing to create a basic Nginx pod if it doesn't exist.
    """
    # Setup Logging
    log_level = logging.DEBUG if debug else logging.INFO
    script_base_name = os.path.basename(__file__).replace(".py", "")
    setup_logging(level=log_level, script_name=script_base_name)

    try:
        # Load K8s config (file or in-cluster)
        if not k8s_utils.load_kube_config_auto():
            logger.critical("Failed to load Kubernetes configuration. Exiting.")
            sys.exit(1)

        # Get K8s API client using the utility
        try:
            api = k8s_utils.get_k8s_client("CoreV1Api")
        except Exception as client_error:
            logger.critical(f"Failed to create Kubernetes API client: {client_error}")
            sys.exit(1)

        pod = _ensure_pod_exists(api, pod_name, namespace, create_if_missing)  # Pass flag

        if not pod:
            logger.critical(f"Pod '{pod_name}' not found or failed to become ready. Exiting.")
            sys.exit(1)

        # Determine target container before setting up stream
        try:
            target_container = k8s_utils.determine_target_container(pod, container)
            logger.info(f"Targeting container: '{target_container}'")
        except ValueError as e:
            logger.critical(f"Container selection error: {e}")
            sys.exit(1)

        k8s_stream = _setup_stream(api, pod_name, namespace, command, container_name=target_container)

        interceptor = Interceptor(k8s_stream=k8s_stream)
        logger.info("Switching to interactive pty mode. Press Ctrl+D or type 'exit' to quit.")
        interceptor.spawn(command)  # Pass command tuple directly
        logger.info("Exited pty mode.")

    except Exception as e:
        # Catch exceptions from helper functions or interceptor setup
        logger.error(f"An error occurred during execution: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Final terminal reset attempt (optional, may interfere with user's shell)
        try:
            logger.debug("Running final terminal reset command.")
            # Consider making reset optional via flag
            subprocess.run(["/usr/bin/reset"], check=True, capture_output=True)
        except FileNotFoundError:
            logger.warning("'/usr/bin/reset' command not found for final reset.")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Final terminal reset command failed: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error during final terminal reset: {e}")


if __name__ == "__main__":
    # Click handles exceptions internally by default, or use try/except here if needed
    # Use basic print here as logger might not be configured if main() fails early
    main()  # Click entry point

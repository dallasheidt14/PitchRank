#!/usr/bin/env python3
"""
Server lifecycle manager for frontend testing.

Starts one or more servers, waits for them to be ready, runs a command,
then shuts down the servers.

Usage:
    python with_server.py --help

    # Single server:
    python with_server.py --server "npm run dev" --port 3000 -- python test.py

    # Multiple servers:
    python with_server.py \
        --server "npm run dev" --port 3000 \
        --server "python api.py" --port 8000 \
        -- python test.py
"""

import argparse
import subprocess
import sys
import time
import socket
import signal
import os
from typing import List, Tuple, Optional


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def wait_for_port(host: str, port: int, timeout: float = 60.0, interval: float = 0.5) -> bool:
    """Wait for a port to become available."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_port_open(host, port):
            return True
        time.sleep(interval)
    return False


def start_server(command: str, cwd: Optional[str] = None) -> subprocess.Popen:
    """Start a server process."""
    # Use shell=True to handle complex commands
    env = os.environ.copy()
    env['FORCE_COLOR'] = '0'  # Disable color output for cleaner logs

    process = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        preexec_fn=os.setsid  # Create new process group for cleanup
    )
    return process


def cleanup_servers(servers: List[subprocess.Popen]) -> None:
    """Terminate all server processes."""
    for proc in servers:
        if proc.poll() is None:  # Process still running
            try:
                # Kill the entire process group
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception as e:
                print(f"Warning: Could not terminate process: {e}", file=sys.stderr)

    # Wait for processes to terminate
    for proc in servers:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="Manage server lifecycle for testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start Next.js dev server and run tests:
  python with_server.py --server "npm run dev" --port 3000 -- python audit.py

  # Multiple servers with different directories:
  python with_server.py \\
    --server "cd frontend && npm run dev" --port 3000 \\
    --server "cd backend && python server.py" --port 8000 \\
    -- python integration_test.py

  # Custom timeout and host:
  python with_server.py --server "npm run dev" --port 3000 \\
    --timeout 120 --host localhost -- python test.py
        """
    )

    parser.add_argument(
        '--server', '-s',
        action='append',
        dest='servers',
        help='Server command to run (can be specified multiple times)'
    )
    parser.add_argument(
        '--port', '-p',
        action='append',
        dest='ports',
        type=int,
        help='Port to wait for (must match number of --server flags)'
    )
    parser.add_argument(
        '--host',
        default='localhost',
        help='Host to check for port availability (default: localhost)'
    )
    parser.add_argument(
        '--timeout', '-t',
        type=float,
        default=60.0,
        help='Timeout in seconds waiting for server to start (default: 60)'
    )
    parser.add_argument(
        '--cwd',
        default=None,
        help='Working directory for server commands'
    )
    parser.add_argument(
        'command',
        nargs='*',
        help='Command to run after servers are ready'
    )

    args = parser.parse_args()

    if not args.servers:
        parser.error("At least one --server is required")

    if not args.ports:
        parser.error("At least one --port is required")

    if len(args.servers) != len(args.ports):
        parser.error("Number of --server and --port flags must match")

    if not args.command:
        parser.error("A command to run is required after --")

    servers: List[subprocess.Popen] = []

    # Setup signal handlers for cleanup
    def signal_handler(signum, frame):
        print("\nReceived interrupt, cleaning up servers...", file=sys.stderr)
        cleanup_servers(servers)
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Start all servers
        for cmd, port in zip(args.servers, args.ports):
            print(f"Starting server: {cmd}", file=sys.stderr)
            proc = start_server(cmd, cwd=args.cwd)
            servers.append(proc)
            print(f"  PID: {proc.pid}, waiting for port {port}...", file=sys.stderr)

        # Wait for all ports to be ready
        for cmd, port in zip(args.servers, args.ports):
            if not wait_for_port(args.host, port, timeout=args.timeout):
                print(f"ERROR: Server failed to start on port {port}", file=sys.stderr)
                cleanup_servers(servers)
                sys.exit(1)
            print(f"  Port {port} is ready!", file=sys.stderr)

        print(f"\nAll servers ready. Running: {' '.join(args.command)}\n", file=sys.stderr)
        print("-" * 60, file=sys.stderr)

        # Run the command
        result = subprocess.run(args.command)

        print("-" * 60, file=sys.stderr)
        print(f"\nCommand exited with code: {result.returncode}", file=sys.stderr)

        return result.returncode

    finally:
        print("Cleaning up servers...", file=sys.stderr)
        cleanup_servers(servers)


if __name__ == '__main__':
    sys.exit(main())

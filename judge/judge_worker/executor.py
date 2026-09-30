import io
import socket
import re
import shlex
import tarfile
import threading
import time
import docker
from docker.utils.socket import frames_iter
from config import WORKSPACE_DIR, MAX_OUTPUT_BYTES, COMPILE_TIMEOUT_SEC
from shared.models import Language, FILENAME, Verdict
from .types import CompileResult, RunResult

STATS = re.compile(r"^__BB_TIME__ ([0-9.]+) ([0-9]+)$", re.MULTILINE)


class JudgeExecutor:
    def __init__(self):
        self.workspace_dir = WORKSPACE_DIR
        self.client = docker.from_env(timeout=10)

    def _copy(self, container, name, data, mode=0o600):
        with io.BytesIO() as stream:
            with tarfile.open(fileobj=stream, mode="w") as archive:
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mode = mode
                archive.addfile(info, io.BytesIO(data))
            stream.seek(0)
            # Docker's archive endpoint rejects read-only root filesystems even
            # when the destination is tmpfs. Stream a trusted tar into tmpfs.
            exec_id = self.client.api.exec_create(
                container.id,
                cmd=["tar", "-xmf", "-", "-C", WORKSPACE_DIR],
                user="run",
                stdin=True,
                tty=False,
            )["Id"]
            sock = self.client.api.exec_start(exec_id, socket=True, tty=False)
            try:
                sock._sock.settimeout(10)
                sock._sock.sendall(stream.getvalue())
                sock._sock.shutdown(socket.SHUT_WR)
                for _, payload in frames_iter(socket=sock, tty=False):
                    pass
            finally:
                sock.close()
            if self.client.api.exec_inspect(exec_id)["ExitCode"] != 0:
                raise RuntimeError("Could not copy input into isolated workspace")

    def copy_code_to_container(self, container, language, code):
        self._copy(container, FILENAME[language], code)

    def read_binary(self, container):
        # Read from the live tmpfs mount, which Docker's archive API cannot see.
        result = container.exec_run(
            ["head", "-c", str(16 * 1024 * 1024 + 1), WORKSPACE_DIR + "/main.out"],
            demux=True,
        )
        data, errors = result.output
        if result.exit_code != 0 or data is None:
            raise RuntimeError("Could not read compiler artifact")
        if len(data) > 16 * 1024 * 1024:
            raise ValueError("Compiled artifact exceeds 16 MB")
        return data

    def copy_binary(self, container, data):
        self._copy(container, "main.out", data, mode=0o500)

    def _execute(self, container, command, deadline):
        """Drain bounded output under a host watchdog; never attach open stdin."""
        exec_id = self.client.api.exec_create(
            container.id,
            cmd=["/bin/sh", "-c", command],
            workdir=WORKSPACE_DIR,
            user="run",
            stdin=False,
            tty=False,
        )["Id"]
        timed_out = threading.Event()

        def kill():
            timed_out.set()
            try:
                container.kill()
            except docker.errors.DockerException:
                pass

        timer = threading.Timer(deadline, kill)
        stdout = bytearray()
        stderr = bytearray()
        overflow = False
        sock = None
        timer.start()
        try:
            sock = self.client.api.exec_start(exec_id, socket=True, tty=False)
            for stream_id, payload in frames_iter(socket=sock, tty=False):
                room = MAX_OUTPUT_BYTES - len(stdout) - len(stderr)
                (stdout if stream_id == 1 else stderr).extend(payload[: max(room, 0)])
                if len(payload) > room:
                    overflow = True
                    try:
                        container.kill()
                    except docker.errors.DockerException:
                        pass
                    break
        except (OSError, docker.errors.DockerException):
            if not timed_out.is_set() and not overflow:
                raise
        finally:
            timer.cancel()
            if sock:
                sock.close()
        try:
            exit_code = self.client.api.exec_inspect(exec_id)["ExitCode"]
        except docker.errors.DockerException:
            if not (timed_out.is_set() or overflow):
                raise
            exit_code = 137
        return (
            exit_code,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
            timed_out.is_set(),
            overflow,
        )

    def _compile(self, container, language):
        compiler = "gcc" if language == Language.C else "g++"
        args = [
            compiler,
            "-O2",
            "-pipe",
            "-o",
            f"{WORKSPACE_DIR}/main.out",
            f"{WORKSPACE_DIR}/{FILENAME[language]}",
        ]
        if language == Language.CPP:
            args.insert(1, "-std=c++17")
        command = f"timeout -s KILL {COMPILE_TIMEOUT_SEC}s " + shlex.join(args)
        code, out, err, timed_out, overflow = self._execute(
            container, command, COMPILE_TIMEOUT_SEC + 2
        )
        message = (
            "Compiler output limit exceeded."
            if overflow
            else (
                "Compilation timed out."
                if timed_out or code in (124, 137)
                else out + err
            )
        )
        return CompileResult(
            ok=code == 0 and not overflow and not timed_out,
            output=message[:8192],
            exit_code=code or 0,
        )

    def compile_c(self, container):
        return self._compile(container, Language.C)

    def compile_cpp(self, container):
        return self._compile(container, Language.CPP)

    def _oom_count(self, container):
        result = container.exec_run(["cat", "/sys/fs/cgroup/memory.events"])
        if result.exit_code != 0:
            return None
        values = dict(line.split() for line in result.output.decode().splitlines())
        return int(values.get("oom_kill", "0"))

    def run_program(
        self,
        container,
        language,
        executable_path,
        input_data,
        expected_output,
        time_limit_sec,
        memory_limit_kb,
    ):
        if time_limit_sec <= 0 or memory_limit_kb <= 0:
            raise ValueError("Invalid execution limits")
        self._copy(container, ".input", input_data.encode())
        # The kernel enforces each problem's memory budget, including descendants.
        memory_bytes = memory_limit_kb * 1024
        container.update(mem_limit=memory_bytes, memswap_limit=memory_bytes)
        before_oom = self._oom_count(container)
        args = (
            ["python3", executable_path]
            if language == Language.PYTHON
            else [executable_path]
        )
        command = (
            f"/usr/bin/time -f '__BB_TIME__ %e %M' timeout -s KILL {time_limit_sec}s "
            + shlex.join(args)
            + f' < {shlex.quote(WORKSPACE_DIR+"/.input")}'
        )
        started = time.monotonic()
        code, out, err, watchdog, overflow = self._execute(
            container, command, time_limit_sec + 2
        )
        matches = list(STATS.finditer(err))
        if matches:
            runtime_ms = round(float(matches[-1].group(1)) * 1000)
            memory_kb = int(matches[-1].group(2))
            diagnostics = STATS.sub("", err).strip()
        else:
            runtime_ms = round((time.monotonic() - started) * 1000)
            memory_kb = 0
            diagnostics = err.strip()
        try:
            after_oom = self._oom_count(container)
        except docker.errors.DockerException:
            after_oom = None
        oom = (
            before_oom is not None and after_oom is not None and after_oom > before_oom
        )
        if overflow:
            verdict = Verdict.RUNTIME_ERROR
            diagnostics = "Output limit exceeded."
        elif oom or memory_kb > memory_limit_kb:
            verdict = Verdict.MEMORY_LIMIT_EXCEEDED
        elif (
            watchdog
            or code == 124
            or (code == 137 and runtime_ms >= time_limit_sec * 1000)
        ):
            verdict = Verdict.TIME_LIMIT_EXCEEDED
        elif code != 0:
            verdict = Verdict.RUNTIME_ERROR
        elif not matches:
            raise RuntimeError(
                "Judge timing statistics missing; execution cannot be trusted"
            )
        else:
            verdict = (
                Verdict.ACCEPTED
                if out.split() == expected_output.split()
                else Verdict.WRONG_ANSWER
            )
        output = (
            diagnostics
            if verdict in (Verdict.RUNTIME_ERROR, Verdict.MEMORY_LIMIT_EXCEEDED)
            else out
        )[:8192]
        return RunResult(
            ok=verdict == Verdict.ACCEPTED,
            verdict=verdict,
            output=output,
            exit_code=code,
            runtime_ms=runtime_ms,
            memory_kb=memory_kb,
        )

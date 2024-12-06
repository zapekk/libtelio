import os
from asyncio import Event, wait_for
from config import WINDUMP_BINARY_WINDOWS
from contextlib import asynccontextmanager, AsyncExitStack
from typing import AsyncIterator, Optional
from utils.connection import TargetOS, Connection
from utils.output_notifier import OutputNotifier
from utils.process import Process
from utils.testing import get_current_test_log_path

PCAP_FILE_PATH = {
    TargetOS.Linux: "/dump.pcap",
    TargetOS.Mac: "/var/root/dump.pcap",
    TargetOS.Windows: "C:\\workspace\\dump.pcap",
}


class TcpDump:
    interfaces: Optional[list[str]]
    connection: Connection
    process: Process
    stdout: str
    stderr: str
    output_file: Optional[str]
    output_notifier: OutputNotifier
    count: Optional[int]

    def __init__(
        self,
        connection: Connection,
        flags: Optional[list[str]] = None,
        expressions: Optional[list[str]] = None,
        interfaces: Optional[list[str]] = None,
        output_file: Optional[str] = None,
        count: Optional[int] = None,
    ) -> None:
        self.connection = connection
        self.interfaces = interfaces
        self.output_file = output_file
        self.output_notifier = OutputNotifier()
        self.start_event = Event()
        self.count = count
        self.stdout = ""
        self.stderr = ""

        self.output_notifier.notify_output("listening on", self.start_event)

        command = [self.get_tcpdump_binary(connection.target_os), "-n"]

        if self.output_file:
            command += ["-w", self.output_file]
        else:
            command += ["-w", PCAP_FILE_PATH[self.connection.target_os]]

        if self.interfaces:
            if self.connection.target_os != TargetOS.Windows:
                command += ["-i", ",".join(self.interfaces)]
            else:
                # TODO(gytsto). Windump itself only supports one interface at the time,
                # but it supports multiple instances of Windump without any issues,
                # so there is a workaround we can do for multiple interfaces:
                # - create multiple process of windump for each interface
                # - when finished with dump, just combine the pcap's with `mergecap` or smth
                print(
                    "[Warning] Currently tcpdump for windows support only 1 interface"
                )
                command += ["-i", self.interfaces[0]]
        else:
            if self.connection.target_os != TargetOS.Windows:
                command += ["-i", "any"]
            else:
                command += ["-i", "1"]

        if self.count:
            command += ["-c", str(self.count)]

        if flags:
            command += flags

        if self.connection.target_os != TargetOS.Windows:
            command += ["--immediate-mode"]
            command += ["port not 22"]
        else:
            command += ["not port 22"]

        if expressions:
            command += expressions

        self.process = self.connection.create_process(
            command,
            # xterm type is needed here, because Mac on default term type doesn't
            # handle signals properly while `tcpdump -w file` is running, without writing
            # to file, everything works fine
            term_type="xterm" if self.connection.target_os == TargetOS.Mac else None,
        )

    @staticmethod
    def get_tcpdump_binary(target_os: TargetOS) -> str:
        if target_os in [TargetOS.Linux, TargetOS.Mac]:
            return "tcpdump"

        if target_os == TargetOS.Windows:
            return WINDUMP_BINARY_WINDOWS

        raise ValueError(f"target_os not supported {target_os}")

    def get_stdout(self) -> str:
        return self.stdout

    def get_stderr(self) -> str:
        return self.stderr

    async def on_stdout(self, output: str) -> None:
        print(f"tcpdump: {output}")
        self.stdout += output
        await self.output_notifier.handle_output(output)

    async def on_stderr(self, output: str) -> None:
        print(f"tcpdump err: {output}")
        self.stderr += output
        await self.output_notifier.handle_output(output)

    async def execute(self) -> None:
        try:
            await self.process.execute(self.on_stdout, self.on_stderr, True)
        except Exception as e:
            print(f"Error executing tcpdump: {e}")
            raise

    @asynccontextmanager
    async def run(self) -> AsyncIterator["TcpDump"]:
        async with self.process.run(self.on_stdout, self.on_stderr, True):
            await wait_for(self.start_event.wait(), 10)
            yield self


def find_unique_path_for_tcpdump(log_dir, guest_name):
    candidate_path = f"{log_dir}/{guest_name}.pcap"
    counter = 1
    # NOTE: counter starting from '1' means that the file will either have no suffix or
    # will have a suffix starting from '2'. This is to make it clear that it's not the
    # first log for that guest/client.
    while os.path.isfile(candidate_path):
        counter += 1
        candidate_path = f"./{log_dir}/{guest_name}-{counter}.pcap"
    return candidate_path


@asynccontextmanager
async def make_tcpdump(
    connection_list: list[Connection],
    download: bool = True,
    store_in: Optional[str] = None,
):
    try:
        async with AsyncExitStack() as exit_stack:
            for conn in connection_list:
                await exit_stack.enter_async_context(TcpDump(conn).run())
            yield
    finally:
        if download:
            log_dir = get_current_test_log_path()
            os.makedirs(log_dir, exist_ok=True)
            for conn in connection_list:
                path = find_unique_path_for_tcpdump(
                    store_in if store_in else log_dir, conn.target_name()
                )
                await conn.download(PCAP_FILE_PATH[conn.target_os], path)

        if conn.target_os != TargetOS.Windows:
            await conn.create_process(
                ["rm", "-f", PCAP_FILE_PATH[conn.target_os]]
            ).execute()
        else:
            await conn.create_process(["del", PCAP_FILE_PATH[conn.target_os]]).execute()

#!/usr/bin/env python3
"""Minimal localtunnel client: relays N TCP connections from the
localtunnel server to a local port. Usage:
  lt_client.py <remote_host> <remote_port> <local_port> [count]
"""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lt_client")


async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def relay(remote_host, remote_port, local_port, idx):
    while True:
        try:
            r_reader, r_writer = await asyncio.open_connection(remote_host, remote_port)
            l_reader, l_writer = await asyncio.open_connection("127.0.0.1", local_port)
            log.info("relay #%d: tunnel connected", idx)
            await asyncio.gather(
                pipe(r_reader, l_writer),
                pipe(l_reader, r_writer),
            )
        except Exception as e:
            log.warning("relay #%d: %s — retrying in 3s", idx, e)
        await asyncio.sleep(3)


async def main():
    remote_host = sys.argv[1]
    remote_port = int(sys.argv[2])
    local_port = int(sys.argv[3])
    count = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    log.info("connecting %d relays to %s:%d -> 127.0.0.1:%d",
             count, remote_host, remote_port, local_port)
    await asyncio.gather(*[relay(remote_host, remote_port, local_port, i) for i in range(count)])


if __name__ == "__main__":
    asyncio.run(main())

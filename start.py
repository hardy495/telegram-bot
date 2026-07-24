import asyncio
import sys

async def run_telegram():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "bot.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    async for line in proc.stdout:
        print(line.decode().strip(), flush=True)

async def run_max():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "max_bot.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    async for line in proc.stdout:
        print(f"[MAX] {line.decode().strip()}", flush=True)

async def main():
    await asyncio.gather(run_telegram(), run_max())

if __name__ == "__main__":
    asyncio.run(main())

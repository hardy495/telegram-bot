import asyncio
import subprocess
import sys
import os

async def run_telegram():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "bot.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    async for line in proc.stdout:
        print(f"[TELEGRAM] {line.decode().strip()}")

async def run_max():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "max_bot.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    async for line in proc.stdout:
        print(f"[MAX] {line.decode().strip()}")

async def main():
    print("Запускаем ботов...")
    await asyncio.gather(
        run_telegram(),
        run_max()
    )

if __name__ == "__main__":
    asyncio.run(main())

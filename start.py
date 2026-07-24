import asyncio
import sys
import os

async def run_telegram():
    print("[START] Запускаем Telegram бота...", flush=True)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "bot.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    async for line in proc.stdout:
        print(f"[TG] {line.decode().strip()}", flush=True)
    print("[TG] Процесс завершился!", flush=True)

async def run_max():
    print("[START] Запускаем MAX бота...", flush=True)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "max_bot.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    async for line in proc.stdout:
        print(f"[MAX] {line.decode().strip()}", flush=True)
    print("[MAX] Процесс завершился!", flush=True)

async def main():
    print("[START] Запускаем обоих ботов...", flush=True)
    await asyncio.gather(
        run_telegram(),
        run_max()
    )

if __name__ == "__main__":
    asyncio.run(main())

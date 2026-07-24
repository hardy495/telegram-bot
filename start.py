import subprocess
import sys
import os
import threading

def run_telegram():
    subprocess.run([sys.executable, "bot.py"])

def run_max():
    subprocess.run([sys.executable, "max_bot.py"])

if __name__ == "__main__":
    t1 = threading.Thread(target=run_telegram, daemon=False)
    t2 = threading.Thread(target=run_max, daemon=False)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

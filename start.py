import subprocess
import sys

# Запускаем один процесс - bot.py содержит оба бота
subprocess.run([sys.executable, "bot.py"])

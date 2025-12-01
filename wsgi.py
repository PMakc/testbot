#!/usr/bin/env python3
# wsgi.py - Рабочий файл для Scalingo

import os
import sys
import threading
import time
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Health check handler
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        elif self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            html = """
            <html>
            <head><title>🎅 Santa Bot</title></head>
            <body style="font-family: Arial; padding: 40px; text-align: center;">
                <h1>🎅 Тайный Санта Бот</h1>
                <p>Status: <span style="color: green; font-weight: bold;">🟢 ONLINE</span></p>
                <p>Telegram: @Santa_GF_BOT</p>
            </body>
            </html>
            """
            self.wfile.write(html.encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Тихий режим
        pass

def run_web_server():
    """Запускает веб-сервер для health check"""
    port = int(os.environ.get('PORT', 5000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    logger.info(f"🌐 Web server started on port {port}")
    server.serve_forever()

def run_bot():
    """Запускает Telegram бота БЕЗ импорта"""
    logger.info("🤖 Запуск бота...")
    
    import subprocess
    
    while True:
        try:
            process = subprocess.Popen(
                ['python', 'SantOS.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # Отдельно stderr
                text=True,
                bufsize=1
            )
            
            # Читаем stdout и stderr одновременно
            import select
            
            while True:
                # Проверяем, есть ли что читать
                reads = [process.stdout, process.stderr]
                ret = select.select(reads, [], [], 1.0)
                
                for read in ret[0]:
                    line = read.readline()
                    if line:
                        if read == process.stderr:
                            logger.error(f"❌ БОТ ОШИБКА: {line.strip()}")
                        else:
                            logger.info(f"🤖 {line.strip()}")
                
                # Проверяем, завершился ли процесс
                if process.poll() is not None:
                    # Прочитать оставшиеся данные
                    for line in process.stdout:
                        logger.info(f"🤖 {line.strip()}")
                    for line in process.stderr:
                        logger.error(f"❌ БОТ ОШИБКА: {line.strip()}")
                    
                    return_code = process.returncode
                    logger.warning(f"⚠️ Бот завершился с кодом {return_code}, перезапуск через 5 сек...")
                    break
            
            time.sleep(5)
            
        except Exception as e:
            logger.error(f"❌ Ошибка запуска: {e}")
            time.sleep(10)

def main():
    logger.info("🚀 Starting Santa Bot system...")
    
    # Запускаем веб-сервер в отдельном потоке (ДЛЯ HEALTH CHECK)
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    logger.info("✅ Web server started")
    
    # Ждем немного, чтобы веб-сервер точно запустился
    time.sleep(3)
    
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot started")
    logger.info("✅ System ready! Deployment should succeed.")
    
    # Главный поток ждет вечно
    try:
        while True:
            time.sleep(60)
            logger.info("💓 Heartbeat - system is alive")
    except KeyboardInterrupt:
        logger.info("👋 Shutting down...")

if __name__ == "__main__":
    main()
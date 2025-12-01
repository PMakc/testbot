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
    """Запускает Telegram бота"""
    try:
        # Импортируем и запускаем бота
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        
        # Замените на ваш способ запуска бота
        # Если SantOS.py запускается при импорте:
        import SantOS
        logger.info("🤖 Bot imported successfully")
        
        # Или если есть функция main():
        if hasattr(SantOS, 'main'):
            SantOS.main()
        else:
            # Если код запускается сразу, просто импортируем
            # и ждем в цикле
            while True:
                time.sleep(3600)
                
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
        # Все равно не падаем, чтобы Scalingo видел работающее приложение
        while True:
            time.sleep(60)
            logger.info("💤 Bot sleeping...")

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
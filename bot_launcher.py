#!/usr/bin/env python3
"""
bot_launcher.py - Единый запускатель для бота
Без лишних перезапусков, с правильным сохранением данных
"""

import os
import sys
import time
import signal
import logging
import threading
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - BOT - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Глобальная переменная для остановки
stop_requested = False

def signal_handler(sig, frame):
    """Обработчик сигналов остановки"""
    global stop_requested
    logger.info("🛑 Получен сигнал остановки, завершаю работу...")
    stop_requested = True
    sys.exit(0)

# Регистрируем обработчики сигналов
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def heartbeat():
    """Периодический heartbeat для мониторинга"""
    while not stop_requested:
        logger.info("💓 Бот активен")
        time.sleep(60)  # Логируем каждую минуту

def save_data_periodically(save_func, interval=300):
    """Периодическое сохранение данных (каждые 5 минут)"""
    while not stop_requested:
        time.sleep(interval)
        try:
            save_func()
            logger.info("💾 Данные сохранены автоматически")
        except Exception as e:
            logger.error(f"❌ Ошибка автосохранения: {e}")

def run_bot():
    """Запускает бота в бесконечном цикле"""
    
    logger.info("=" * 60)
    logger.info("🎅 ЗАПУСК БОТА ТАЙНОГО САНТЫ")
    logger.info(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    # Импортируем модуль бота
    try:
        import SantOS
        logger.info("✅ Модуль SantOS загружен")
    except ImportError as e:
        logger.error(f"❌ Не удалось импортировать SantOS: {e}")
        return False
    
    # Проверяем токен
    if not os.environ.get('BOT_TOKEN'):
        logger.error("❌ BOT_TOKEN не установлен!")
        return False
    
    # Проверяем токен через функцию бота
    try:
        if not SantOS.check_bot_token():
            logger.error("❌ Неверный токен бота!")
            return False
        logger.info("✅ Токен бота проверен")
    except Exception as e:
        logger.error(f"❌ Ошибка проверки токена: {e}")
        return False
    
    # Загружаем данные
    try:
        SantOS.load_data()
        logger.info(f"✅ Данные загружены: {len(SantOS.rooms)} комнат")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки данных: {e}")
        # Не прерываем работу, продолжаем с пустыми данными
    
    # Запускаем heartbeat в отдельном потоке
    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    
    # Запускаем автосохранение
    save_thread = threading.Thread(
        target=save_data_periodically, 
        args=(SantOS.save_data, 300),
        daemon=True
    )
    save_thread.start()
    
    # Основной цикл polling
    offset = 0
    import requests
    
    logger.info("⏳ Бот запущен, ожидание сообщений...")
    
    try:
        while not stop_requested:
            try:
                # Получаем обновления с увеличенным timeout
                response = requests.get(
                    f"{SantOS.BASE_URL}/getUpdates",
                    params={
                        'offset': offset + 1,
                        'timeout': 50,  # Увеличенный timeout
                        'limit': 100
                    },
                    timeout=55  # Чуть больше чем timeout в параметрах
                )
                
                if response.status_code != 200:
                    logger.error(f"❌ HTTP ошибка: {response.status_code}")
                    time.sleep(5)
                    continue
                
                data = response.json()
                
                if not data.get('ok'):
                    logger.error(f"❌ Telegram API error: {data}")
                    time.sleep(5)
                    continue
                
                updates = data.get('result', [])
                
                if updates:
                    logger.info(f"📨 Получено {len(updates)} сообщений")
                    
                    # Обрабатываем каждое обновление
                    for update in updates:
                        current_offset = update['update_id']
                        if current_offset > offset:
                            offset = current_offset
                        
                        # Обрабатываем в основном потоке для простоты
                        try:
                            SantOS.process_update(update)
                        except Exception as e:
                            logger.error(f"❌ Ошибка обработки update: {e}")
                            # Продолжаем обработку остальных сообщений
                
                # Короткая пауза если нет сообщений
                elif not updates and not stop_requested:
                    time.sleep(0.5)
                    
            except requests.exceptions.Timeout:
                # Таймаут - нормальная ситуация при long polling
                continue
                
            except requests.exceptions.ConnectionError:
                logger.error("🔌 Ошибка соединения, переподключение...")
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"❌ Ошибка в цикле polling: {e}")
                time.sleep(5)
        
        logger.info("👋 Основной цикл завершен")
        return True
        
    except Exception as e:
        logger.error(f"💥 Критическая ошибка в run_bot: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Главная функция с контролируемым перезапуском"""
    restart_count = 0
    last_restart_time = time.time()
    
    while not stop_requested:
        restart_count += 1
        current_time = time.time()
        
        # Защита от слишком частых перезапусков
        if restart_count > 10 and (current_time - last_restart_time) < 300:
            logger.error("🔴 Слишком частые перезапуски, ожидание 30 секунд...")
            time.sleep(30)
        
        logger.info(f"\n{'='*50}")
        logger.info(f"🚀 Попытка запуска #{restart_count}")
        logger.info(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
        logger.info(f"{'='*50}")
        
        try:
            # Запускаем бота
            success = run_bot()
            
            if stop_requested:
                logger.info("👋 Завершение работы по запросу")
                break
                
            if not success:
                logger.warning("⚠️ Бот завершился с ошибкой")
            
            # Пауза перед перезапуском
            wait_time = 2 if success else 5
            logger.info(f"🔄 Перезапуск через {wait_time} секунд...")
            
            for i in range(wait_time * 2):  # Проверяем stop_requested каждые 0.5 сек
                if stop_requested:
                    break
                time.sleep(0.5)
                
        except KeyboardInterrupt:
            logger.info("\n👋 Прервано пользователем")
            break
            
        except Exception as e:
            logger.error(f"💥 Неожиданная ошибка: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(10)
        
        last_restart_time = current_time

if __name__ == "__main__":
    main()
    
    # Финализация
    logger.info("✅ Бот завершил работу")
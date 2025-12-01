#!/usr/bin/env python3
"""
app.py - Основной запускающий файл для бота
Упрощенная версия с правильным бесконечным циклом
"""

import os
import sys
import time
import signal
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def signal_handler(sig, frame):
    """Обработчик сигналов остановки"""
    logger.info("🛑 Получен сигнал остановки")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def check_imports():
    """Проверяем доступность всех необходимых модулей"""
    try:
        import requests
        return True
    except ImportError as e:
        logger.error(f"❌ Не установлен модуль: {e}")
        logger.info("💡 Установите: pip install requests")
        return False

def main():
    """Основная функция запуска бота"""
    logger.info("=" * 50)
    logger.info("🎅 ЗАПУСК БОТА ТАЙНОГО САНТЫ")
    logger.info("=" * 50)
    
    # Проверяем импорты
    if not check_imports():
        time.sleep(10)
        return False
    
    # Проверяем токен
    BOT_TOKEN = os.environ.get('BOT_TOKEN')
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не установлен!")
        logger.info("💡 Установите переменную окружения BOT_TOKEN")
        time.sleep(10)
        return False
    
    # Динамический импорт SantOS для перехвата ошибок
    try:
        # Импортируем весь модуль
        from SantOS import (
            load_data, check_bot_token, process_update,
            rooms, user_rooms, user_states,
            BASE_URL, logger as santos_logger
        )
        
        logger.info("✅ SantOS успешно импортирован")
        
    except ImportError as e:
        logger.error(f"❌ Ошибка импорта SantOS: {e}")
        logger.info("💡 Проверьте наличие файла SantOS.py")
        import traceback
        traceback.print_exc()
        time.sleep(10)
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка при импорте SantOS: {e}")
        import traceback
        traceback.print_exc()
        time.sleep(10)
        return False
    
    # Загружаем данные
    try:
        load_data()
        logger.info("✅ Данные загружены")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки данных: {e}")
        time.sleep(5)
    
    # Проверяем токен бота
    try:
        if not check_bot_token():
            logger.error("❌ Неверный токен бота!")
            return False
        logger.info("✅ Токен бота проверен")
    except Exception as e:
        logger.error(f"❌ Ошибка проверки токена: {e}")
        time.sleep(5)
        return False
    
    # Основной бесконечный цикл polling
    offset = 0
    error_count = 0
    max_errors = 10
    
    logger.info("⏳ Запуск основного цикла обработки сообщений...")
    
    import requests
    
    while True:
        try:
            # Получаем обновления
            params = {
                'offset': offset + 1,
                'timeout': 30,
                'limit': 100
            }
            
            response = requests.get(f"{BASE_URL}/getUpdates", params=params, timeout=35)
            
            if response.status_code != 200:
                error_count += 1
                logger.error(f"❌ HTTP ошибка: {response.status_code}")
                
                if error_count >= max_errors:
                    logger.error(f"🔴 Слишком много ошибок ({error_count})")
                    return False
                
                time.sleep(5)
                continue
            
            data = response.json()
            
            if not data.get('ok'):
                error_count += 1
                logger.error(f"❌ Telegram API error: {data}")
                time.sleep(5)
                continue
            
            # Сбрасываем счетчик ошибок при успехе
            error_count = 0
            
            updates = data.get('result', [])
            
            if updates:
                logger.info(f"📨 Получено {len(updates)} сообщений")
                
                for update in updates:
                    current_offset = update['update_id']
                    if current_offset > offset:
                        offset = current_offset
                    
                    # Обрабатываем update в отдельном потоке или просто синхронно
                    try:
                        process_update(update)
                    except Exception as e:
                        logger.error(f"❌ Ошибка обработки сообщения: {e}")
                        # Не прерываем цикл из-за ошибки в одном сообщении
            
            else:
                # Нет сообщений - небольшая пауза
                time.sleep(1)
                
            # Периодический лог
            if int(time.time()) % 60 == 0:  # Каждую минуту
                logger.info(f"💓 Бот активен, offset: {offset}, комнат: {len(rooms)}, пользователей: {len(user_states)}")
            
        except requests.exceptions.Timeout:
            logger.warning("⏱️ Таймаут запроса, продолжаем...")
            time.sleep(2)
            
        except requests.exceptions.ConnectionError:
            error_count += 1
            logger.error("🔌 Ошибка соединения")
            time.sleep(5)
            
        except Exception as e:
            error_count += 1
            logger.error(f"❌ Неожиданная ошибка: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            
            if error_count >= max_errors:
                logger.error("🔴 Критическое количество ошибок, перезапуск...")
                return False
            
            time.sleep(5)
    
    return True

if __name__ == "__main__":
    # Внешний цикл перезапуска
    restart_count = 0
    
    while True:
        restart_count += 1
        start_time = time.time()
        
        logger.info(f"\n{'='*50}")
        logger.info(f"🚀 ЗАПУСК #{restart_count}")
        logger.info(f"⏰ Время запуска: {datetime.now().strftime('%H:%M:%S')}")
        logger.info(f"{'='*50}\n")
        
        try:
            success = main()
            
            if success:
                # main() никогда не должен вернуть True если работает правильно
                logger.info("ℹ️ main() завершился без ошибок, но должен работать бесконечно")
                time.sleep(5)
            else:
                logger.info("⚠️ main() завершился с ошибкой, перезапуск...")
                
        except KeyboardInterrupt:
            logger.info("\n👋 Остановлено пользователем")
            break
            
        except Exception as e:
            logger.error(f"💥 Критическая ошибка в главном цикле: {e}")
            import traceback
            traceback.print_exc()
        
        # Пауза перед перезапуском
        wait_time = 5
        logger.info(f"🔄 Перезапуск через {wait_time} секунд...\n")
        time.sleep(wait_time)
import os
import csv
import logging
import time
import base64
from pathlib import Path
from dotenv import load_dotenv

# Импортируем класс OpenAI и базовые ошибки
import openai
from openai import OpenAI, OpenAIError

# Загрузка переменных окружения из .env файла
load_dotenv()

# Установите API-ключ OpenAI из переменных окружения
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logging.error("API-ключ OpenAI не найден. Установите его в OPENAI_API_KEY.")
    exit(1)

# Настраиваем логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Инициализируем клиента согласно новой документации
client = OpenAI(api_key=OPENAI_API_KEY)

# Файлы конфигурации
CSV_FILE = "product.csv"      # CSV, который будем обновлять
IMAGES_DIR = "images"         # Папка с изображениями
PROMPT_FILE = "prompt.txt"    # Файл с текстом промпта

# Приоритет моделей (пример из вашей конфигурации)
PRIMARY_MODEL = "gpt-4o-mini"
FALLBACK_MODEL = "gpt-4o"

def load_prompt(file_path):
    """Загружает текст промпта из файла."""
    if not os.path.exists(file_path):
        logging.error(f"Файл промпта '{file_path}' не найден.")
        exit(1)
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def encode_image_to_base64(image_path):
    """Кодирует изображение в формат base64."""
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode('utf-8')

def analyze_image_with_model(image_base64, prompt, model):
    """
    Отправляет изображение (base64) и текстовый prompt модели для анализа.
    Согласно свежей документации, контент внутри messages передаётся
    в виде списка объектов: [{'type':'text', 'text': prompt}, {'type':'image_url', ...}].
    """
    try:
        # Создаём запрос к модели
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        # 1) Текстовая часть промпта
                        {"type": "text", "text": prompt},
                        # 2) Изображение в base64 (формат data:image/jpeg;base64,...)
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            },
                        },
                    ],
                },
            ],
        )

        # В новой версии SDK метод возвращает объект, но доступ к
        # choices[0].message.content работает аналогично
        return response.choices[0].message.content

    except OpenAIError as e:
        logging.error(f"Ошибка при использовании модели {model}: {e}")
        return None

def analyze_images(folder_name, image_paths, prompt):
    """Анализирует список изображений и возвращает список (img_path, caption)."""
    results = []
    for img_path in image_paths:
        try:
            logging.info(f"Анализируем изображение: {img_path}")
            image_base64 = encode_image_to_base64(img_path)

            # 1) Пытаемся первичной моделью
            caption = analyze_image_with_model(image_base64, prompt, PRIMARY_MODEL)

            # Если не получилось, пробуем fallback
            if not caption:
                logging.warning(f"Переход к {FALLBACK_MODEL} для изображения {img_path}.")
                caption = analyze_image_with_model(image_base64, prompt, FALLBACK_MODEL)

            # Если и второй раз не вернулось caption — пишем ошибку
            if caption:
                logging.debug(f"Результат анализа для {img_path}: {caption}")
                results.append((img_path, caption))
            else:
                logging.error(f"Не удалось получить результат анализа для {img_path}.")

        except Exception as e:
            logging.error(f"Ошибка анализа изображения {img_path}: {e}")

    return results

def select_images(analysis_results):
    """
    Выбирает подходящие изображения:
    - Full (полностью виден костюм),
    - Top (возможно пиджак/верх),
    - Bottom (брюки/низ).

    Условие отбора - простая проверка по ключевым словам.
    """
    full_image = None
    top_image = None
    bottom_image = None

    for img_path, caption in analysis_results:
        caption_lower = caption.lower()
        if "full body" in caption_lower or "overall look" in caption_lower:
            if not full_image:
                full_image = img_path
        elif "jacket" in caption_lower or "upper body" in caption_lower:
            if not top_image:
                top_image = img_path
        elif "pants" in caption_lower or "lower body" in caption_lower:
            if not bottom_image:
                bottom_image = img_path

    return full_image, top_image, bottom_image

def update_csv(csv_file, folder_name, full_image, top_image, bottom_image):
    """Обновляет CSV-файл, меняя колонки 'Image' и 'Ext Images'."""
    updated_rows = []
    with open(csv_file, 'r', encoding='utf-8-sig') as file:
        reader = csv.DictReader(file, delimiter=';')
        fieldnames = reader.fieldnames

        for row in reader:
            # Если название папки встречается в колонке Name, обновляем
            if folder_name[3::].lower() in row['Name'].lower():
                logging.info(f"Обновляем записи для {folder_name} в CSV.")
                if full_image:
                    row['Image'] = full_image

                ext_images = []
                if top_image:
                    ext_images.append(top_image)
                if bottom_image:
                    ext_images.append(bottom_image)

                row['Ext Images'] = ','.join(ext_images)

            updated_rows.append(row)

    # Перезаписываем CSV
    with open(csv_file, 'w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, delimiter=';')
        writer.writeheader()
        writer.writerows(updated_rows)

    logging.info(f"CSV файл '{csv_file}' обновлен.")

def main():
    start_time = time.time()

    # Загружаем текст промпта из файла
    prompt = load_prompt(PROMPT_FILE)

    # Проверяем папку с изображениями
    if not os.path.exists(IMAGES_DIR):
        logging.error(f"Папка с изображениями '{IMAGES_DIR}' не найдена.")
        exit(1)

    # Находим подпапки, в которых есть "костюм" или "смокинг" в названии
    subfolders = [
        f for f in os.listdir(IMAGES_DIR)
        if os.path.isdir(os.path.join(IMAGES_DIR, f))
           and ("костюм" in f.lower() or "смокинг" in f.lower())
    ]

    if not subfolders:
        logging.warning("Не найдено папок, соответствующих 'костюм' или 'смокинг'.")
        exit(1)

    # Перебираем каждую подпапку
    for folder_name in subfolders:
        folder_path = os.path.join(IMAGES_DIR, folder_name)
        image_files = [
            os.path.join(folder_path, f) for f in os.listdir(folder_path)
            if f.lower().endswith(('.jpg', '.jpeg', '.png'))
        ]

        if not image_files:
            logging.warning(f"В папке '{folder_name}' нет изображений. Пропускаем.")
            continue

        # Анализируем все изображения в папке
        analysis_results = analyze_images(folder_name, image_files, prompt)

        # Выбираем «лучшее» full_image, top_image, bottom_image
        full_image, top_image, bottom_image = select_images(analysis_results)

        # Обновляем CSV
        update_csv(CSV_FILE, folder_name, full_image, top_image, bottom_image)

    end_time = time.time()
    logging.info(f"Обновление CSV завершено. Время: {end_time - start_time:.2f} секунд.")

if __name__ == "__main__":
    main()

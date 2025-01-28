import os
import csv
import logging
import time
import base64
import requests
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

# Загрузка переменных окружения из .env файла
load_dotenv()

# Установите API-ключ OpenAI из переменных окружения
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logging.error("API-ключ OpenAI не найден. Пожалуйста, установите его в переменную окружения OPENAI_API_KEY.")
    exit(1)

# Настройка прокси
proxy_ip = os.getenv("PROXY_IP")
port = os.getenv("PROXY_PORT")
proxy_username = os.getenv("PROXY_USERNAME")
proxy_password = os.getenv("PROXY_PASSWORD")

if proxy_username and proxy_password:
    PROXY = {
        "http": f"http://{proxy_username}:{proxy_password}@{proxy_ip}:{port}",
        "https": f"http://{proxy_username}:{proxy_password}@{proxy_ip}:{port}"
    }
else:
    PROXY = {
        "http": f"http://{proxy_ip}:{port}",
        "https": f"http://{proxy_ip}:{port}"
    }

# Установка переменных окружения для прокси
os.environ["HTTP_PROXY"] = PROXY["http"]
os.environ["HTTPS_PROXY"] = PROXY["https"]

# Настраиваем логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Проверка доступности прокси
def test_proxy(proxies):
    try:
        test_url = "https://httpbin.org/ip"
        logging.info("Проверка прокси...")
        response = requests.get(test_url, proxies=proxies, timeout=10)
        if response.status_code == 200:
            logging.info(f"Прокси работает. Ответ: {response.json()}")
        else:
            logging.error(f"Прокси ответил с кодом: {response.status_code}")
            exit(1)
    except requests.RequestException as e:
        logging.error(f"Ошибка подключения через прокси: {e}")
        exit(1)

# Проверка прокси перед запуском
test_proxy(PROXY)

# Конфигурация
client = OpenAI(api_key=OPENAI_API_KEY)
CSV_FILE = "product.csv"      # Файл, который будем обновлять
IMAGES_DIR = "images"         # Папка с изображениями
PROMPT_FILE = "prompt.txt"    # Файл с текстом промпта

# Приоритет моделей
PRIMARY_MODEL = "gpt-4o-mini"    # Замените на актуальное название модели
FALLBACK_MODEL = "gpt-4o"        # Замените на актуальное название модели 

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
    """Отправляет изображение и промпт модели для анализа через прокси."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Анализируй следующее изображение. data:image/jpeg;base64,{image_base64}"}
            ]
        )
        return response["choices"][0]["message"]["content"]
    except OpenAIError as e:
        logging.error(f"Ошибка при использовании модели {model}: {e}")
        return None

def analyze_images(folder_name, image_paths, prompt):
    """Анализирует изображения и возвращает подходящие фото."""
    results = []
    for img_path in image_paths:
        try:
            logging.info(f"Анализируем изображение: {img_path}")
            image_base64 = encode_image_to_base64(img_path)

            # Попробуем использовать основную модель
            caption = analyze_image_with_model(image_base64, prompt, PRIMARY_MODEL)

            if not caption:
                logging.warning(f"Переход к {FALLBACK_MODEL} для изображения {img_path}.")
                # Попробуем fallback-модель
                caption = analyze_image_with_model(image_base64, prompt, FALLBACK_MODEL)

            if caption:
                logging.debug(f"Результат анализа для {img_path}: {caption}")
                results.append((img_path, caption))
            else:
                logging.error(f"Не удалось получить результат анализа для {img_path}.")
        except Exception as e:
            logging.error(f"Ошибка анализа изображения {img_path}: {e}")
    return results

def select_images(analysis_results):
    """Выбирает подходящие изображения для Full, Top и Bottom."""
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
    """Обновляет CSV-файл с новыми путями изображений."""
    updated_rows = []
    with open(csv_file, 'r', encoding='utf-8-sig') as file:
        reader = csv.DictReader(file, delimiter=';')
        fieldnames = reader.fieldnames
        for row in reader:
            if folder_name.lower() in row['Name'].lower():
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

    with open(csv_file, 'w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, delimiter=';')
        writer.writeheader()
        writer.writerows(updated_rows)

    logging.info(f"CSV файл '{csv_file}' обновлен.")

def main():
    start_time = time.time()

    # Загружаем промпт
    prompt = load_prompt(PROMPT_FILE)

    # Проверяем папку изображений
    if not os.path.exists(IMAGES_DIR):
        logging.error(f"Папка с изображениями '{IMAGES_DIR}' не найдена.")
        exit(1)

    # Собираем подпапки с "костюмами" или "смокингами"
    subfolders = [
        f for f in os.listdir(IMAGES_DIR)
        if os.path.isdir(os.path.join(IMAGES_DIR, f)) and ("костюм" in f.lower() or "смокинг" in f.lower())
    ]

    if not subfolders:
        logging.warning("Не найдено папок, соответствующих 'костюм' или 'смокинг'.")
        exit(1)

    # Проходим по каждой папке
    for folder_name in subfolders:
        folder_path = os.path.join(IMAGES_DIR, folder_name)
        image_files = [
            os.path.join(folder_path, f) for f in os.listdir(folder_path)
            if f.lower().endswith(('.jpg', '.jpeg', '.png'))
        ]

        if not image_files:
            logging.warning(f"В папке '{folder_name}' нет изображений. Пропускаем.")
            continue

        # Анализируем изображения
        analysis_results = analyze_images(folder_name, image_files, prompt)

        # Выбираем подходящие изображения
        full_image, top_image, bottom_image = select_images(analysis_results)

        # Обновляем CSV
        update_csv(CSV_FILE, folder_name, full_image, top_image, bottom_image)

    end_time = time.time()
    logging.info(f"Обновление CSV завершено. Время выполнения: {end_time - start_time:.2f} секунд.")

if __name__ == "__main__":
    main()

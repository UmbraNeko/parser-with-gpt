import requests
from bs4 import BeautifulSoup
import csv
import re
import os
import shutil
import json
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# Глобальный словарь для костюмов/смокингов: { "название_товара": [список_ссылок], ... }
suits_dict = {}

def get_product_data(url, external_id, index):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/117.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
    except requests.exceptions.HTTPError as http_err:
        print(f"Произошла HTTP ошибка: {http_err}")
        return {
            'ID': external_id, 
            'Brand': 'N/A', 
            'Name': 'N/A', 
            'Article': 'N/A', 
            'URL': url, 
            'Image': 'N/A', 
            'Ext Images': 'N/A', 
            'Gender': 'N/A', 
            'Description': 'N/A'
        }
    except Exception as err:
        print(f"Произошла другая ошибка: {err}")
        return {
            'ID': external_id, 
            'Brand': 'N/A', 
            'Name': 'N/A', 
            'Article': 'N/A', 
            'URL': url, 
            'Image': 'N/A', 
            'Ext Images': 'N/A', 
            'Gender': 'N/A', 
            'Description': 'N/A'
        }
    
    soup = BeautifulSoup(response.text, 'html.parser')

    product_brand = 'N/A'
    product_name = 'N/A'
    product_article = 'N/A'
    product_image = 'N/A'
    product_other_images = []
    product_gender = 'N/A'
    product_description = ''
    product_size = ''
    product_color = ''
    product_category = ''

    # Бренд
    product_brand_tag = soup.find('span', {'class': 'description__visuallyHidden____sjk5'})
    if product_brand_tag:
        product_brand = product_brand_tag.get_text(strip=True)

    # Название
    product_name_tag = soup.find('h1', {'data-test-id': 'productTitle'})
    if product_name_tag:
        product_name_span = product_name_tag.find('span', class_='description__visuallyHidden____sjk5')
        if product_name_span:
            raw_name = product_name_tag.text.strip()
            raw_hidden = product_name_span.text.strip()
            # Убираем скрытый <span> из полного текста:
            product_name = raw_name.replace(raw_hidden, '').strip()
            product_name = clean_text(product_name)

    # Артикул
    article_tag = soup.find('li', string=lambda t: t and "Артикул:" in t)
    if article_tag:
        product_article = article_tag.get_text(strip=True).replace('Артикул:', '').strip()
        product_article = clean_text(product_article)

    # Гендер
    gender_tag = soup.select_one('ul.Breadcrumbs__breadcrumbs___dbDQw a[href*="/catalog/muzhskoe-"], a[href*="/catalog/zhenskoe-"], a[href*="/catalog/unisex-"]')
    if gender_tag:
        if 'muzhskoe' in gender_tag['href']:
            product_gender = 'male'
        elif 'zhenskoe' in gender_tag['href']:
            product_gender = 'female'
        elif 'unisex' in gender_tag['href']:
            product_gender = 'unisex'

    # Описание
    description_tag = soup.find('section', {
        'class': 'SegmentsView__section___jGPx8 SegmentsView__section_show___BWJGT', 
        'data-test-id': 'productInfoSectionWrapper'
    })
    if description_tag:
        description_p = description_tag.find('p')
        if description_p:
            product_description = clean_text(description_p.get_text(strip=True))

    # Размер
    size_data = soup.find('ul', {
        'class': 'Sizes__sizes___geUvy', 
        'data-test-id': 'productSizeWrapper'
    })
    if size_data:
        collected_sizes = []
        for size_tag in size_data.find_all('li'):
            class_li = size_tag.get('class', [])
            # Игнорируем li, у которых классы 'Sizes__sizesMobileTitle___skPu9' или 'Sizes__uppercase___U1DRS'
            if ('Sizes__sizesMobileTitle___skPu9' not in class_li and 
                'Sizes__uppercase___U1DRS' not in class_li):
                spans = size_tag.find_all('span')
                if spans:
                    # Берём последний span, предположительно содержащий сам размер
                    size_span_text = spans[-1].get_text(strip=True)
                    if size_span_text:
                        collected_sizes.append(clean_text(size_span_text))
        if collected_sizes:
            product_size = ",".join(collected_sizes)

    # Цвет
    color_tag = soup.find('span', {'class': 'SingleColor__colorTitle___VTGcs'})
    product_color = color_tag.get_text(strip=True) if color_tag else 'N/A'

    # Категория
    breadcrumbs_tag = soup.find('ul', {'class': 'Breadcrumbs__breadcrumbs___dbDQw'})
    if breadcrumbs_tag:
        last_breadcrumb = breadcrumbs_tag.find_all('li')[-1]
        category_link = last_breadcrumb.find('a')
        product_category = category_link.get_text(strip=True) if category_link else 'N/A'

    # Проверяем "костюм" / "смокинг"
    keywords = ["костюм", "смокинг"]
    pattern = rf'\b(?:{"|".join(map(re.escape, keywords))})\b'
    contains_keywords = re.search(pattern, product_name, re.IGNORECASE) if product_name else False

    # Извлекаем ссылки на изображения
    product_images = get_images(
        soup=soup,
        base_url=url,
        product_name=product_name,
        index=index,
        contains_keywords=contains_keywords
    )

    # Логика выбора 1-й фото (Image) и "Ext Images" (2, 3, 4...) для CSV
    if len(product_images) >= 4:
        product_image = product_images[2]  # третья
        product_other_images = [product_images[1], product_images[3]]
    elif len(product_images) == 3:
        product_image = product_images[1]  # вторая
        product_other_images = [product_images[0], product_images[2]]
    elif len(product_images) == 2:
        product_image = product_images[1]
        product_other_images = [product_images[0]]
    elif len(product_images) == 1:
        product_image = product_images[0]

    # Результат
    product_data = {
        'ID': external_id,
        'Brand': product_brand,
        'Name': product_name,
        'Article': product_article,
        'URL': url,
        'Image': product_image,
        'Ext Images': ','.join(product_other_images),
        'Gender': product_gender,
        'Description': product_description,
        'Sizes': product_size,
        'Color': product_color,
        'Category': product_category
    }
    return product_data

def clean_text(text):
    """Удаляем непечатаемые символы и NUL."""
    return re.sub(r'[^\x20-\x7Eа-яА-ЯёЁ]', '', text)

def get_images(soup, base_url, product_name, index, contains_keywords):
    """
    Собираем ссылки из div.Desktop__slide___S6W7J
    * Если contains_keywords=True (есть "костюм"/"смокинг" в названии):
      - Собираем все фото, без ограничений
    * Иначе (нет "костюм"/"смокинг"):
      - Ограничиваемся максимум 4 картинками, пропуская первую при exactly 4
    * При этом избавляемся от дубликатов через set().
    """
    slide_divs = soup.find_all('div', {'class': 'Desktop__slide___S6W7J'})
    
    # Используем set, чтобы отфильтровать повторяющиеся ссылки
    images_set = set()

    if contains_keywords:
        for i, div in enumerate(slide_divs):
            image_tag = div.find('img')
            if image_tag:
                image_url = image_tag.get('data-src', image_tag.get('src', 'N/A'))
                absolute_image_url = urljoin(base_url, image_url)
                if absolute_image_url not in images_set:
                    images_set.add(absolute_image_url)
                    # Сохраняем файл
                    save_image(absolute_image_url, index, i+1, product_name)
        # Сохраняем эти ссылки в глобальный suits_dict
        suits_dict[product_name] = list(images_set)
    else:
        # Если НЕ костюм / смокинг, берём до 4 фото (пропуская 1-ю если их ровно 4)
        for i, div in enumerate(slide_divs):
            if i >= 4:
                break
            if len(slide_divs) == 4 and i == 0:
                # пропускаем первый div, если всего их 4
                continue
            image_tag = div.find('img')
            if image_tag:
                image_url = image_tag.get('data-src', image_tag.get('src', 'N/A'))
                absolute_image_url = urljoin(base_url, image_url)
                if absolute_image_url not in images_set:
                    images_set.add(absolute_image_url)
                    save_image(absolute_image_url, index, i+1, product_name)

    # Превращаем множество в список и возвращаем
    images = list(images_set)
    return images

def save_image(url, index, image_number, product_name):
    """
    Сохраняет картинку в папку images/{index+1}. {product_name}/image{image_number}.jpg
    """
    folder_name = f"images/{index+1}. {product_name}"
    os.makedirs(folder_name, exist_ok=True)

    response = requests.get(url)
    if response.status_code == 200:
        filename = f"image{image_number}.jpg"
        file_path = os.path.join(folder_name, filename)
        with open(file_path, 'wb') as f:
            f.write(response.content)

# --- ОСНОВНОЙ КОД ---

# Перед запуском удаляем папку images, чтобы каждый раз начинать "с нуля"
if os.path.exists('images'):
    shutil.rmtree('images')

BASE_URL = 'https://www.tsum.ru/product/'
links = []
external_ids = []

# Считываем IDs из файла
with open('IDs.txt', 'r', encoding='utf-8') as file:
    for line in file:
        external_id = line.strip()
        external_ids.append(external_id)
        links.append(f"{BASE_URL}{external_id}")

print(f"Всего ID в файле: {len(external_ids)}")

# Проверяем, что кол-во ссылок соответствует кол-ву ID
if len(links) != len(external_ids):
    print("Ошибка: количество ссылок и внешних ID не совпадает.")
    exit(1)

# Получаем уже имеющиеся external_item_id из базы (если нужно)
def fetch_all_ext_ids():
    base_url = "https://prod.api-landing.com/api/get_company_items"
    company_id = "tsum_cs"
    limit = 10000
    page = 1
    ext_ids = []

    while True:
        params = {
            "company_id": company_id,
            "limit": limit,
            "page": page
        }
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        data_json = response.json()
        
        if not data_json:
            break

        for item in data_json:
            if "external_item_id" in item:
                ext_ids.append(item["external_item_id"])
        page += 1

    print(f"Всего найдено external_id в базе данных: {len(ext_ids)}")
    return ext_ids

ext_ids_bd = fetch_all_ext_ids()

# Подготовка CSV
with open('product.csv', mode='w', newline='', encoding='utf-8-sig') as file:
    writer = csv.writer(file, delimiter=';')
    writer.writerow([
        'URL', 'ID', 'Name', 'Brand', 'Article', 'Gender', 
        'Image', 'Ext Images', 'Description', 'Sizes', 
        'Color', 'Category'
    ])

    results = [None] * len(links)
    data = []
    count_new_items = 0

    def process_link(link, external_id, index):
        # проверка на дубли
        if external_id not in data:
            if external_id not in ext_ids_bd:
                data.append(external_id)
                return get_product_data(link, external_id, index)

    # Запускаем многопоточную загрузку
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {
            executor.submit(process_link, link, external_id, i): i
            for i, (link, external_id) in enumerate(zip(links, external_ids))
        }

        with tqdm(total=len(futures), desc="Обработка ссылок", unit=" запросов") as pbar:
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    product = future.result(timeout=10)
                    results[idx] = product
                    pbar.update(1)
                except Exception as e:
                    print(f"Ошибка при обработке ссылки {links[idx]}: {e}")
                    pbar.update(1)

    # Записываем результат в том же порядке
    for product in results:
        if product:
            # Отсекаем 'unisex', если нужно
            if product['Gender'] != 'unisex':
                # Проверяем, что есть нормальное имя
                if product['Name'] != 'N/A':
                    writer.writerow([
                        product['URL'],
                        product['ID'],
                        product['Name'],
                        product['Brand'],
                        product['Article'],
                        product['Gender'],
                        product['Image'],
                        product['Ext Images'],
                        product['Description'],
                        product['Sizes'],
                        product['Color'],
                        product['Category']
                    ])
                    count_new_items += 1

print("Количество спаршенных айтемов:", count_new_items, "из", len(external_ids))
print("Данные успешно извлечены и сохранены в product.csv")

# Сохраняем suits_dict в JSON, чтобы видеть все ссылки для костюмов/смокингов
if suits_dict:
    with open("suits.json", "w", encoding="utf-8") as jf:
        json.dump(suits_dict, jf, ensure_ascii=False, indent=2)
    print("JSON для костюмов/смокингов сохранён в 'suits.json'.")
else:
    print("Не найдено товаров с 'костюм' или 'смокинг'. JSON не создан.")

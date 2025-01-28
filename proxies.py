import requests

# Настройки прокси
proxy_ip = "200.174.198.86"
port = 8888
proxies = {
    "http": "http://{}:{}".format(proxy_ip, port),
    "https": "http://{}:{}".format(proxy_ip, port)
}


# URL для тестирования (можно заменить на нужный)
url = "https://httpbin.org/ip"

try:
    # Выполняем запрос через прокси
    response = requests.get(url, proxies=proxies, timeout=10)
    # Выводим результат
    print("Ответ от сервера:", response.json())
except requests.exceptions.RequestException as e:
    # Обработка ошибок
    print("Ошибка при подключении:", e)

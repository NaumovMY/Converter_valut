# Подключаем нужные библиотеки
import json          # чтобы сохранять курсы в файл кэша
import logging       # чтобы записывать логи (что происходит в программе)
import os            # чтобы проверять, существует ли файл
import xml.etree.ElementTree as ET  # чтобы разбирать XML от ЦБ РФ
import requests      # чтобы делать запросы в интернет
from decimal import Decimal, ROUND_HALF_UP  # для точных денежных расчётов

# Настраиваем логирование: сообщения будут писаться в файл conversion.log
# и одновременно показываться в консоли
logging.basicConfig(
    level=logging.INFO,  # показываем все сообщения уровня INFO и выше
    format='%(asctime)s - %(levelname)s - %(message)s',  # формат: дата - уровень - текст
    handlers=[
        logging.FileHandler('conversion.log', encoding='utf-8'),  # пишем в файл
        logging.StreamHandler()  # и в консоль
    ]
)
logger = logging.getLogger(__name__)  # создаём логгер для этого файла


class CurrencyConverter:
    """Класс, который умеет конвертировать валюты по курсам ЦБ РФ."""

    # Адреса, откуда будем брать курсы.
    # Сначала пробуем зеркало, если не получится — официальный сайт ЦБ.
    PRIMARY_URL = "https://www.cbr-xml-daily.ru/daily.xml"
    FALLBACK_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
    CACHE_FILE = "cache.json"  # файл, куда сохраняем курсы на случай отсутствия интернета
    SUPPORTED = {"USD", "EUR", "RUB"}  # валюты, с которыми умеем работать

    def __init__(self):
        # Session — это как «браузер» внутри программы.
        # Он запоминает настройки и может переиспользовать соединение.
        self._session = requests.Session()
        # Некоторые сайты блокируют запросы без User-Agent,
        # поэтому представляемся обычным браузером
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CurrencyConverter/1.0"
        })

    def _parse_cbr_xml(self, xml_text):
        """Разбирает XML от ЦБ РФ и возвращает словарь {код валюты: курс к рублю}."""
        # Превращаем текст XML в объект, с которым можно работать
        root = ET.fromstring(xml_text)
        # Рубль к самому себе всегда равен 1
        rates = {"RUB": Decimal("1.0")}

        # Проходим по каждому тегу <Valute> (это одна валюта)
        for valute in root.findall("Valute"):
            # Достаём код валюты (например, "USD")
            code = valute.find("CharCode").text
            # Достаём номинал (обычно 1, но бывает 10, 100 и т.д.)
            nominal = int(valute.find("Nominal").text)
            # Достаём значение курса. В XML запятая вместо точки — заменяем
            value = Decimal(valute.find("Value").text.replace(",", "."))
            # Делим на номинал, чтобы получить курс за 1 единицу валюты
            rates[code] = value / Decimal(nominal)

        return rates

    def _fetch_rates(self):
        """Пробует скачать курсы сначала с одного сайта, потом с другого."""
        # Проходим по списку адресов: сначала основной, потом запасной
        for url in (self.PRIMARY_URL, self.FALLBACK_URL):
            try:
                # Делаем запрос. timeout=10 — ждём ответа не больше 10 секунд
                response = self._session.get(url, timeout=10)
                # Если сервер вернул ошибку (например, 404), здесь будет исключение
                response.raise_for_status()
                # Разбираем полученный XML в словарь курсов
                rates = self._parse_cbr_xml(response.text)
                logger.info(f"Курсы ЦБ РФ получены с {url}")
                return rates
            except Exception as e:
                # Если что-то пошло не так — записываем в лог и пробуем следующий адрес
                logger.warning(f"Не удалось получить курсы с {url}: {e}")
                continue
        # Если оба адреса не сработали — сообщаем об ошибке
        raise ConnectionError("Не удалось получить курсы ЦБ РФ ни с одного источника.")

    def _load_cache(self):
        """Читает сохранённые курсы из файла cache.json."""
        # Если файла нет — возвращаем пустой словарь
        if not os.path.exists(self.CACHE_FILE):
            return {}
        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # Если файл повреждён или не читается — пишем в лог и возвращаем пусто
            logger.warning("Не удалось прочитать кэш, создаём новый.")
            return {}

    def _save_cache(self, rates):
        """Сохраняет курсы в файл cache.json."""
        try:
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                # Decimal нельзя сохранить в JSON напрямую, поэтому превращаем в строки
                json.dump({k: str(v) for k, v in rates.items()}, f,
                          ensure_ascii=False, indent=2)
        except IOError:
            logger.error("Не удалось сохранить кэш.")

    def get_rate(self, from_curr, to_curr):
        """Возвращает курс из одной валюты в другую (например, USD → EUR)."""
        # Приводим коды валют к верхнему регистру, чтобы "usd" и "USD" работали одинаково
        from_curr = from_curr.upper()
        to_curr = to_curr.upper()

        # Проверяем, что обе валюты поддерживаются
        if from_curr not in self.SUPPORTED or to_curr not in self.SUPPORTED:
            raise ValueError(
                f"Валюта не поддерживается. Доступны: {', '.join(self.SUPPORTED)}"
            )

        # Если валюты одинаковые — курс 1, даже не идём в интернет
        if from_curr == to_curr:
            return Decimal("1.0")

        # Пытаемся скачать свежие курсы
        try:
            rates = self._fetch_rates()
            self._save_cache(rates)  # и сразу сохраняем их в кэш
        except ConnectionError:
            # Если интернет не работает — берём последние сохранённые курсы
            logger.error("Нет соединения с ЦБ РФ, пробуем кэш...")
            cached = self._load_cache()
            if not cached:
                raise ConnectionError("Нет соединения и нет сохранённых курсов.")
            # Превращаем строки из JSON обратно в Decimal
            rates = {k: Decimal(v) for k, v in cached.items()}
            logger.info("Использованы курсы из кэша.")

        # Проверяем, что нужные валюты есть в словаре курсов
        if from_curr not in rates or to_curr not in rates:
            raise ValueError(f"Курс для {from_curr} или {to_curr} не найден в данных ЦБ РФ.")

        # ЦБ даёт курсы только к рублю. Поэтому считаем через рубль:
        # сколько рублей стоит 1 единица from_curr, делим на стоимость 1 единицы to_curr
        rate = rates[from_curr] / rates[to_curr]
        # Округляем курс до 4 знаков после запятой
        return rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    def convert(self, amount, from_curr, to_curr):
        """Конвертирует сумму из одной валюты в другую."""
        # Сумма должна быть больше нуля
        if amount <= 0:
            raise ValueError("Сумма должна быть положительным числом.")

        # Получаем курс
        rate = self.get_rate(from_curr, to_curr)
        # Умножаем сумму на курс и округляем до копеек (2 знака)
        result = (Decimal(str(amount)) * rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Записываем в лог, что мы сконвертировали
        logger.info(
            f"Конвертация: {amount} {from_curr.upper()} → {result} {to_curr.upper()} "
            f"(курс ЦБ РФ: {rate})"
        )
        return result
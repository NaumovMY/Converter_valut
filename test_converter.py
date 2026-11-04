# Импортируем стандартный модуль для тестов
import unittest
from decimal import Decimal
# MagicMock — это «заглушка», которая притворяется объектом (например, ответом сервера)
from unittest.mock import patch, MagicMock
import requests
import os
import json
import logging

# Отключаем логирование, чтобы сообщения из converter.py не засоряли вывод тестов
logging.disable(logging.CRITICAL)

from converter import CurrencyConverter


# Тестовый XML, который как будто пришёл от ЦБ РФ.
# Так тесты не зависят от интернета и работают всегда одинаково.
SAMPLE_XML = """<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="29.10.2026" name="Foreign Currency Market">
    <Valute ID="R01235">
        <NumCode>840</NumCode>
        <CharCode>USD</CharCode>
        <Nominal>1</Nominal>
        <Name>Доллар США</Name>
        <Value>90,0000</Value>
    </Valute>
    <Valute ID="R01239">
        <NumCode>978</NumCode>
        <CharCode>EUR</CharCode>
        <Nominal>1</Nominal>
        <Name>Евро</Name>
        <Value>100,0000</Value>
    </Valute>
</ValCurs>"""


class TestCurrencyConverter(unittest.TestCase):
    """Проверяем, что конвертер правильно работает в разных ситуациях."""

    def setUp(self):
        """Выполняется ПЕРЕД каждым тестом: создаём свежий конвертер."""
        self.converter = CurrencyConverter()
        # Удаляем старый кэш, чтобы тесты не влияли друг на друга
        if os.path.exists(self.converter.CACHE_FILE):
            os.remove(self.converter.CACHE_FILE)

    def tearDown(self):
        """Выполняется ПОСЛЕ каждого теста: убираем кэш за собой."""
        if os.path.exists(self.converter.CACHE_FILE):
            os.remove(self.converter.CACHE_FILE)

    # ---------- Проверяем разбор XML ----------

    def test_parse_cbr_xml(self):
        """XML ЦБ правильно превращается в словарь курсов."""
        rates = self.converter._parse_cbr_xml(SAMPLE_XML)
        # Рубль всегда 1
        self.assertEqual(rates["RUB"], Decimal("1.0"))
        # Доллар — 90 рублей
        self.assertEqual(rates["USD"], Decimal("90.0"))
        # Евро — 100 рублей
        self.assertEqual(rates["EUR"], Decimal("100.0"))

    def test_parse_cbr_xml_with_nominal(self):
        """Если у валюты номинал 10, курс нужно поделить на 10."""
        # Пример: 10 японских йен стоят 5 рублей → 1 йена = 0.5 рубля
        xml = """<ValCurs>
            <Valute>
                <CharCode>JPY</CharCode>
                <Nominal>10</Nominal>
                <Value>5,0000</Value>
            </Valute>
        </ValCurs>"""
        rates = self.converter._parse_cbr_xml(xml)
        self.assertEqual(rates["JPY"], Decimal("0.5"))

    # ---------- Проверяем get_rate ----------

    @patch('requests.Session.get')
    def test_get_rate_usd_to_eur(self, mock_get):
        """USD → EUR считается через рубль: 90 / 100 = 0.9."""
        # Готовим «поддельный ответ сервера» с нашим XML
        mock_response = MagicMock()
        mock_response.text = SAMPLE_XML
        mock_response.raise_for_status.return_value = None
        # Говорим: когда код вызовет get(), верни этот поддельный ответ
        mock_get.return_value = mock_response

        rate = self.converter.get_rate("USD", "EUR")
        self.assertEqual(rate, Decimal("0.9000"))

    @patch('requests.Session.get')
    def test_get_rate_rub_to_usd(self, mock_get):
        """RUB → USD = 1 / 90 ≈ 0.0111."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_XML
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        rate = self.converter.get_rate("RUB", "USD")
        self.assertEqual(rate, Decimal("0.0111"))

    def test_get_rate_same_currency(self):
        """Если валюты одинаковые — курс 1, и запрос в интернет не нужен."""
        rate = self.converter.get_rate("USD", "USD")
        self.assertEqual(rate, Decimal("1.0"))

    def test_get_rate_invalid_currency(self):
        """Если валюта не поддерживается — должна быть ошибка ValueError."""
        with self.assertRaises(ValueError):
            self.converter.get_rate("GBP", "EUR")

    # ---------- Проверяем кэширование ----------

    @patch('requests.Session.get')
    def test_cache_saved_after_success(self, mock_get):
        """После успешного запроса курсы сохраняются в файл cache.json."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_XML
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        self.converter.get_rate("USD", "EUR")
        # Проверяем: файл кэша появился
        self.assertTrue(os.path.exists(self.converter.CACHE_FILE))

        # И в нём есть курсы USD и EUR
        with open(self.converter.CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        self.assertIn("USD", cache)
        self.assertIn("EUR", cache)

    @patch('requests.Session.get')
    def test_uses_cache_on_network_error(self, mock_get):
        """Если интернет пропал, но есть кэш — программа всё равно работает."""
        # 1. Сначала делаем успешный запрос, чтобы кэш заполнился
        mock_response = MagicMock()
        mock_response.text = SAMPLE_XML
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        self.converter.get_rate("USD", "EUR")

        # 2. Теперь «ломаем» интернет: любой запрос будет падать
        mock_get.side_effect = requests.exceptions.ConnectionError()

        # 3. Просим курс снова — он должен взяться из кэша (0.9)
        rate = self.converter.get_rate("USD", "EUR")
        self.assertEqual(rate, Decimal("0.9000"))

    @patch('requests.Session.get')
    def test_connection_error_no_cache(self, mock_get):
        """Если нет интернета и нет кэша — должна быть ошибка ConnectionError."""
        mock_get.side_effect = requests.exceptions.ConnectionError()

        with self.assertRaises(ConnectionError):
            self.converter.get_rate("USD", "EUR")

    @patch('requests.Session.get')
    def test_timeout_no_cache(self, mock_get):
        """Если сервер не отвечает и нет кэша — ошибка ConnectionError."""
        mock_get.side_effect = requests.exceptions.Timeout()

        with self.assertRaises(ConnectionError):
            self.converter.get_rate("USD", "EUR")

    # ---------- Проверяем convert ----------

    @patch.object(CurrencyConverter, 'get_rate')
    def test_convert_calculation(self, mock_get_rate):
        """Результат = сумма × курс."""
        # Подменяем настоящий get_rate, чтобы не ходить в интернет
        mock_get_rate.return_value = Decimal("0.85")

        result = self.converter.convert(100, "USD", "EUR")
        self.assertEqual(result, Decimal("85.00"))
        # Проверяем, что get_rate вызвали именно с этими валютами
        mock_get_rate.assert_called_once_with("USD", "EUR")

    @patch.object(CurrencyConverter, 'get_rate')
    def test_convert_rounding(self, mock_get_rate):
        """Результат округляется до 2 знаков после запятой."""
        mock_get_rate.return_value = Decimal("0.123456")

        result = self.converter.convert(100, "USD", "EUR")
        # 100 × 0.123456 = 12.3456, после округления = 12.35
        self.assertEqual(result, Decimal("12.35"))

    def test_convert_negative_amount(self):
        """Отрицательную сумму конвертировать нельзя."""
        with self.assertRaises(ValueError):
            self.converter.convert(-50, "USD", "EUR")

    def test_convert_zero_amount(self):
        """Нулевую сумму конвертировать нельзя."""
        with self.assertRaises(ValueError):
            self.converter.convert(0, "USD", "EUR")


# Если запустить файл напрямую — запускаем тесты
if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestCurrencyConverter)
    unittest.TextTestRunner(verbosity=2).run(suite)
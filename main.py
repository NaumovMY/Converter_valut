# Импортируем наш класс из файла converter.py
from converter import CurrencyConverter


def main():
    """Главная функция — запускает программу и общается с пользователем."""
    # Создаём объект конвертера, через него будем делать всю работу
    converter = CurrencyConverter()
    print("=== Конвертер валют (USD / EUR / RUB) ===")
    print("Введите 'exit' для выхода\n")

    # Бесконечный цикл — программа работает, пока пользователь не введёт 'exit'
    while True:
        try:
            # Спрашиваем, из какой валюты переводим
            from_curr = input("Из какой валюты (USD/EUR/RUB): ").strip().upper()
            # Если пользователь хочет выйти — выходим из цикла
            if from_curr == "EXIT":
                print("До свидания!")
                break

            # Спрашиваем, в какую валюту переводим
            to_curr = input("В какую валюту (USD/EUR/RUB): ").strip().upper()
            # Спрашиваем сумму. Заменяем запятую на точку, чтобы можно было писать «10,5»
            amount_str = input("Сумма: ").strip().replace(",", ".")
            # Превращаем строку в число
            amount = float(amount_str)

            # Вызываем конвертацию
            result = converter.convert(amount, from_curr, to_curr)
            print(f"✓ {amount} {from_curr} = {result} {to_curr}\n")

        except ValueError as e:
            # Сюда попадаем, если пользователь ввёл что-то не то
            # (например, буквы вместо числа или неподдерживаемую валюту)
            print(f"✗ Ошибка ввода: {e}\n")
        except ConnectionError as e:
            # Сюда попадаем, если нет интернета и кэша
            print(f"✗ Ошибка сети: {e}\n")
        except Exception as e:
            # Любая другая неожиданная ошибка — программа не должна падать
            print(f"✗ Непредвиденная ошибка: {e}\n")


# Если запустить этот файл напрямую — запустится main()
if __name__ == "__main__":
    main()
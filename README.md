# VK Archive Parser

Скрипт для извлечения вложений из архива сообщений ВКонтакте. Сохраняет структуру чатов и метаданные файлов.

## Возможности

- Извлечение вложений из личных сообщений, групповых чатов и ботов
- Сохранение оригинальной даты создания файлов
- Фильтрация нежелательных ссылок (YouTube, Avito, AliExpress и др.)
- Опциональное скачивание голосовых сообщений
- Опциональное скачивание вложений от ботов
- Автоматическое создание структуры директорий по типам чатов

## Поддерживаемые вложения

- ✅ Фотографии (jpg, jpeg, png, gif)
- ✅ Голосовые сообщения (ogg)
- ❌ Видео
- ❌ Документы

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/yourusername/vk-archive-parser.git
cd vk-archive-parser
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

## Использование

```bash
python src/vk_archive_parser.py /path/to/archive/messages [options]
```

### Опции

- `--download-bots` - скачивать вложения от ботов
- `--download-voice` - скачивать голосовые сообщения

### Примеры

```bash
# Базовое использование (без ботов и голосовых)
python src/vk_archive_parser.py /path/to/archive/messages

# Скачивание вложений от ботов
python src/vk_archive_parser.py /path/to/archive/messages --download-bots

# Скачивание голосовых сообщений
python src/vk_archive_parser.py /path/to/archive/messages --download-voice

# Скачивание всего
python src/vk_archive_parser.py /path/to/archive/messages --download-bots --download-voice
```

## Как получить архив сообщений ВКонтакте

1. Перейдите в настройки ВКонтакте → Общие → Запрос данных
2. Нажмите "Запросить копию данных"
3. Выберите "Сообщения" в списке данных
4. Нажмите "Запросить данные"
5. Дождитесь уведомления о готовности архива
6. Скачайте архив и распакуйте его
7. Укажите путь к распакованному архиву при запуске скрипта

## Структура проекта

```
vk-archive-parser/
├── src/
│   └── vk_archive_parser.py
├── requirements.txt
└── README.md
```

## Лицензия

MIT 
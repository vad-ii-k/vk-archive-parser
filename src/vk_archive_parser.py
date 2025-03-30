#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException
from tqdm import tqdm


class VKArchiveParser:
    def __init__(self, archive_path: str, download_bots: bool = False, download_voice: bool = False):
        """
        Инициализация парсера архива ВКонтакте.
        
        Args:
            archive_path: Путь к директории с архивом
            download_bots: Скачивать ли вложения от ботов
            download_voice: Скачивать ли голосовые сообщения
        """
        self.archive_path = Path(archive_path)
        self.output_path = self.archive_path.parent / "attachments"
        self.output_path.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.max_retries = 3
        self.retry_delay = 5
        self.request_delay = 1
        self.download_bots = download_bots
        self.download_voice = download_voice
        
    def clean_filename(self, filename: str) -> str:
        """
        Очищает имя файла от недопустимых символов.
        
        Args:
            filename: Исходное имя файла
            
        Returns:
            Очищенное имя файла
        """
        cleaned = re.sub(r'[<>:"/\\|?*]', '_', filename)
        cleaned = re.sub(r'_+', '_', cleaned)
        cleaned = cleaned.strip('_')
        return cleaned if cleaned else "unnamed"
        
    def parse_chats(self) -> List[Dict[str, str]]:
        """
        Парсит главный файл архива и возвращает список чатов.
        
        Returns:
            Список словарей с информацией о чатах (имя, путь, тип)
        """
        main_file = self.archive_path / "index-messages.html"
        with open(main_file, "r", encoding="windows-1251") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
            
        chats = []
        for item in soup.select(".item"):
            link = item.select_one(".message-peer--id a")
            if link:
                chat_name = link.text.strip()
                chat_path = link["href"]
                chat_id = re.search(r"(-?\d+)/messages", chat_path)
                if chat_id:
                    chat_id = int(chat_id.group(1))
                    if chat_id > 2000000000:
                        chat_type = "group"
                    elif chat_id < 0:
                        chat_type = "bot"
                    else:
                        chat_type = "personal"
                else:
                    chat_type = "other"
                    
                chats.append({
                    "name": chat_name,
                    "path": chat_path,
                    "type": chat_type
                })
        return chats
    
    def get_chat_pages(self, chat_path: str) -> List[str]:
        """
        Получает список всех страниц чата.
        
        Args:
            chat_path: Путь к первой странице чата
            
        Returns:
            Список путей к страницам чата, отсортированный по номеру
        """
        chat_dir = os.path.dirname(chat_path)
        pages = []
        
        for file in os.listdir(self.archive_path / chat_dir):
            if file.startswith("messages") and file.endswith(".html"):
                pages.append(os.path.join(chat_dir, file))
        
        pages.sort(key=lambda x: int(re.search(r"messages(\d+)\.html", x).group(1)))
        return pages
    
    def parse_attachments(self, chat_path: str) -> List[Dict[str, str]]:
        """
        Парсит страницу чата и извлекает информацию о вложениях.
        
        Args:
            chat_path: Путь к странице чата
            
        Returns:
            Список словарей с информацией о вложениях (URL, тип, дата)
        """
        full_path = self.archive_path / chat_path
        with open(full_path, "r", encoding="windows-1251") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
            
        attachments = []
        for message in soup.select(".message"):
            message_date = message.select_one(".message__header")
            if not message_date:
                continue
                
            date_text = message_date.text.strip()
            date_match = re.search(r"(\d{1,2}\s+[а-я]+\s+\d{4}\s+в\s+\d{1,2}:\d{2}:\d{2})", date_text)
            if not date_match:
                continue
                
            date_str = date_match.group(1)
            months = {
                'янв': '01', 'фев': '02', 'мар': '03', 'апр': '04',
                'май': '05', 'июн': '06', 'июл': '07', 'авг': '08',
                'сен': '09', 'окт': '10', 'ноя': '11', 'дек': '12'
            }
            
            for ru_month, num_month in months.items():
                date_str = date_str.replace(ru_month, num_month)
            
            try:
                message_datetime = datetime.strptime(date_str, "%d %m %Y в %H:%M:%S")
            except ValueError:
                continue
            
            for attachment in message.select(".attachment"):
                link = attachment.select_one(".attachment__link")
                if link:
                    url = link["href"]
                    description = attachment.select_one(".attachment__description").text
                    attachments.append({
                        "url": url,
                        "type": description,
                        "date": message_datetime
                    })
        return attachments
    
    def should_skip_url(self, url: str) -> bool:
        """
        Проверяет, нужно ли пропустить URL.
        
        Args:
            url: URL для проверки
            
        Returns:
            True если URL нужно пропустить, False иначе
        """
        skip_domains = {
            'youtube.com', 'youtu.be',
            'avito.ru',
            'aliexpress.com', 'aliexpress.ru',
            'pastebin.com',
            'coderoad.ru',
            'github.com',
            'play.google.com'
        }
        domain = urlparse(url).netloc.lower()
        
        if not self.download_voice and url.endswith('.ogg'):
            return True
            
        return any(skip_domain in domain for skip_domain in skip_domains)
    
    def download_file(self, url: str, output_path: Path, file_date: datetime) -> bool:
        """
        Скачивает файл по URL с повторными попытками.
        
        Args:
            url: URL файла для скачивания
            output_path: Путь для сохранения файла
            file_date: Дата создания файла
            
        Returns:
            True если файл успешно скачан, False иначе
        """
        for attempt in range(self.max_retries):
            try:
                time.sleep(self.request_delay)
                
                response = self.session.get(url, stream=True, timeout=30)
                response.raise_for_status()
                
                content_length = response.headers.get('content-length')
                if content_length and int(content_length) > 100 * 1024 * 1024:
                    print(f"Warning: File {url} is too large ({content_length} bytes), skipping")
                    return False
                
                with open(output_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                os.utime(output_path, (file_date.timestamp(), file_date.timestamp()))
                return True
                
            except RequestException as e:
                if attempt < self.max_retries - 1:
                    print(f"Attempt {attempt + 1} failed for {url}: {e}")
                    print(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                else:
                    print(f"Failed to download {url} after {self.max_retries} attempts: {e}")
                    return False
            except Exception as e:
                print(f"Unexpected error downloading {url}: {e}")
                return False
    
    def process_chat(self, chat: Dict[str, str]) -> None:
        """
        Обрабатывает один чат: получает все страницы и скачивает вложения.
        
        Args:
            chat: Словарь с информацией о чате
        """
        if chat["type"] == "bot" and not self.download_bots:
            return
            
        pages = self.get_chat_pages(chat["path"])
        
        type_dir = None
        chat_dir = None
        
        for page in tqdm(pages, desc=f"Processing pages for {chat['name']}", leave=False):
            attachments = self.parse_attachments(page)
            for attachment in tqdm(attachments, desc=f"Processing attachments", leave=False):
                url = attachment["url"]
                if self.should_skip_url(url):
                    continue
                    
                filename = os.path.basename(urlparse(url).path)
                
                if not type_dir:
                    type_dir = self.output_path / chat["type"]
                    type_dir.mkdir(exist_ok=True)
                    
                if not chat_dir:
                    chat_dir = type_dir / self.clean_filename(chat["name"])
                    chat_dir.mkdir(exist_ok=True)
                
                output_path = chat_dir / filename
                
                if not output_path.exists():
                    self.download_file(url, output_path, attachment["date"])
    
    def run(self) -> None:
        """
        Запускает процесс парсинга архива.
        Обрабатывает все чаты и скачивает вложения.
        """
        try:
            chats = self.parse_chats()
            for chat in tqdm(chats, desc="Processing chats"):
                self.process_chat(chat)
        except KeyboardInterrupt:
            print("\nProcess interrupted by user")
        except Exception as e:
            print(f"Unexpected error: {e}")
        finally:
            self.session.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="VK Archive Parser")
    parser.add_argument("archive_path", help="Path to the archive directory")
    parser.add_argument("--download-bots", action="store_true", help="Download attachments from bot chats")
    parser.add_argument("--download-voice", action="store_true", help="Download voice messages")
    args = parser.parse_args()
    
    parser = VKArchiveParser(args.archive_path, args.download_bots, args.download_voice)
    parser.run()


if __name__ == "__main__":
    main() 
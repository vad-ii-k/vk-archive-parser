#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from urllib.parse import urlparse
import hashlib

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
        
    def clean_filename(self, filename: str, max_length: int = 60) -> str:
        """
        Очищает имя файла от недопустимых символов и обрезает длинные имена.
        
        Args:
            filename: Исходное имя файла
            max_length: Максимальная длина имени файла
            
        Returns:
            Очищенное имя файла
        """
        name, ext = os.path.splitext(filename)
        name = re.sub(r'[<>:"/\\|?*]', '_', name)
        name = re.sub(r'_+', '_', name).strip('_') or "unnamed"
        
        if len(name) > max_length:
            name = name[:max_length] + f"_{hashlib.md5(name.encode()).hexdigest()[:8]}"
        
        return name + ext
        
    def parse_chats(self) -> List[Dict[str, str]]:
        """
        Парсит главный файл архива и возвращает список чатов.
        
        Returns:
            Список словарей с информацией о чатах (имя, путь, тип)
        """
        with open(self.archive_path / "index-messages.html", "r", encoding="windows-1251") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
            
        chats = []
        for item in soup.select(".item"):
            link = item.select_one(".message-peer--id a")
            if not link:
                continue
                
            chat_name = link.text.strip()
            chat_path = link["href"]
            chat_id = re.search(r"(-?\d+)/messages", chat_path)
            
            if not chat_id:
                chat_type = "other"
            else:
                chat_id = int(chat_id.group(1))
                chat_type = "group" if chat_id > 2000000000 else "bot" if chat_id < 0 else "personal"
                    
            chats.append({"name": chat_name, "path": chat_path, "type": chat_type})
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
        pages = [os.path.join(chat_dir, f) for f in os.listdir(self.archive_path / chat_dir)
                if f.startswith("messages") and f.endswith(".html")]
        return sorted(pages, key=lambda x: int(re.search(r"messages(\d+)\.html", x).group(1)))
    
    def parse_attachments(self, chat_path: str) -> List[Dict[str, str]]:
        """
        Парсит страницу чата и извлекает информацию о вложениях.
        
        Args:
            chat_path: Путь к странице чата
            
        Returns:
            Список словарей с информацией о вложениях (URL, тип, дата)
        """
        with open(self.archive_path / chat_path, "r", encoding="windows-1251") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
            
        months = {
            'янв': '01', 'фев': '02', 'мар': '03', 'апр': '04',
            'май': '05', 'июн': '06', 'июл': '07', 'авг': '08',
            'сен': '09', 'окт': '10', 'ноя': '11', 'дек': '12'
        }
        
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
            for ru_month, num_month in months.items():
                date_str = date_str.replace(ru_month, num_month)
            
            try:
                message_datetime = datetime.strptime(date_str, "%d %m %Y в %H:%M:%S")
            except ValueError:
                continue
            
            for attachment in message.select(".attachment"):
                link = attachment.select_one(".attachment__link")
                if not link:
                    continue
                    
                description = attachment.select_one(".attachment__description")
                attachments.append({
                    "url": link["href"],
                    "type": description.text if description else "",
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
        if not self.download_voice and url.endswith('.ogg'):
            return True
            
        domain = urlparse(url).netloc.lower()
        skip_domains = {
            'youtube.com', 'youtu.be', 'avito.ru', 'aliexpress.com', 'aliexpress.ru',
            'pastebin.com', 'coderoad.ru', 'github.com', 'play.google.com'
        }
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
                
                if int(response.headers.get('content-length', 0)) > 100 * 1024 * 1024:
                    print(f"Warning: File {url} is too large, skipping")
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
        try:
            if chat["type"] == "bot" and not self.download_bots:
                return
                
            pages = self.get_chat_pages(chat["path"])
            type_dir = self.output_path / chat["type"]
            type_dir.mkdir(exist_ok=True)
            
            chat_name = self.clean_filename(chat["name"], max_length=40)
            chat_dir = type_dir / chat_name
            chat_dir.mkdir(exist_ok=True)
            
            for page in tqdm(pages, desc=f"Processing pages for {chat['name']}", leave=False):
                attachments = self.parse_attachments(page)
                for attachment in tqdm(attachments, desc=f"Processing attachments", leave=False):
                    url = attachment["url"]
                    if self.should_skip_url(url):
                        continue
                        
                    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                    filename = os.path.basename(urlparse(url).path)
                    name, ext = os.path.splitext(filename)
                    
                    if not ext:
                        continue
                        
                    output_path = chat_dir / f"{url_hash}{ext}"
                    if not output_path.exists():
                        self.download_file(url, output_path, attachment["date"])
        except Exception as e:
            print(f"Error processing chat {chat['name']}: {e}")
            # Продолжаем работу со следующим чатом
    
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
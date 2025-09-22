import requests
import time
import os
import json
import logging
from urllib.parse import quote
from PIL import Image
import io
import sys
# -*- coding: utf-8 -*-
# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("vk2tg.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Конфигурация
CONFIG = {
    'vk': {
        'token': '',
        'owner_id': "YOURIDGROUP", 
        'api_version': '5.131'
    },
    'telegram': {
        'bot_token': 'YourBotToken',
        'chat_id': '@IDGroup',
        'bot_username': 'idBot'
    },
    'settings': {
        'button_text': 'Button_Text',
        'check_interval': 60,
        'timeout': 30,
        'max_retries': 3,
        'max_images': 10  # Максимальное количество изображений в медиагруппе
    }
}

class VK2TGBot:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'VK2TG/2.0'})
        self.last_post_time = self.load_last_post_time()

    def load_last_post_time(self):
        try:
            with open('last_post_time.txt', 'r') as f:
                return int(f.read())
        except (FileNotFoundError, ValueError):
            return 0

    def save_last_post_time(self, timestamp):
        with open('last_post_time.txt', 'w') as f:
            f.write(str(timestamp))

    def get_vk_posts(self):
        params = {
            'owner_id': CONFIG['vk']['owner_id'],
            'count': 10,
            'access_token': CONFIG['vk']['token'],
            'v': CONFIG['vk']['api_version']
        }

        try:
            response = self.session.get(
                'https://api.vk.com/method/wall.get',
                params=params,
                timeout=CONFIG['settings']['timeout']
            )
            data = response.json()
            return data.get('response', {}).get('items', [])
        except Exception as e:
            logging.error(f"Ошибка получения постов: {str(e)}")
            return []

    def process_post(self, post):
        # Проверяем наличие репоста (copy_history)
        if 'copy_history' in post and post['copy_history']:
            repost = post['copy_history'][0]
            result = {
                'timestamp': post.get('date', 0),
                'text': '',
                'images': [],
                'stats': {
                    'likes': post.get('likes', {}).get('count', 0),
                    'reposts': post.get('reposts', {}).get('count', 0),
                    'views': post.get('views', {}).get('count', 0)
                }
            }
            
            # Обрабатываем текст: основной + репост
            main_text = post.get('text', '')
            repost_text = repost.get('text', '')
            
            if main_text and repost_text:
                result['text'] = f"{main_text}\n\n{repost_text}"
            else:
                result['text'] = main_text or repost_text
                
            # Добавляем гиперссылку на исходный пост
            owner_id = repost.get('owner_id', 0)
            post_id = repost.get('id', 0)
            
            if owner_id and post_id:
                # Формируем правильный URL для группы или пользователя
                if owner_id < 0:
                    group_id = abs(owner_id)
                    source_url = f"https://vk.com/club{group_id}?w=wall{owner_id}_{post_id}"
                else:
                    source_url = f"https://vk.com/id{owner_id}?w=wall{owner_id}_{post_id}"
                
                result['text'] += f"\n\n🔗 <a href='{source_url}'>Источник</a>"
            
            # Обрабатываем вложения репоста
            for att in repost.get('attachments', []):
                if att.get('type') == 'photo':
                    photo = att['photo']
                    largest = max(photo['sizes'], key=lambda s: s['width'] * s['height'])
                    result['images'].append(largest['url'])
                    
            return result
        
        # Обработка обычного поста (не репоста)
        result = {
            'timestamp': post.get('date', 0),
            'text': post.get('text', ''),
            'images': [],
            'stats': {
                'likes': post.get('likes', {}).get('count', 0),
                'reposts': post.get('reposts', {}).get('count', 0),
                'views': post.get('views', {}).get('count', 0)
            }
        }

        for att in post.get('attachments', []):
            if att.get('type') == 'photo':
                photo = att['photo']
                largest = max(photo['sizes'], key=lambda s: s['width'] * s['height'])
                result['images'].append(largest['url'])

        return result

    def download_image(self, url):
        for attempt in range(CONFIG['settings']['max_retries']):
            try:
                response = self.session.get(url, stream=True, timeout=10)
                response.raise_for_status()
                
                # Проверяем что это валидное изображение
                img = Image.open(io.BytesIO(response.content))
                img.verify()
                
                return response.content
            except Exception as e:
                logging.warning(f"Попытка {attempt+1}: Ошибка загрузки изображения - {str(e)}")
                time.sleep(2)
        return None

    def create_keyboard(self):
        return {
            'inline_keyboard': [[{
                'text': CONFIG['settings']['button_text'],
                'url': f'https://t.me/{CONFIG["telegram"]["bot_username"]}'
            }]]
        }

    def send_text_post(self, text):
        url = f'https://api.telegram.org/bot{CONFIG["telegram"]["bot_token"]}/sendMessage'
        
        data = {
            'chat_id': CONFIG['telegram']['chat_id'],
            'text': text,
            'parse_mode': 'HTML',
            'reply_markup': json.dumps(self.create_keyboard())
        }

        try:
            response = self.session.post(url, data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logging.error(f"Ошибка отправки текста: {str(e)}")
            return False

    def send_single_photo(self, caption, photo_url):
        url = f'https://api.telegram.org/bot{CONFIG["telegram"]["bot_token"]}/sendPhoto'
        
        image_data = self.download_image(photo_url)
        if not image_data:
            return False

        data = {
            'chat_id': CONFIG['telegram']['chat_id'],
            'caption': caption,
            'parse_mode': 'HTML',
            'reply_markup': json.dumps(self.create_keyboard())
        }

        try:
            response = self.session.post(
                url,
                data=data,
                files={'photo': ('image.jpg', image_data)},
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            logging.error(f"Ошибка отправки фото: {str(e)}")
            return False

    def send_to_telegram(self, content, images):
        if not images:
            return self.send_text_post(content)
        elif len(images) == 1:
            return self.send_single_photo(content, images[0])
        else:
            return self.send_media_group(content, images)

    def send_media_group(self, caption, image_urls):
        url = f'https://api.telegram.org/bot{CONFIG["telegram"]["bot_token"]}/sendMediaGroup'
        
        media = []
        files = {}
        # Создаем список media без reply_markup
        for idx, img_url in enumerate(image_urls[:CONFIG['settings']['max_images']]):
            image_data = self.download_image(img_url)
            if not image_data:
                continue
                
            media_obj = {
                'type': 'photo',
                'media': f'attach://photo{idx}'
            }

            # Добавляем caption и parse_mode только к первому элементу
            if idx == 0:
                media_obj['caption'] = caption
                media_obj['parse_mode'] = 'HTML'
            
            media.append(media_obj)
            files[f'photo{idx}'] = (f'photo{idx}.jpg', image_data)

        if not media:
            return False

        # Передаем reply_markup отдельно
        reply_markup = json.dumps(self.create_keyboard())

        try:
            response = self.session.post(
                url,
                data={
                    'chat_id': CONFIG['telegram']['chat_id'],
                    'media': json.dumps(media),
                    'reply_markup': reply_markup
                },
                files=files,
                timeout=20
            )
            
            if response.status_code != 200:
                logging.error(f"Ошибка медиагруппы: {response.text}")
            return response.status_code == 200
            
        except Exception as e:
            logging.error(f"Ошибка отправки медиагруппы: {str(e)}")
            return False
    def run(self):
        logging.info("Bot Started")
        while True:
            try:
                posts = self.get_vk_posts()
                new_posts = [p for p in posts if p['date'] > self.last_post_time]
                new_posts.sort(key=lambda x: x['date'])

                for post in new_posts:
                    processed = self.process_post(post)
                    if self.send_to_telegram(processed['text'], processed['images']):
                        self.last_post_time = max(self.last_post_time, processed['timestamp'])
                        self.save_last_post_time(self.last_post_time)

                time.sleep(CONFIG['settings']['check_interval'])
                
            except Exception as e:
                logging.error(f"Ошибка в основном цикле: {str(e)}")
                time.sleep(60)

if __name__ == "__main__":
    bot = VK2TGBot()
    bot.run()
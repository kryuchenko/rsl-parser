#!/usr/bin/env python3
"""
Простой RSL парсер с флагом --all
"""

import asyncio
from pathlib import Path
import argparse
import re
import base64
import hashlib
from datetime import datetime

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Установите playwright: pip install playwright")
    exit(1)

async def save_book_description(page, output_dir):
    """Сохраняет описание книги в простой текстовый файл"""
    try:
        print("📋 Сохранение описания книги...")
        
        # Пробуем кликнуть на кнопку информации
        info_button_xpath = '//*[@id="app"]/div[1]/div[1]/div/ul/li[7]/button'
        try:
            info_button = await page.query_selector(f'xpath={info_button_xpath}')
            if info_button:
                await info_button.click()
                await asyncio.sleep(2)
        except:
            pass
        
        # Извлекаем информацию о книге
        book_info = await page.evaluate('''
            () => {
                const info = {};
                
                // Заголовок книги
                const titleSelectors = ['h1', 'h2', '.title', '[class*="title"]'];
                for (let selector of titleSelectors) {
                    const elem = document.querySelector(selector);
                    if (elem && elem.textContent.trim().length > 10) {
                        let title = elem.textContent.trim();
                        // Убираем "[Текст]" и подобные приписки
                        title = title.replace(/\\s*\\[.*?\\]\\s*$/g, '').trim();
                        info.title = title;
                        break;
                    }
                }
                
                // Автор
                const authorSelectors = ['[class*="author"]', '.creator', '.metadata .author'];
                for (let selector of authorSelectors) {
                    const elem = document.querySelector(selector);
                    if (elem && elem.textContent.trim()) {
                        info.author = elem.textContent.trim();
                        break;
                    }
                }
                
                // Год
                const allText = document.body.innerText || '';
                const yearMatch = allText.match(/\\b(1[89]\\d{2}|20\\d{2})\\b/g);
                if (yearMatch) {
                    info.year = yearMatch[yearMatch.length - 1];
                }
                
                info.url = window.location.href;
                info.date = new Date().toISOString().split('T')[0];
                
                return info;
            }
        ''')
        
        # Создаем простой текстовый файл
        desc_file = Path(output_dir) / 'description.txt'
        with open(desc_file, 'w', encoding='utf-8') as f:
            if book_info.get('title'):
                f.write(f"{book_info['title']}\n\n")
            
            if book_info.get('author'):
                f.write(f"Автор: {book_info['author']}\n")
            
            if book_info.get('year'):
                f.write(f"Год: {book_info['year']}\n")
            
            f.write(f"\nИсточник: {book_info['url']}\n")
            f.write(f"Скачано: {book_info['date']}\n")
        
        print(f"   ✅ Описание сохранено в {desc_file.name}")
        return book_info
        
    except Exception as e:
        print(f"   ❌ Ошибка сохранения описания: {e}")
        return None

async def extract_book_images(book_id, max_pages=50, headless=True):
    """Извлекает изображения из background-image стилей"""
    
    # Папка просто по ID книги
    output_dir = Path(book_id)
    output_dir.mkdir(exist_ok=True)
    
    async with async_playwright() as p:
        print("🚀 Запуск браузера...")
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        
        page = await context.new_page()
        saved_images = 0
        saved_hashes = set()
        consecutive_failures = 0  # Счетчик неудачных попыток подряд
        
        base_url = f"https://viewer.rsl.ru/ru/{book_id}"
        print(f"📖 Открываем книгу: {base_url}")
        
        # Переходим на первую страницу и сохраняем описание
        await page.goto(f"{base_url}?page=1", wait_until='networkidle', timeout=20000)
        await asyncio.sleep(3)
        
        # Сохраняем описание книги
        book_info = await save_book_description(page, output_dir)
        
        # Определяем реальное количество страниц по списку превью
        try:
            # Сначала прокручиваем список превью вниз чтобы загрузились все элементы
            await page.evaluate('''
                () => {
                    const scrollContainer = document.querySelector('.sidebar__scroll-container');
                    if (scrollContainer) {
                        scrollContainer.scrollTop = scrollContainer.scrollHeight;
                    }
                }
            ''')
            await asyncio.sleep(2)  # Ждем загрузки всех превью
            
            total_pages = await page.evaluate('''
                () => {
                    // Ищем список превью страниц
                    const previewItems = document.querySelectorAll('.preview-list__item');
                    if (previewItems && previewItems.length > 0) {
                        console.log('Found preview items:', previewItems.length);
                        return previewItems.length;
                    }
                    
                    // Альтернативный селектор - все li элементы в списке превью
                    const listItems = document.querySelectorAll('.preview-viewer__scroll-container li');
                    if (listItems && listItems.length > 0) {
                        console.log('Found list items:', listItems.length);
                        return listItems.length;
                    }
                    
                    // Еще один вариант
                    const allLi = document.querySelectorAll('.sidebar__container li');
                    if (allLi && allLi.length > 0) {
                        console.log('Found sidebar items:', allLi.length);
                        return allLi.length;
                    }
                    
                    return null;
                }
            ''')
            
            if total_pages:
                print(f"📊 Обнаружено {total_pages} страниц в книге")
                # Корректируем max_pages 
                if max_pages == 500:  # Если режим --all
                    max_pages = total_pages
                    print(f"🎯 Будет скачано все {max_pages} страниц")
                elif total_pages < max_pages:
                    max_pages = total_pages
                    print(f"📎 Скорректировано до {max_pages} страниц (всего в книге)")
            else:
                print("⚠️ Не удалось определить количество страниц")
        except Exception as e:
            print(f"⚠️ Ошибка при определении страниц: {e}")
        
        print(f"\n📥 Извлечение до {max_pages} страниц (остановка при неудачах)...\n")
        
        for page_num in range(1, max_pages + 1):
            print(f"📄 Страница {page_num}...", end=" ")
            
            # Переходим на страницу
            page_url = f"{base_url}?page={page_num}"
            await page.goto(page_url, wait_until='networkidle', timeout=20000)
            await asyncio.sleep(2)
            
            saved = False
            
            try:
                # Ищем элементы с background-image
                background_image_data = await page.evaluate('''
                    () => {
                        const elements = document.querySelectorAll('*');
                        
                        for (let element of elements) {
                            const computedStyle = window.getComputedStyle(element);
                            const bgImage = computedStyle.backgroundImage;
                            
                            if (bgImage && bgImage.includes('data:image/jpeg')) {
                                const match = bgImage.match(/url\\("?(data:image\\/jpeg;base64,[^"]+)"?\\)/);
                                if (match) {
                                    return [{ dataUrl: match[1] }];
                                }
                            }
                        }
                        
                        return [];
                    }
                ''')
                
                if background_image_data and len(background_image_data) > 0:
                    data_url = background_image_data[0]['dataUrl']
                    
                    if data_url and data_url.startswith('data:image/jpeg'):
                        try:
                            img_data = base64.b64decode(data_url.split(',')[1])
                            
                            if len(img_data) > 5000:
                                img_hash = hashlib.md5(img_data).hexdigest()
                                
                                if img_hash not in saved_hashes:
                                    image_path = output_dir / f"page_{page_num:04d}.jpg"
                                    with open(image_path, 'wb') as f:
                                        f.write(img_data)
                                    
                                    saved_hashes.add(img_hash)
                                    saved_images += 1
                                    size_kb = len(img_data) // 1024
                                    print(f"✅ {size_kb}KB")
                                    saved = True
                                    consecutive_failures = 0
                                else:
                                    print("⚠️ дубликат")
                                    consecutive_failures += 1
                            else:
                                print(f"⚠️ мало данных")
                                consecutive_failures += 1
                        except Exception as e:
                            print(f"❌ ошибка: {e}")
                            consecutive_failures += 1
                else:
                    print("❌ не найдено")
                    consecutive_failures += 1
                    
            except Exception as e:
                print(f"❌ ошибка: {e}")
                consecutive_failures += 1
            
            if not saved:
                consecutive_failures += 1
            
            # Если 5 страниц подряд не удалось скачать - прекращаем
            if consecutive_failures >= 5:
                print(f"\n⏹️  Остановка: {consecutive_failures} неудачных попыток подряд")
                break
            
            await asyncio.sleep(0.8)
        
        await browser.close()
        return saved_images, book_info, output_dir

def extract_book_id(url):
    """Извлечь ID книги из URL"""
    match = re.search(r'(rsl\d+)', url)
    return match.group(1) if match else None

async def main():
    parser = argparse.ArgumentParser(description='RSL парсер с умной остановкой')
    parser.add_argument('url', help='URL книги на viewer.rsl.ru')
    parser.add_argument('--pages', type=int, default=20, help='Максимум страниц (по умолчанию 20)')
    parser.add_argument('--all', action='store_true', help='Попытаться скачать все страницы (до 500)')
    parser.add_argument('--show-browser', action='store_true', help='Показать браузер')
    
    args = parser.parse_args()
    
    book_id = extract_book_id(args.url)
    if not book_id:
        print(f"❌ Не удалось извлечь ID книги из URL: {args.url}")
        return
    
    print(f"📚 ID книги: {book_id}")
    
    # Определяем количество страниц
    if args.all:
        max_pages = 500  # Большой лимит для режима --all
        print(f"🔄 Режим: скачать ВСЕ страницы (умная остановка при неудачах)")
    else:
        max_pages = args.pages
        print(f"📊 Максимум страниц: {args.pages}")
    
    print(f"📁 Папка: {book_id}/")
    
    saved_count, book_info, output_dir = await extract_book_images(
        book_id,
        max_pages=max_pages,
        headless=not args.show_browser
    )
    
    if saved_count > 0:
        print(f"\n🎉 ГОТОВО! Сохранено {saved_count} изображений")
        print(f"📁 Папка: {output_dir}/")
        
        # Показываем размер
        files = list(output_dir.glob("*.jpg"))
        if files:
            total_size = sum(f.stat().st_size for f in files)
            total_size_mb = total_size / (1024 * 1024)
            print(f"📊 Размер: {total_size_mb:.1f} MB")
        
        # Показываем информацию о книге
        if book_info and book_info.get('title'):
            print(f"📖 Книга: {book_info['title']}")
            if book_info.get('author'):
                print(f"✍️ Автор: {book_info['author']}")
            print(f"💾 Описание сохранено в description.txt")
    else:
        print("\n❌ Не удалось извлечь изображения")

if __name__ == "__main__":
    asyncio.run(main())
import asyncio
import os
from collections import namedtuple
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import aiohttp
from aiogram import Bot
from aiogram.types.input_file import BufferedInputFile
from aiogram.types.link_preview_options import LinkPreviewOptions
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from PIL import ImageFile

# Load environment variables from .env file if present
load_dotenv()

ImageFile.LOAD_TRUNCATED_IMAGES = True


def _get_post_id(url: str) -> str:
    qs = urlparse(url).query
    if 'p' in qs:
        p = parse_qs(qs)['p'][0]
        return 'post_' + p
    return ''


async def get_threads(session: aiohttp.ClientSession, f: str = '', prefixid: str = '',
                      newset: str = '', page: int = 1, pp: int = 25, daysprune: int = 0) -> list:
    url = (f'https://vipergirls.to/forumdisplay.php?f={f}&prefixid={prefixid}'
           f'&newset={newset}&page={page}&pp={pp}&daysprune={daysprune}')
    async with session.get(url) as response:
        text = await response.text()
    soup = BeautifulSoup(text, 'lxml')
    thread_urls = []
    for u in soup.find_all('a', class_='lastpostdate'):
        href = u.get('href')
        thread_urls.append('https://vipergirls.to/' + href.split('?')[0])
    return thread_urls


async def get_img_urls(session: aiohttp.ClientSession, page: str) -> tuple:
    async with session.get(page) as response:
        text = await response.text()
    soup = BeautifulSoup(text, 'lxml')
    body = soup.find('body')
    post_id = _get_post_id(page)
    if post_id:
        body = soup.find('li', attrs={'id': post_id})
    posts = body.find_all('div', class_='postrow')
    urls = []
    for post in posts:
        post_i = {'vipr': [], 'imx': [], 'pixhost': [], 'acidimg': []}
        for u in post.find_all('img', attrs={'border': '0', 'alt': ''}):
            src = u.get('src')
            if 'vipr' in src:
                post_i['vipr'].append(src.replace('/th/', '/i/'))
            elif 'imx.to/u' in src:
                t_src = src
                if '/t/' not in src:
                    async with session.head(src) as head_resp:
                        t_src = str(head_resp.url)
                post_i['imx'].append(t_src.replace('/t/', '/i/'))
            elif 'pixhost' in src:
                post_i['pixhost'].append(src.replace('thumb', 'image').replace('//t', '//img'))
            elif 'acidimg' in src:
                post_i['acidimg'].append(src.replace('small', 'big'))
        urls.append(post_i)
    # Select the image list with the most entries for each host
    url = {'vipr': [], 'imx': [], 'pixhost': [], 'acidimg': []}
    for i in urls:
        if len(i['vipr']) > len(url['vipr']):
            url['vipr'] = i['vipr']
        if len(i['pixhost']) > len(url['pixhost']):
            url['pixhost'] = i['pixhost']
        if len(i['imx']) > len(url['imx']):
            url['imx'] = i['imx']
        if len(i['acidimg']) > len(url['acidimg']):
            url['acidimg'] = i['acidimg']

    title = soup.find('title').string if soup.find('title') else 'No Title'
    if url['vipr']:
        return title, url['vipr']
    if url['pixhost']:
        return title, url['pixhost']
    if url['acidimg']:
        return title, url['acidimg']
    if url['imx']:
        return title, url['imx']
    return title, []


async def upload_image_to_telegram(bot: Bot, chat_id: str, image_url: str,
                                   semaphore: asyncio.Semaphore,
                                   session: aiohttp.ClientSession) -> str:
    """
    Downloads an image and sends it via the Telegram Bot API using the provided bot.
    Returns the Telegram-hosted image URL.
    """
    async with semaphore:
        try:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    print(f"Failed to download image: {image_url}")
                    return None
                image_bytes = await resp.read()
        except Exception as e:
            print(f"Error downloading image from {image_url}: {e}")
            return None

        try:
            # Prepare the image file using BytesIO
            photo_file = BytesIO(image_bytes)
            photo_file.seek(0)
            buffer_photo_file = BufferedInputFile(photo_file.getvalue(), filename=f"{image_url.split('/')[-1]}.jpg")
            # Send the photo asynchronously using the upload bot
            msg = await bot.send_photo(chat_id, photo=buffer_photo_file)
            # Retrieve file info from the sent photo (choose the largest size)
            file_id = msg.photo[-1].file_id
            file_info = await bot.get_file(file_id)
            file_path = file_info.file_path
            telegram_img_url = f"https://api.telegram.org/file/bot{bot.token}/{file_path}"
            return telegram_img_url
        except Exception as e:
            print(f"Error uploading image to Telegram: {e}")
            return None


def create_telegraph_page_sync(telegraph_token: str, title: str, html_content: str) -> str:
    """
    Synchronously creates a Telegraph page using the telegraph library.
    """
    from telegraph import Telegraph
    telegraph = Telegraph(telegraph_token)
    page = telegraph.create_page(title, html_content=html_content)
    return page['url']


async def create_page(upload_bot: Bot, chat_id: str, title: str, img_urls: list,
                      telegraph_token: str, semaphore: asyncio.Semaphore,
                      session: aiohttp.ClientSession, skip: int = None) -> str:
    """
    Uploads images concurrently (max 10 at a time) using the upload bot,
    then creates a Telegraph page (synchronously, via run_in_executor) that
    contains <img> tags with the Telegram-hosted image URLs.
    Returns the Telegraph page URL.
    """
    tasks = []
    for i, url in enumerate(img_urls):
        if skip is not None and i == skip:
            continue
        tasks.append(upload_image_to_telegram(upload_bot, chat_id, url, semaphore, session))
    results = await asyncio.gather(*tasks)
    telegram_img_urls = [r for r in results if r]
    if telegram_img_urls:
        content = ''.join(f'<img src="{link}" alt="image">\n' for link in telegram_img_urls)
        loop = asyncio.get_running_loop()
        page_url = await loop.run_in_executor(None, create_telegraph_page_sync, telegraph_token, title, content)
        return page_url
    return None


async def process_new_threads(bot: Bot, upload_bot: Bot, chat_id: str, telegraph_token: str,
                              session: aiohttp.ClientSession):
    Site = namedtuple('Site', 'f prefixid')
    sites = (
        Site('304', 'Vixen_com'),
        Site('304', 'Tushy_com'),
        Site('304', 'TushyRaw_com'),
        Site('304', 'Deeper_com'),
        Site('304', 'Blacked_com'),
        Site('304', 'BlackedRaw_com'),
        Site('305', 'Slayed_com')
    )

    sent_threads = []
    if os.path.exists('sent.txt'):
        with open('sent.txt', 'r') as file:
            sent_threads = [line.strip() for line in file.readlines()]

    new_threads = []
    for site in sites:
        threads = await get_threads(session, site.f, site.prefixid, newset='1')
        for thread in threads:
            if thread not in sent_threads:
                new_threads.append(thread)

    semaphore = asyncio.Semaphore(1)  # Limit to 10 concurrent image uploads

    if new_threads:
        print('Found new threads!')
        for thread in reversed(new_threads):
            title, img_urls = await get_img_urls(session, thread)
            if img_urls:
                page_url = await create_page(upload_bot, chat_id, title, img_urls,
                                             telegraph_token, semaphore, session)
                if page_url:
                    # Send the Telegraph page link via the messaging bot
                    await bot.send_message(chat_id, page_url.replace('telegra.ph/','te.legra.ph/'), link_preview_options=LinkPreviewOptions(is_disabled=False))
                    # safe_title = ''.join(ch for ch in title if ch.isalnum() or ch.isspace())
                    # try:
                    #     await bot.send_message(chat_id,
                    #                            f'[{safe_title}]\({thread}\)',
                    #                            parse_mode='MarkdownV2',
                    #                            disable_web_page_preview=True)
                    # except Exception as e:
                    #     print(f"Error sending thread link: {e}")
            with open('sent.txt', 'a') as file:
                file.write(thread + '\n')
    else:
        print('No new threads found. Closing App')


async def process_message_updates(bot: Bot, upload_bot: Bot, chat_id: str, telegraph_token: str,
                                  session: aiohttp.ClientSession):
    try:
        with open('offset.txt', 'r') as f:
            offset = int(f.readline().strip())
    except (FileNotFoundError, ValueError):
        offset = 0

    updates = await bot.get_updates(offset=offset)
    if updates:
        with open('offset.txt', 'w') as f:
            f.write(str(updates[-1].update_id))
    new_msg_threads = []
    for update in updates[1:]:
        if not update.message:
            continue
        if update.message.chat.id != int(chat_id):
            continue
        if not update.message.text:
            continue
        parts = update.message.text.split(' ')
        try:
            msg_text = parts[0]
            skip = int(parts[1]) if len(parts) == 2 else None
            parsed = urlparse(msg_text)
            if parsed.scheme and parsed.netloc:
                new_msg_threads.append((msg_text, skip))
        except Exception as e:
            print(f"Error processing message text: {e}")

    if new_msg_threads:
        semaphore = asyncio.Semaphore(1)
        print('Found new message threads!')
        for thread, skip in new_msg_threads:
            title, img_urls = await get_img_urls(session, thread)
            if img_urls:
                page_url = await create_page(upload_bot, chat_id, title, img_urls,
                                             telegraph_token, semaphore, session, skip=skip)
                if page_url:
                    await bot.send_message(chat_id, page_url.replace('telegra.ph/','te.legra.ph/'), link_preview_options=LinkPreviewOptions(is_disabled=False))


async def main():
    chat_id = os.environ['CHAT_ID']
    # Bot for sending messages (using TELEGRAM_API_KEY)
    telegram_api_key = os.environ['TELEGRAM_API_KEY']
    # Bot for uploading images (using TELEGRAM_API_KEY_2)
    telegram_api_key_2 = os.environ['TELEGRAM_API_KEY_2']
    telegraph_token = os.environ['TELEGRAPH_TOKEN']

    bot = Bot(token=telegram_api_key)
    upload_bot = Bot(token=telegram_api_key_2)

    async with aiohttp.ClientSession() as session:
        await process_new_threads(bot, upload_bot, chat_id, telegraph_token, session)
        await process_message_updates(bot, upload_bot, chat_id, telegraph_token, session)
    await bot.session.close()
    await upload_bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())

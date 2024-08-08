import bs4, requests, telebot,os
from collections import namedtuple
from telegraph import Telegraph
from io import BytesIO
from PIL import Image
from urllib.parse import urlparse, parse_qs

def _get_post_id(url):
    qs = urlparse(url).query
    if 'p' in qs:
        p = parse_qs(qs)['p'][0]
        return 'post_'+p
    else:
        return ''

def get_threads(f='',prefixid='',newset='',page=1,pp=25,daysprune=0):
    thread_urls = []
    url = f'https://vipergirls.to/forumdisplay.php?f={f}&prefixid={prefixid}&newset={newset}&page={page}&pp={pp}&daysprune={daysprune}'
    sitedata = requests.get(url).text
    soup = bs4.BeautifulSoup(sitedata,'lxml')
    for u in soup.find_all('a',class_='lastpostdate'):
        href = u.get('href')
        thread_urls.append('https://vipergirls.to/'+href[:href.index('?')])
    return thread_urls

def get_img_urls(page):
    pagedata = requests.get(page).text
    soup = bs4.BeautifulSoup(pagedata,'lxml')
    
    body = soup.find('body')
    post_id = _get_post_id(page)
    if post_id:
        body = soup.find('li',attrs={'id':post_id})
    
    posts = body.find_all('div',attrs={'class':'postrow'})
    urls=[]
    for post in posts:
        post_i = {'vipr':[],'imx':[],'pixhost':[],'acidimg':[]}
        for u in post.find_all('img',attrs={'border':'0','alt':''}):
            src = u.get('src')
            if 'vipr' in src:
                post_i['vipr'].append(src.replace('/th/','/i/'))
            elif 'imx.to/u' in src:
                t_src = src
                if '/t/' not in src:
                    tmp_r = requests.head(src)
                    t_src = tmp_r.next.url
                post_i['imx'].append(t_src.replace('/t/','/i/'))
            elif 'pixhost' in src:
                post_i['pixhost'].append(src.replace('thumb','image').replace('//t','//img'))
            elif 'acidimg' in src:
                post_i['acidimg'].append(src.replace('small','big'))
        urls.append(post_i)
    url = {'vipr':[],'imx':[],'pixhost':[],'acidimg':[]}
    for i in urls:
        if len(i['vipr']) > len(url['vipr']):
            url['vipr'] = i['vipr']
        if len(i['pixhost']) > len(url['pixhost']):
            url['pixhost'] = i['pixhost']
        if len(i['imx']) > len(url['imx']):
            url['imx'] = i['imx']
        if len(i['acidimg']) > len(url['acidimg']):
            url['acidimg'] = i['acidimg']
    print(url)
    if url['vipr'] != []:
        return soup.find('title').string,url['vipr']
    if url['pixhost'] != []:
        return soup.find('title').string,url['pixhost']
    if url['acidimg'] != []:
        return soup.find('title').string,url['acidimg']
    if url['imx'] != []:
        return soup.find('title').string,url['imx']

def download_all_imgs(img_urls):
    for i,url in enumerate(img_urls):
        img_data = requests.get(url)
        if img_data.ok:
            with open(f'{i:03}.jpg','wb+') as img_file:
                img_file.write(img_data.content)
        
def create_page(auth_token,title,img_urls,skip=None):
    tg = Telegraph(auth_token)
    tg_img_urls = []
    for i,url in enumerate(img_urls):
        if i == skip:
            continue
        img = Image.open(BytesIO(requests.get(url).content))
        img.save('temp.jpg','jpeg',quality=95)
        temp_jpg = ''
        with open('temp.jpg','rb') as f:
            try:
                req = requests.post('https://telegra.ph/upload',files={'select-file':f})
                tg_img_urls.append((req.json()[0]['src'],url))
            except Exception as e:
                print(e)
        os.remove('temp.jpg')
    if tg_img_urls:
        content = ''.join([f'<img src=\"{x}\" alt=\"{y}\">\n' for x,y in tg_img_urls])
        tgraph_page = tg.create_page(title,html_content=content)
        return tgraph_page['url']
    else:
        return None


if __name__ == '__main__':
    auth_token = os.environ['TELEGRAPH_TOKEN']
    chat_id = os.environ['CHAT_ID']
    api_key = os.environ['TELEGRAM_API_KEY']
    print(auth_token)

    Site = namedtuple('Site','f,prefixid')
    sites = (Site('304','Vixen_com'),Site('304','Tushy_com'),Site('304','TushyRaw_com'),Site('304','Deeper_com'),Site('304','Blacked_com'),Site('304','BlackedRaw_com'),Site('305','Slayed_com'))

    bot = telebot.TeleBot(api_key)

    sent_threads = []
    with open('sent.txt','r') as file:
        sent_threads = [i[:-1] for i in file.readlines()]
    new_threads = []
    for site in sites:
        threads = get_threads(site.f,site.prefixid,newset=1)
        for i in threads:
            if i not in sent_threads:
                new_threads.append(i)

    if new_threads:
        print('Found new threads!.\n',*[f'\t- {i}\n' for i in new_threads])
        for thread in new_threads[::-1]:
            title, img_urls = get_img_urls(thread)
            if img_urls:
                link = create_page(auth_token,title,img_urls)
                bot.send_message(chat_id,str(link.replace('telegra.ph/','te.legra.ph/')))
                t = ''.join([i for i in title if i.isalnum() or i.isspace()])
                try:
                    bot.send_message(chat_id,f'[{t}]({thread})',parse_mode='MarkdownV2',disable_web_page_preview=True)
                except Exception as e:
                    print(e)
                with open('sent.txt','a') as file:
                    file.writelines(thread+'\n')
    else:
        print('No new threads found. Closing App')
        
    new_msg_threads = []
    offset = 0
    with open('offset.txt','r') as f:
        offset = int(f.readline())
    msg_updates = bot.get_updates(offset=offset)

    if msg_updates:
        with open('offset.txt','w') as f:
            f.write(str(msg_updates[-1].update_id))
    
    for msg in msg_updates[1:]:
        if msg.message == None:
            continue
        if msg.message.chat.id != int(chat_id):
            continue
        if msg.message.text == None:
            continue
        s = msg.message.text.split(' ')
        try:
            msg_text = s[0]
            if len(s) == 2:
                skip = int(s[1])
            else:
                skip = None
            parsed = urlparse(msg_text)
            if parsed.scheme and parsed.netloc:
                new_msg_threads.append((msg_text, skip))
        except Exception as e:
            print(e)
    
    if new_msg_threads:
        print('Found new messages!.\n',*[f'\t- {i}\n' for i in new_msg_threads])
        for thread, skip in new_msg_threads:
            title, img_urls = get_img_urls(thread)
            if img_urls:
                link = create_page(auth_token,title,img_urls,skip=skip)
                bot.send_message(chat_id,str(link.replace('telegra.ph/','te.legra.ph/')))

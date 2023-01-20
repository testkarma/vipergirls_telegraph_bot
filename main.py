import bs4, requests, telebot,os
from collections import namedtuple
from telegraph import Telegraph
from io import BytesIO
from PIL import Image

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
    posts = soup.find_all('div',attrs={'class':'postrow'})
    urls=[]
    for post in posts:
        post_i = {'vipr':[],'imx':[]}
        for u in post.find_all('img',attrs={'border':'0','alt':''}):
            if 'vipr' in u.get('src'):
                post_i['vipr'].append(u.get('src').replace('/th/','/i/'))
            elif 'imx' in u.get('src'):
                post_i['imx'].append(u.get('src').replace('/t/','/i/'))
        urls.append(post_i)
    url = {'vipr':[],'imx':[]}
    for i in urls:
        if len(i['vipr']) > len(url['vipr']):
            url['vipr'] = i['vipr']
        if len(i['imx']) > len(url['imx']):
            url['imx'] = i['imx']
    if url['vipr'] == []:
        return soup.find('title').string,url['imx']
    else:
        return soup.find('title').string,url['vipr']

def download_all_imgs(img_urls):
    for i,url in enumerate(img_urls):
        img_data = requests.get(url)
        if img_data.ok:
            with open(f'{i:03}.jpg','wb+') as img_file:
                img_file.write(img_data.content)
        
def create_page(auth_token,title,img_urls):
    tg = Telegraph(auth_token)
    tg_img_urls = []
    for i,url in enumerate(img_urls):
        img = Image.open(BytesIO(requests.get(url).content))
        img.save('temp.jpg','jpeg',quality=95)
        tg_img_urls.append((tg.upload_file('temp.jpg')[0]['src'],url))
        os.remove('temp.jpg')
    content = ''.join([f'<img src=\"{x}\" alt=\"{y}\">\n' for x,y in tg_img_urls])
    tgraph_page = tg.create_page(title,html_content=content)
    return tgraph_page['url']

Site = namedtuple('Site','f,prefixid')
sites = (Site('304','Vixen_com'),Site('304','Tushy_com'),Site('304','TushyRaw_com'),Site('304','Deeper_com'),Site('304','Blacked_com'),Site('304','BlackedRaw_com'),Site('305','Slayed_com'))

auth_token = os.environ['TELEGRAPH_TOKEN']
chat_id = os.environ['CHAT_ID']
api_key = os.environ['TELEGRAM_API_KEY']

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
    bot = telebot.TeleBot(api_key)
    for thread in new_threads[::-1]:
        title, img_urls = get_img_urls(thread)
        if img_urls:
            link = create_page(auth_token,title,img_urls)
            bot.send_message(chat_id,link)
            t = ''.join([i for i in title if i.isalnum() or i.isspace()])
            bot.send_message(chat_id,f'[{t}]({thread})',parse_mode='MarkdownV2',disable_web_page_preview=True)
            with open('sent.txt','a') as file:
                file.writelines(thread+'\n')
else:
    print('No new threads found. Closing App')

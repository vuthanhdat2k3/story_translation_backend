import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup

START = 1478
END = 1499

URL1 = "https://www.novel543.com/1215500675/8096_{}.html"
URL2 = "https://www.novel543.com/1215500675/8096_{}_2.html"

os.makedirs("chapters", exist_ok=True)

options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")
options.add_argument("--disable-blink-features=AutomationControlled")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


def get_text(url):

    driver.get(url)

    time.sleep(5)

    html = driver.page_source

    soup = BeautifulSoup(html, "html.parser")

    content = soup.select_one(".chapter-content .content")

    if not content:
        print("Không thấy content:", url)
        return ""

    paragraphs = content.find_all("p")

    text = "\n".join(p.get_text(strip=True) for p in paragraphs)

    return text


for chap in range(START, END + 1):

    print("Crawling chapter", chap)

    text1 = get_text(URL1.format(chap))
    text2 = get_text(URL2.format(chap))

    full_text = text1 + "\n" + text2

    with open(f"chapters/chapter_{chap}.txt", "w", encoding="utf-8") as f:
        f.write(full_text)

    time.sleep(3)


driver.quit()

print("Done!")
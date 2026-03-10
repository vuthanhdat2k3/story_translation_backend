import os
import re
import time
from contextlib import suppress

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from app.db.database import SessionLocal
from app.models.chapter import Chapter
from app.models.novel import Novel
from app.services.translation_pipeline import translate_chapter

NOVEL_ID = 5
NOVEL_URL = "https://www.novel543.com/1215500675"
CHAPTER_URL_1 = "https://www.novel543.com/1215500675/8096_{}.html"
CHAPTER_URL_2 = "https://www.novel543.com/1215500675/8096_{}_2.html"
CHAPTERS_DIR = "chapters"

os.makedirs(CHAPTERS_DIR, exist_ok=True)


def build_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


def get_latest_chapter_number(driver: webdriver.Chrome) -> int | None:
    """Detect latest chapter number by scanning chapter links on the novel page."""
    driver.get(NOVEL_URL)
    time.sleep(5)

    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")
    hrefs = [a.get("href", "") for a in soup.select("a[href]")]

    numbers = []
    pattern = re.compile(r"/8096_(\d+)(?:_2)?\.html$")
    for href in hrefs:
        match = pattern.search(href)
        if match:
            numbers.append(int(match.group(1)))

    if not numbers:
        return None

    return max(numbers)


def get_chapter_text_and_title(driver: webdriver.Chrome, url: str) -> tuple[str, str | None]:
    """Get chapter text and an optional title from a chapter URL."""
    driver.get(url)
    time.sleep(4)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    content = soup.select_one(".chapter-content .content")

    if not content:
        print("Khong thay content:", url)
        return "", None

    paragraphs = content.find_all("p")
    text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

    title = None
    with suppress(Exception):
        title_tag = soup.select_one("h1")
        if title_tag:
            title = title_tag.get_text(strip=True)

    return text, title


def crawl_chapter(driver: webdriver.Chrome, chapter_number: int) -> tuple[str, str]:
    """Crawl both part 1 and part 2 (if exists) for a chapter."""
    text1, title = get_chapter_text_and_title(driver, CHAPTER_URL_1.format(chapter_number))
    text2, _ = get_chapter_text_and_title(driver, CHAPTER_URL_2.format(chapter_number))

    full_text = "\n".join([part for part in [text1, text2] if part]).strip()
    safe_title = title or f"Chuong {chapter_number}"
    return full_text, safe_title


def save_chapter_file(chapter_number: int, text: str) -> str:
    file_path = os.path.join(CHAPTERS_DIR, f"chapter_{chapter_number}.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)
    return file_path


def upsert_and_translate_chapter(novel_id: int, chapter_number: int, title: str, content_cn: str) -> int:
    """Insert/update chapter in DB and translate it immediately."""
    db = SessionLocal()
    try:
        novel = db.query(Novel).filter(Novel.id == novel_id).first()
        if not novel:
            raise ValueError(f"Novel ID {novel_id} khong ton tai trong DB")

        chapter = (
            db.query(Chapter)
            .filter(Chapter.novel_id == novel_id, Chapter.chapter_number == chapter_number)
            .first()
        )

        if chapter:
            chapter.title = title
            chapter.content_cn = content_cn
            chapter.content_vi = None
            print(f"Da cap nhat chapter #{chapter_number} (id={chapter.id})")
        else:
            chapter = Chapter(
                novel_id=novel_id,
                chapter_number=chapter_number,
                title=title,
                content_cn=content_cn,
            )
            db.add(chapter)
            db.flush()
            print(f"Da them chapter moi #{chapter_number} (id={chapter.id})")

            if chapter_number > novel.total_chapters:
                novel.total_chapters = chapter_number

        db.commit()
        chapter_id = chapter.id

        print(f"Bat dau dich chapter id={chapter_id} ...")
        translate_chapter(db, chapter_id)
        print("Dich chapter xong")

        return chapter_id
    finally:
        db.close()


def main() -> None:
    driver = build_driver()
    try:
        latest = get_latest_chapter_number(driver)
        if latest is None:
            raise RuntimeError("Khong detect duoc chapter moi nhat tu trang web")

        print(f"Chapter moi nhat detect duoc: {latest}")
        full_text, title = crawl_chapter(driver, latest)
        if not full_text:
            raise RuntimeError(f"Khong crawl duoc noi dung chapter {latest}")

        file_path = save_chapter_file(latest, full_text)
        print(f"Da luu chapter vao file: {file_path}")

        chapter_id = upsert_and_translate_chapter(
            novel_id=NOVEL_ID,
            chapter_number=latest,
            title=title,
            content_cn=full_text,
        )

        print(f"Hoan tat: chapter {latest} (id={chapter_id}) da duoc crawl + dich")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
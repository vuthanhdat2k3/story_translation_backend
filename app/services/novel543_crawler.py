"""Crawler service for fetching the latest chapter from novel543."""

import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from sqlalchemy import text

from app.models.chapter import Chapter
from app.models.novel import Novel

DEFAULT_NOVEL543_URL = "https://www.novel543.com/1215500675"
DEFAULT_CHAPTER_PREFIX = "8096"
REQUEST_TIMEOUT = 20
SELENIUM_WAIT_SECONDS = 5
SELENIUM_BOT_BYPASS_TIMEOUT = 120

_CF_COOKIE_CACHE: dict[str, float | str] = {
    "cookie": "",
    "expires_at": 0.0,
}
COOKIE_CACHE_TTL_SECONDS = 60 * 60 * 2


@dataclass
class CrawlLatestResult:
    chapter_id: int
    chapter_number: int
    title: str
    created: bool


def _request_headers(cookie_header: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


def _get_html(url: str, cookie_header: str | None = None, session: requests.Session | None = None) -> str:
    client = session or requests
    response = client.get(
        url,
        headers=_request_headers(cookie_header=cookie_header),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    if response.encoding is None:
        response.encoding = response.apparent_encoding
    return response.text


def _build_driver() -> Any:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as e:
        raise RuntimeError(
            "Selenium fallback chua san sang. Cai them: selenium, webdriver-manager"
        ) from e

    options = webdriver.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")

    if os.environ.get("RENDER") or os.environ.get("HEADLESS_CHROME"):
        # Server / cloud environment (Render, Docker, etc.)
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.binary_location = "/usr/bin/google-chrome"
    else:
        # Local development – open visible browser window
        options.add_argument("--start-maximized")

    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


def _is_antibot_page(html: str) -> bool:
    lower = html.lower()
    return (
        "attention required" in lower
        or "cf-browser-verification" in lower
        or "just a moment" in lower
        or "captcha" in lower
    )


def _get_html_selenium_with_bypass(driver: Any, url: str) -> str:
    """Open URL with Selenium and wait for Cloudflare challenge to clear."""
    try:
        driver.get(url)
    except Exception as e:
        raise ValueError(f"Selenium khong mo duoc trang: {url}. Chi tiet: {e}") from e
    time.sleep(SELENIUM_WAIT_SECONDS)

    html = driver.page_source or ""
    if html and not _is_antibot_page(html):
        return html

    deadline = time.time() + SELENIUM_BOT_BYPASS_TIMEOUT
    while time.time() < deadline:
        time.sleep(2)
        try:
            html = driver.page_source or ""
        except Exception as e:
            raise ValueError(
                "Trinh duyet Selenium bi dong/mat ket noi. Vui long thu lai crawl."
            ) from e
        if html and not _is_antibot_page(html):
            return html

    raise ValueError(
        "Bi chan boi Cloudflare. Hay xac minh captcha trong cua so Chrome, roi bam lai."
    )


def _cookie_header_from_driver(driver: Any) -> str | None:
    try:
        cookies = driver.get_cookies()
    except Exception:
        return None

    if not cookies:
        return None

    pairs = []
    for ck in cookies:
        name = ck.get("name")
        value = ck.get("value")
        if name and value is not None:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs) if pairs else None


def _session_from_cookie(cookie_header: str | None) -> requests.Session:
    session = requests.Session()
    if not cookie_header:
        return session

    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        session.cookies.set(name.strip(), value.strip())
    return session


def _get_cached_cookie() -> str | None:
    now = time.time()
    cookie = str(_CF_COOKIE_CACHE.get("cookie") or "").strip()
    expires_at = float(_CF_COOKIE_CACHE.get("expires_at") or 0.0)
    if cookie and now < expires_at:
        return cookie
    return None


def _set_cached_cookie(cookie_header: str | None) -> None:
    if not cookie_header:
        return
    _CF_COOKIE_CACHE["cookie"] = cookie_header
    _CF_COOKIE_CACHE["expires_at"] = time.time() + COOKIE_CACHE_TTL_SECONDS


def _extract_chapter_text(html: str) -> tuple[str, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".chapter-content .content")
    if not content:
        return "", None

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else None

    paragraphs = content.find_all("p")
    text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)).strip()
    return text, title


def _chapter_exists(
    novel_url: str,
    prefix: str,
    chapter_number: int,
    driver: Any,
) -> bool:
    if chapter_number < 1:
        return False

    url = f"{novel_url}/{prefix}_{chapter_number}.html"
    try:
        html = _get_html_selenium_with_bypass(driver, url)
    except Exception:
        return False

    text, _ = _extract_chapter_text(html)
    return bool(text.strip())


def _detect_latest_by_probing(
    novel_url: str,
    prefix: str,
    start_hint: int,
    driver: Any,
) -> int:
    current = max(1, start_hint)

    if _chapter_exists(novel_url, prefix, current, driver):
        high = current
        step = 1
        while _chapter_exists(novel_url, prefix, high + step, driver):
            high += step
            step *= 2

        left = high
        right = high + step
        while left + 1 < right:
            mid = (left + right) // 2
            if _chapter_exists(novel_url, prefix, mid, driver):
                left = mid
            else:
                right = mid
        return left

    low = 1
    high = current
    best = 0
    while low <= high:
        mid = (low + high) // 2
        if _chapter_exists(novel_url, prefix, mid, driver):
            best = mid
            low = mid + 1
        else:
            high = mid - 1

    if best == 0:
        raise ValueError("Khong detect duoc chapter tu trang novel543")
    return best


def _parse_latest_from_html(html: str) -> tuple[str, int] | None:
    soup = BeautifulSoup(html, "html.parser")
    hrefs = [a.get("href", "") for a in soup.select("a[href]")]
    pattern = re.compile(r"/(\d+)/(\d+)_(\d+)(?:_2)?\.html$")

    candidates: list[tuple[str, int]] = []
    for href in hrefs:
        match = pattern.search(href)
        if not match:
            continue
        candidates.append((match.group(2), int(match.group(3))))

    if not candidates:
        return None

    return max(candidates, key=lambda item: item[1])


def _detect_prefix_and_latest(
    novel_url: str,
    start_hint: int,
    driver: Any,
) -> tuple[str, int]:
    # Open novel page in Selenium (same browser session, no new challenge).
    page_html = _get_html_selenium_with_bypass(driver, novel_url)
    parsed = _parse_latest_from_html(page_html)
    if parsed:
        return parsed

    latest = _detect_latest_by_probing(
        novel_url=novel_url,
        prefix=DEFAULT_CHAPTER_PREFIX,
        start_hint=start_hint,
        driver=driver,
    )
    return DEFAULT_CHAPTER_PREFIX, latest


def _crawl_full_chapter(
    novel_url: str,
    prefix: str,
    chapter_number: int,
    driver: Any,
) -> tuple[str, str]:
    part1_url = f"{novel_url}/{prefix}_{chapter_number}.html"
    part2_url = f"{novel_url}/{prefix}_{chapter_number}_2.html"

    html1 = _get_html_selenium_with_bypass(driver, part1_url)
    text1, title = _extract_chapter_text(html1)

    text2 = ""
    try:
        html2 = _get_html_selenium_with_bypass(driver, part2_url)
        text2, _ = _extract_chapter_text(html2)
    except Exception:
        text2 = ""

    full_text = "\n".join(chunk for chunk in [text1, text2] if chunk).strip()
    if not full_text:
        raise ValueError(f"Khong crawl duoc noi dung chapter {chapter_number}")

    return full_text, (title or f"Chuong {chapter_number}")


def _upsert_chapter(
    db: Session,
    novel_id: int,
    chapter_number: int,
    title: str,
    content_cn: str,
) -> tuple[Chapter, bool]:
    """Insert or update a chapter row, auto-fixing sequence conflicts."""
    chapter = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id, Chapter.chapter_number == chapter_number)
        .first()
    )
    if chapter:
        chapter.title = title
        chapter.content_cn = content_cn
        chapter.content_vi = None
        return chapter, False

    # Reset the id sequence before inserting to avoid duplicate key errors
    db.execute(
        text("SELECT setval('chapters_id_seq', COALESCE((SELECT MAX(id) FROM chapters), 0))")
    )
    chapter = Chapter(
        novel_id=novel_id,
        chapter_number=chapter_number,
        title=title,
        content_cn=content_cn,
    )
    db.add(chapter)
    return chapter, True


def crawl_latest_chapter_to_db(
    db: Session,
    novel_id: int,
    source_url: str = DEFAULT_NOVEL543_URL,
    cookie_header: str | None = None,
) -> CrawlLatestResult:
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise ValueError(f"Novel {novel_id} khong ton tai")

    last_error: Exception | None = None
    content_cn = ""
    title = ""
    latest = 0

    # Use Selenium for everything, just like the old working crawl script.
    # Retry once for flaky webdriver sessions.
    for _ in range(2):
        driver = _build_driver()
        try:
            prefix, latest = _detect_prefix_and_latest(
                source_url,
                start_hint=max(1, novel.total_chapters),
                driver=driver,
            )
            content_cn, title = _crawl_full_chapter(
                source_url,
                prefix,
                latest,
                driver,
            )
            last_error = None
            break
        except Exception as e:
            last_error = e
        finally:
            driver.quit()

    if last_error is not None:
        raise ValueError(str(last_error))

    chapter, created = _upsert_chapter(db, novel_id, latest, title, content_cn)

    if latest > novel.total_chapters:
        novel.total_chapters = latest

    db.commit()
    db.refresh(chapter)

    return CrawlLatestResult(
        chapter_id=chapter.id,
        chapter_number=chapter.chapter_number,
        title=chapter.title,
        created=created,
    )


def crawl_specific_chapter_to_db(
    db: Session,
    novel_id: int,
    chapter_number: int,
    source_url: str = DEFAULT_NOVEL543_URL,
    prefix: str = DEFAULT_CHAPTER_PREFIX,
) -> CrawlLatestResult:
    """Crawl a specific chapter number and upsert into DB."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise ValueError(f"Novel {novel_id} khong ton tai")

    last_error: Exception | None = None
    content_cn = ""
    title = ""

    for _ in range(2):
        driver = _build_driver()
        try:
            content_cn, title = _crawl_full_chapter(
                source_url, prefix, chapter_number, driver,
            )
            last_error = None
            break
        except Exception as e:
            last_error = e
        finally:
            driver.quit()

    if last_error is not None:
        raise ValueError(str(last_error))

    chapter, created = _upsert_chapter(db, novel_id, chapter_number, title, content_cn)

    if chapter_number > novel.total_chapters:
        novel.total_chapters = chapter_number

    db.commit()
    db.refresh(chapter)

    return CrawlLatestResult(
        chapter_id=chapter.id,
        chapter_number=chapter.chapter_number,
        title=chapter.title,
        created=created,
    )

import os
import time
import re
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
# --- 설정 ---
BASE_URL = "https://docs.nhncloud.com"
START_URL = "https://docs.nhncloud.com/ko/quickstarts/ko/overview/"
SAVE_DIR = "nhn_cloud_docs"

# 도커 환경을 위한 셀레니움 옵션
chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--disable-gpu')

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

def clean_name(text):
    """폴더나 파일명으로 쓸 수 없는 문자 제거 및 대소문자 통일(선택)"""
    # 대소문자 구분 없이 처리하고 싶다면 text.lower() 사용 가능
    # 여기서는 폴더명 가독성을 위해 양끝 공백만 제거하고 특수문자만 치환합니다.
    return re.sub(r'[\\/*?:"<>|]', "_", text.strip())

def save_content(url, category_name, sub_menu_name):
    driver.get(url)
    time.sleep(2)  # 페이지 렌더링 대기
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')

    content = soup.find('section', class_='page__content-wrapper')

    if content:
        # 폴더 생성: SAVE_DIR / 카테고리 / 하위메뉴
        folder_path = os.path.join(SAVE_DIR, clean_name(category_name))
        os.makedirs(folder_path, exist_ok=True)
        
        file_name = f"{clean_name(sub_menu_name)}.html"
        full_path = os.path.join(folder_path, file_name)
        
        with open(full_path, 'w', encoding='utf-8') as f:
            # HTML 본문 저장
            f.write(content.prettify())
        print(f"저장 성공: {full_path}")

def start_crawl():
    driver.get(START_URL)

    # 1. 페이지 로딩
    WebDriverWait(driver, 10).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )

    # 2. JS 렌더링 완료까지 대기 (핵심)
    WebDriverWait(driver, 20).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, "li.gnb_menu")) > 0
    )

    categories = driver.find_elements(By.CSS_SELECTOR, '#gnb > li.gnb_menu')
    count = len(categories)

    print("메뉴 로딩 완료")
    tasks = []

    for i in range(count):
        categories = driver.find_elements(By.CSS_SELECTOR, '#gnb > li.gnb_menu')
        cat = categories[i]

        try:
            cat_link = cat.find_element(By.CSS_SELECTOR, 'a.category_menu')
            category_name = cat_link.text.strip()
            category_url = cat_link.get_attribute('href')

            print(f"\n[{category_name}]")

            # 🔥 1. 일단 클릭 (submenu 열기)
            driver.execute_script("arguments[0].click();", cat_link)
            time.sleep(1)

            # 🔥 2. DOM 다시 잡기
            categories = driver.find_elements(By.CSS_SELECTOR, '#gnb > li.gnb_menu')
            cat = categories[i]

            # 🔥🔥 핵심: 모든 하위 a 가져오기 (depth 무시)
            all_links = cat.find_elements(By.CSS_SELECTOR, 'ul.lst_sub_menu a.link_txt')

            valid_links = []

            for link in all_links:
                url = link.get_attribute('href')

                # 🔥 텍스트 추출 (강화 버전)
                name = link.text.strip()

                if not name:
                    name = link.get_attribute("innerText").strip()

                if not name:
                    name = link.get_attribute("textContent").strip()

                # 그래도 없으면 skip
                if not name:
                    continue

                # 🔥 가짜 링크 제거
                if not url or url.startswith("javascript") or "#" in url:
                    continue

                valid_links.append((name, url))

            # =========================
            # ✅ CASE 1: 하위 링크 있음
            # =========================
            if valid_links:
                for name, url in valid_links:
                    print(f"  - {name} ({url})")
                    tasks.append({
                        'category': category_name,
                        'name': name,
                        'url': url
                    })
            else:
                if category_url and 'javascript' not in category_url:
                    print(f"  - {name} ({url})")
                    tasks.append({
                        'category': category_name,
                        'name': "",
                        'url': category_url
                    })

        except Exception as e:
            print("에러:", e)

    print(f"총 {len(tasks)}개의 페이지를 수집합니다.")
    for task in tasks:
        try:
            print(f"작업 중: [{task['category']}] > {task['name']}")
            save_content(task['url'], task['category'], task['name'])
        except Exception as e:
            print(f"{task['name']} 저장 실패: {e}")


if __name__ == "__main__":
    try:
        start_crawl()
    finally:
        driver.quit()
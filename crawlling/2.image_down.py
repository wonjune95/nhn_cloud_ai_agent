import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

ROOT_DIR = "./nhn_cloud_docs"

def download_and_replace_images(html_path):
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    # HTML 기준 base URL (없으면 NHN docs 기본)
    base_url = "https://docs.nhncloud.com"

    # 이미지 저장 폴더 (html 기준 상대경로)
    img_dir = os.path.join(os.path.dirname(html_path), "images")
    os.makedirs(img_dir, exist_ok=True)

    img_tags = soup.find_all("img")

    for idx, img in enumerate(img_tags):
        src = img.get("src")

        if not src:
            continue

        # 절대 URL 변환
        img_url = urljoin(base_url, src)

        # 🔥 CDN 아닌 이상한 링크 제거
        if not img_url.startswith("http"):
            continue

        try:
            response = requests.get(img_url, timeout=5)
            if response.status_code != 200:
                continue

            # 파일 확장자 추출
            parsed = urlparse(img_url)
            ext = os.path.splitext(parsed.path)[-1] or ".png"

            filename = f"img_{idx}{ext}"
            filepath = os.path.join(img_dir, filename)

            # 저장
            with open(filepath, "wb") as f:
                f.write(response.content)

            # 🔥 HTML 경로 수정 (상대경로)
            img["src"] = f"./images/{filename}"

            print(f"[다운로드] {img_url} → {filepath}")

        except Exception as e:
            print("이미지 실패:", img_url, e)

    # 🔥 HTML 덮어쓰기
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))


def process_all_html(root_dir):
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".html"):
                html_path = os.path.join(root, file)
                print(f"\n처리 중: {html_path}")
                download_and_replace_images(html_path)


if __name__ == "__main__":
    process_all_html(ROOT_DIR)
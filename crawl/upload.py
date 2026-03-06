import os
import glob
import requests
import time

NOVEL_ID = 5
BASE_URL = "http://127.0.0.1:8000/api"
CHAPTERS_DIR = os.path.join(os.path.dirname(__file__), "chapters")

def main():
    if not os.path.exists(CHAPTERS_DIR):
        print(f"Directory {CHAPTERS_DIR} does not exist.")
        return

    # Find all chapter_*.txt files
    files = glob.glob(os.path.join(CHAPTERS_DIR, "chapter_*.txt"))
    # Sort files by chapter number extracted from filename
    try:
        files.sort(key=lambda f: int(os.path.basename(f).replace('chapter_', '').replace('.txt', '')))
    except ValueError:
        files.sort()

    if not files:
        print("No chapters found to upload.")
        return

    print(f"Found {len(files)} chapters. Preparing to upload to Novel ID: {NOVEL_ID}...")

    # Read and combine all chapters into one big text format
    # This is much more efficient than hitting the DB 20+ times individually.
    combined_text = ""
    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            # Thêm khoảng trắng giữa các chương để file_parser nhận diện chính xác
            combined_text += content + "\n\n\n"

    print("Sending text to the backend for processing and splitting...")
    
    # 1. Upload the combined text
    response = requests.post(
        f"{BASE_URL}/novels/{NOVEL_ID}/chapters/paste",
        json={
            "text": combined_text,
            "auto_translate": False  # Chúng ta sẽ trigger thủ công ở bước 2
        }
    )

    if response.status_code == 200:
        print(f"✅ Upload successful! All {len(files)} chapters added.")
    else:
        print(f"❌ Upload failed: {response.status_code} - {response.text}")
        return

    # 2. Start the background translation process
    print("Starting translation process...")
    trans_response = requests.post(f"{BASE_URL}/translate/novel/{NOVEL_ID}")
    
    if trans_response.status_code == 200:
        print("✅ Translation started! AI is now translating sequentially in the background.")
    else:
        print(f"❌ Failed to start translation: {trans_response.status_code} - {trans_response.text}")

if __name__ == "__main__":
    main()

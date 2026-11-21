from dotenv import load_dotenv

load_dotenv()  # 讀取 .env（只在本機開發用；.env 在 .gitignore 裡，正式環境用 GitHub Secrets / 環境變數）

from app import create_app  # noqa: E402  要在 load_dotenv 之後 import，才讀得到環境變數

app = create_app()

if __name__ == "__main__":
    app.run(debug=app.config["APP_ENV"] != "production", port=5000)

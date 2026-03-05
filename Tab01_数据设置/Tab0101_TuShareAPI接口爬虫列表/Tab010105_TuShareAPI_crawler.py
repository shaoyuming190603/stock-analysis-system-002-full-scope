# This Python file uses the following encoding: utf-8

# if __name__ == "__main__":
#     pass
import requests
from bs4 import BeautifulSoup
from parser import parse_api_page
from utils import ensure_dir

class Crawler:
    def __init__(self, logger):
        self.logger = logger
        self.visited = set()

    def crawl_all(self, root_url):
        self.visited = set()
        all_data = []
        self.logger.log(f"开始递归爬取：{root_url}")
        self._crawl_recursive(root_url, all_data)
        return all_data

    def _crawl_recursive(self, url, all_data):
        if url in self.visited:
            return
        self.visited.add(url)
        self.logger.log(f"访问页面：{url}")
        try:
            resp = requests.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            page_data = parse_api_page(soup, url)
            if page_data:
                if page_data["api_name"] == "index_classify":
                    self.logger.log(f"忽略接口：{url}")
                else:
                    all_data.append(page_data)
            # 查找所有子页面链接
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith("/document/2?doc_id="):
                    full_url = "https://tushare.pro" + href
                    self._crawl_recursive(full_url, all_data)
        except Exception as e:
            self.logger.log(f"爬取失败：{url}，原因：{e}")

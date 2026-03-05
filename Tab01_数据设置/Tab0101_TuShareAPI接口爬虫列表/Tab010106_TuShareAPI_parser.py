# This Python file uses the following encoding: utf-8

# if __name__ == "__main__":
#     pass
def parse_api_page(soup, url):
    # 1. 提取接口名
    api_name = None
    for tag in soup.find_all(text=lambda t: "接口：" in t):
        api_name = tag.split("接口：")[-1].strip()
        break
    if not api_name:
        return None

    # 2. 提取标题
    title = None
    for h2 in soup.find_all("h2"):
        if h2.get_text(strip=True):
            title = h2.get_text(strip=True)
            break

    # 3. 输入参数表
    input_params, input_types, input_defaults = [], [], []
    input_table = None
    for tag in soup.find_all(text=lambda t: "输入参数" in t):
        input_table = tag.find_parent("table")
        break
    if input_table:
        for row in input_table.find_all("tr")[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) >= 4:
                input_params.append(cols[0])
                input_types.append(cols[1])
                input_defaults.append(cols[2])

    # 4. 输出参数表
    output_params, output_types, output_defaults = [], [], []
    output_table = None
    for tag in soup.find_all(text=lambda t: "输出参数" in t):
        output_table = tag.find_parent("table")
        break
    if output_table:
        for row in output_table.find_all("tr")[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) >= 4:
                output_params.append(cols[0])
                output_types.append(cols[1])
                output_defaults.append(cols[2])

    return {
        "api_name": api_name,
        "title": title,
        "url": url,
        "input_params": input_params,
        "input_types": input_types,
        "input_defaults": input_defaults,
        "output_params": output_params,
        "output_types": output_types,
        "output_defaults": output_defaults,
    }

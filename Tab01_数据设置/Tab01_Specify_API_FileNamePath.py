import os
from datetime import datetime



# def save_log(self):
def save_log(txt_Specify_Initial_Path,txt_Specify_API_log_Name,pushBttn_API_GeneratList):

    # 获取当前文件夹
    # current_dir = os.getcwd()

    # 获取指定的API初始化路径文本控件名称：txt_Specify_Initial
    api_initial_path_obj_name=txt_Specify_Initial_Path.objectName()

    # 获取指定的API初始化路径文本，控件名称：txt_Specify_Initial_Path
    api_initial_path=txt_Specify_Initial_Path.toPlainText()


    # 获取PlainTextEdit控件名称: txt_Specify_API_log_Name
    api_log_obj_name = txt_Specify_API_log_Name.objectName()

    # 获取PlainTextEdit内容，控件名称：txt_Specify_API_log_Name
    api_initial_log_text = txt_Specify_API_log_Name.toPlainText()


    # 获取按钮控件名称：pushBttn_API_GeneratList
    api_gen_btn_name = pushBttn_API_GeneratList.objectName()

    # 获取当前时间
    now = datetime.now()
    time_str = now.strftime("%Y%m%d_%H%M%S")

    # 生成log文件名
    log_filename = f"{api_initial_log_text}_{time_str}.log"
    log_filename = log_filename.replace(" ", "_")  # 避免空格
    log_path = os.path.join(api_initial_path, log_filename)
    # 写入内容
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"API清单创建日期时间: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"API log文件名的控件名称: {api_log_obj_name}\n")
        f.write(f"API log文件名: {api_initial_log_text}\n")
        f.write(f"文件保存路径控件名称: {api_initial_path_obj_name}\n")
        f.write(f"文件保存路径: {api_initial_path}\n")
        f.write(f"触发生成API清单的按钮控件名称: {api_gen_btn_name}\n")

    print(f"日志已保存: {log_path}")
    print("Hello from Tab01_Specify_API_FileNamePath!")

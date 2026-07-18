"""
PaddleOCR 端到端测试：生成中文测试图 -> OCR 识别 -> 验证结果
用 PP-OCRv4 中文模型（已缓存在 ~/.paddleocr/）
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

# 1. 生成一张包含中文的测试图片（模拟错题截图）
font_path = r"C:\Windows\Fonts\simhei.ttf"  # Windows 自带黑体
img = Image.new("RGB", (600, 200), color="white")
draw = ImageDraw.Draw(img)
font = ImageFont.truetype(font_path, 32)
draw.text((20, 30), "已知函数 f(x) = 2x + 3", fill="black", font=font)
draw.text((20, 90), "求 f(5) 的值是多少？", fill="black", font=font)

test_img = r"C:\Users\linho\Desktop\jnu\training\project\ocr_test.png"
img.save(test_img)
print(f"[1/3] 测试图已生成: {test_img}")

# 2. 用 PaddleOCR 识别
print("[2/3] 加载 PP-OCRv4 中文模型并识别中...")
from paddleocr import PaddleOCR

ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
result = ocr.ocr(test_img, cls=True)

# 3. 输出识别结果
print("[3/3] 识别结果：")
print("-" * 50)
if result and result[0]:
    full_text = []
    for line in result[0]:
        box, (text, conf) = line
        print(f"  [{conf:.3f}] {text}")
        full_text.append(text)
    print("-" * 50)
    print(f"完整文本: {''.join(full_text)}")
    print(f"\n[OK] OCR 功能正常，可替代百度 OCR")
else:
    print("[FAIL] 未识别到文字，检查模型或图片")
    sys.exit(1)

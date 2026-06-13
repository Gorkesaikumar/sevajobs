import sys
from PIL import Image

def process_logo(input_path, output_white_path, output_dark_path):
    try:
        img = Image.open(input_path)
        img = img.convert("RGBA")
        datas = img.getdata()
        
        # 1. White text version (for dark backgrounds)
        new_data_white = []
        for item in datas:
            r, g, b, a = item
            if r > 180 and g > 180 and b < 180:
                new_data_white.append((255, 255, 255, 0))
            else:
                if r < 100 and g < 100 and b < 100:
                    new_data_white.append((255, 255, 255, 255))
                else:
                    new_data_white.append((r, g, b, 255))
        img_white = Image.new("RGBA", img.size)
        img_white.putdata(new_data_white)
        img_white.save(output_white_path, "PNG")
        print(f"Saved {output_white_path}")

        # 2. Dark text version (for light backgrounds)
        new_data_dark = []
        for item in datas:
            r, g, b, a = item
            if r > 180 and g > 180 and b < 180:
                new_data_dark.append((255, 255, 255, 0))
            else:
                if r < 100 and g < 100 and b < 100:
                    new_data_dark.append((0, 0, 0, 255))
                else:
                    new_data_dark.append((r, g, b, 255))
        img_dark = Image.new("RGBA", img.size)
        img_dark.putdata(new_data_dark)
        img_dark.save(output_dark_path, "PNG")
        print(f"Saved {output_dark_path}")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    process_logo(r"d:\sevajobs\static\images\logo.jpg", 
                 r"d:\sevajobs\static\images\logo.png",
                 r"d:\sevajobs\static\images\logo_dark.png")

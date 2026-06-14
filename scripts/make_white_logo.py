from PIL import Image

def make_white_bg():
    img = Image.open('d:\\sevajobs\\static\\images\\logo.jpg').convert('L')
    d = img.getdata()
    new_d = []
    for p in d:
        # Yellow background has luminance ~215. Black text is ~0.
        # We stretch the contrast so anything > 180 becomes 255 (white)
        # anything < 80 becomes 0 (black)
        if p > 180:
            new_d.append((255, 255, 255))
        elif p < 80:
            new_d.append((0, 0, 0))
        else:
            # Interpolate the grey edge
            val = int((p - 80) * 255 / (180 - 80))
            new_d.append((val, val, val))
            
    out = Image.new('RGB', img.size)
    out.putdata(new_d)
    out.save('d:\\sevajobs\\static\\images\\logo_white.png')
    print("Created logo_white.png")

if __name__ == '__main__':
    make_white_bg()

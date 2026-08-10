from pathlib import Path
from PIL import Image

input_folder = Path("../labware_cache/")
output_folder = input_folder / "compressed"
output_folder.mkdir(exist_ok=True)

quality = 30   # lower = more compression, smaller file, worse quality

for img_path in input_folder.glob("*.jpg"):
    img = Image.open(img_path)
    save_path = output_folder / img_path.name
    img.save(save_path, "JPEG", quality=quality, optimize=True)
    print(f"Saved: {save_path}")

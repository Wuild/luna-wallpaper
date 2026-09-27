from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
root = Path(__file__).resolve().parent.parent
output = root / 'luna-wallpaper@wuild.shell-extension.zip'
with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
    for path in sorted((root / 'dist').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            archive.write(path, path.relative_to(root / 'dist'))
print(output)
